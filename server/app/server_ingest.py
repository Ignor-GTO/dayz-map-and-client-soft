"""Ingest player positions from a SCUM game server (RCON / log agent)."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import channel_key
from app.elevation_service import record_elevation_sample
from app.models import MapDeath, Position, Room, ServerApiKey, User
from app.websocket import manager

_STEAM_ID_RE = re.compile(r"^\d{15,20}$")
_TRAVEL_MODES = {"foot", "vehicle"}
_VEHICLE_ROLES = {"driver", "passenger"}


def normalize_steam_id(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if not _STEAM_ID_RE.match(raw):
        return None
    return raw


def normalize_z(raw: dict) -> float | None:
    if "z" not in raw or raw.get("z") is None:
        return None
    try:
        z = float(raw["z"])
    except (TypeError, ValueError):
        return None
    if not (abs(z) < 1_000_000):
        return None
    return z


def normalize_travel_fields(raw: dict) -> tuple[str | None, str | None, str | None]:
    """Parse travel_mode / vehicle_role / vehicle_type from ingest payload."""
    mode_raw = raw.get("travel_mode")
    mode = str(mode_raw).strip().lower() if mode_raw is not None else None
    if mode not in _TRAVEL_MODES:
        mode = None

    role_raw = raw.get("vehicle_role")
    role = str(role_raw).strip().lower() if role_raw is not None else None
    if role not in _VEHICLE_ROLES:
        role = None

    type_raw = raw.get("vehicle_type")
    vtype: str | None
    if type_raw is None:
        vtype = None
    else:
        vtype = str(type_raw).strip()[:64] or None

    if mode == "foot":
        role = None
        vtype = None
    return mode, role, vtype


def position_event_data(user: User, position: Position) -> dict:
    return {
        "user_id": user.id,
        "nickname": user.nickname,
        "avatar_url": user.avatar_url,
        "x": position.x,
        "y": position.y,
        "z": position.z,
        "updated_at": position.updated_at.isoformat(),
        "travel_mode": position.travel_mode,
        "vehicle_role": position.vehicle_role,
        "vehicle_type": position.vehicle_type,
    }


async def find_user_for_ingest(
    db: AsyncSession,
    *,
    map_id: int,
    room_id: int | None,
    steam_id: str | None,
    nickname: str | None,
) -> User | None:
    """Match map user by steam_id first, then nickname (case-insensitive)."""
    base = (
        select(User)
        .join(Room, User.room_id == Room.id)
        .options(selectinload(User.room).selectinload(Room.map))
        .where(Room.map_id == map_id)
    )
    if room_id is not None:
        base = base.where(User.room_id == room_id)

    sid = normalize_steam_id(steam_id)
    if sid:
        result = await db.execute(base.where(User.steam_id == sid).limit(1))
        user = result.scalar_one_or_none()
        if user:
            return user

    nick = (nickname or "").strip()
    if nick:
        result = await db.execute(
            base.where(func.lower(User.nickname) == nick.lower()).limit(1)
        )
        return result.scalar_one_or_none()
    return None


async def upsert_user_position(
    db: AsyncSession,
    user: User,
    x: float,
    y: float,
    *,
    z: float | None = None,
    update_z: bool = False,
    travel_mode: str | None = None,
    vehicle_role: str | None = None,
    vehicle_type: str | None = None,
    update_travel: bool = False,
) -> Position:
    result = await db.execute(select(Position).where(Position.user_id == user.id))
    position = result.scalar_one_or_none()
    if position:
        position.x = x
        position.y = y
        position.updated_at = datetime.now(timezone.utc)
        if update_z:
            position.z = z
        if update_travel:
            position.travel_mode = travel_mode
            position.vehicle_role = vehicle_role
            position.vehicle_type = vehicle_type
    else:
        position = Position(
            user_id=user.id,
            x=x,
            y=y,
            z=z if update_z else None,
            travel_mode=travel_mode if update_travel else None,
            vehicle_role=vehicle_role if update_travel else None,
            vehicle_type=vehicle_type if update_travel else None,
        )
        db.add(position)
    await db.flush()
    await db.refresh(position)
    return position


async def broadcast_position(user: User, position: Position) -> None:
    room = user.room
    if room is None or room.map_id is None:
        return
    ch = channel_key(room.map_id, room.id)
    await manager.broadcast(
        ch,
        {
            "type": "position",
            "data": position_event_data(user, position),
        },
    )


async def ingest_players(
    db: AsyncSession,
    api_key: ServerApiKey,
    players: list[dict],
) -> dict:
    updated = 0
    skipped: list[dict] = []
    map_slug = (api_key.map.slug if api_key.map else None) or ""

    for raw in players:
        steam_id = raw.get("steam_id")
        nickname = raw.get("nickname")
        try:
            x = float(raw["x"])
            y = float(raw["y"])
        except (KeyError, TypeError, ValueError):
            skipped.append(
                {
                    "steam_id": steam_id,
                    "nickname": nickname,
                    "reason": "invalid_coords",
                }
            )
            continue

        z = normalize_z(raw)
        # Always feed height map from bridge samples (even unmatched players).
        if map_slug and z is not None:
            record_elevation_sample(map_slug, x, y, z)

        user = await find_user_for_ingest(
            db,
            map_id=api_key.map_id,
            room_id=api_key.room_id,
            steam_id=str(steam_id) if steam_id is not None else None,
            nickname=str(nickname) if nickname is not None else None,
        )
        if not user:
            skipped.append(
                {
                    "steam_id": steam_id,
                    "nickname": nickname,
                    "reason": "user_not_found",
                }
            )
            continue

        travel_mode, vehicle_role, vehicle_type = normalize_travel_fields(raw)
        update_travel = any(k in raw for k in ("travel_mode", "vehicle_role", "vehicle_type"))
        position = await upsert_user_position(
            db,
            user,
            x,
            y,
            z=z,
            update_z=("z" in raw),
            travel_mode=travel_mode,
            vehicle_role=vehicle_role,
            vehicle_type=vehicle_type,
            update_travel=update_travel,
        )
        await broadcast_position(user, position)
        updated += 1

    api_key.last_used_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True, "updated": updated, "skipped": skipped}


async def ingest_events(
    db: AsyncSession,
    api_key: ServerApiKey,
    events: list[dict],
) -> dict:
    """Ingest bridge events. Currently supports type=death."""
    from datetime import datetime as dt
    from datetime import timedelta

    created = 0
    skipped: list[dict] = []
    map_slug = (api_key.map.slug if api_key.map else None) or ""
    created_payloads: list[dict] = []

    for raw in events:
        event_type = str(raw.get("type") or "death").strip().lower()
        if event_type != "death":
            skipped.append(
                {
                    "type": event_type,
                    "steam_id": raw.get("steam_id"),
                    "reason": "unsupported_type",
                }
            )
            continue
        try:
            x = float(raw["x"])
            y = float(raw["y"])
        except (KeyError, TypeError, ValueError):
            skipped.append(
                {
                    "steam_id": raw.get("steam_id"),
                    "nickname": raw.get("nickname"),
                    "reason": "invalid_coords",
                }
            )
            continue

        # Bridge also skips 0,0 — reject near-origin junk.
        if abs(x) < 1.0 and abs(y) < 1.0:
            skipped.append(
                {
                    "steam_id": raw.get("steam_id"),
                    "nickname": raw.get("nickname"),
                    "reason": "zero_coords",
                }
            )
            continue

        z = normalize_z(raw)
        steam_id = normalize_steam_id(str(raw.get("steam_id") or "") or None)
        nickname = str(raw.get("nickname") or "").strip() or steam_id or "Игрок"
        profile_id = raw.get("profile_id")
        try:
            profile_id_int = int(profile_id) if profile_id is not None else None
        except (TypeError, ValueError):
            profile_id_int = None

        died_at = datetime.now(timezone.utc)
        at_raw = raw.get("at")
        if at_raw:
            try:
                parsed = dt.fromisoformat(str(at_raw).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                died_at = parsed
            except ValueError:
                pass

        window_start = died_at - timedelta(minutes=2)
        dedup_q = select(MapDeath).where(
            MapDeath.map_id == api_key.map_id,
            MapDeath.died_at >= window_start,
            MapDeath.x >= x - 50,
            MapDeath.x <= x + 50,
            MapDeath.y >= y - 50,
            MapDeath.y <= y + 50,
        )
        if profile_id_int is not None:
            dedup_q = dedup_q.where(MapDeath.profile_id == profile_id_int)
        elif steam_id:
            dedup_q = dedup_q.where(MapDeath.steam_id == steam_id)
        else:
            dedup_q = dedup_q.where(func.lower(MapDeath.nickname) == nickname.lower())
        existing = (await db.execute(dedup_q.limit(1))).scalar_one_or_none()
        if existing:
            skipped.append(
                {
                    "steam_id": steam_id,
                    "nickname": nickname,
                    "profile_id": profile_id_int,
                    "reason": "duplicate",
                }
            )
            continue

        death = MapDeath(
            map_id=api_key.map_id,
            room_id=api_key.room_id,
            steam_id=steam_id,
            nickname=nickname[:64],
            profile_id=profile_id_int,
            x=x,
            y=y,
            z=z,
            died_at=died_at,
        )
        db.add(death)
        await db.flush()
        created += 1

        if map_slug and z is not None:
            record_elevation_sample(map_slug, x, y, z)

        created_payloads.append(
            {
                "id": death.id,
                "nickname": death.nickname,
                "steam_id": death.steam_id,
                "profile_id": death.profile_id,
                "x": death.x,
                "y": death.y,
                "z": death.z,
                "died_at": death.died_at.isoformat(),
            }
        )

    api_key.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    if created_payloads:
        if api_key.room_id is not None:
            room_ids = [api_key.room_id]
        else:
            result = await db.execute(select(Room.id).where(Room.map_id == api_key.map_id))
            room_ids = list(result.scalars().all())
        for room_id in room_ids:
            ch = channel_key(api_key.map_id, room_id)
            for payload in created_payloads:
                await manager.broadcast(ch, {"type": "death", "data": payload})

    return {"ok": True, "created": created, "skipped": skipped}
