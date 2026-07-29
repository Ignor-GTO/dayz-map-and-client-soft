"""Ingest player positions from a SCUM game server (RCON / log agent)."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import channel_key
from app.models import Position, Room, ServerApiKey, User
from app.websocket import manager

_STEAM_ID_RE = re.compile(r"^\d{15,20}$")


def normalize_steam_id(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    if not _STEAM_ID_RE.match(raw):
        return None
    return raw


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
) -> Position:
    result = await db.execute(select(Position).where(Position.user_id == user.id))
    position = result.scalar_one_or_none()
    if position:
        position.x = x
        position.y = y
        position.updated_at = datetime.now(timezone.utc)
    else:
        position = Position(user_id=user.id, x=x, y=y)
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
            "data": {
                "user_id": user.id,
                "nickname": user.nickname,
                "avatar_url": user.avatar_url,
                "x": position.x,
                "y": position.y,
                "updated_at": position.updated_at.isoformat(),
            },
        },
    )


async def ingest_players(
    db: AsyncSession,
    api_key: ServerApiKey,
    players: list[dict],
) -> dict:
    updated = 0
    skipped: list[dict] = []

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

        position = await upsert_user_position(db, user, x, y)
        await broadcast_position(user, position)
        updated += 1

    api_key.last_used_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True, "updated": updated, "skipped": skipped}
