import json
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, File
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import (
    authenticate_client,
    authenticate_server_api_key,
    channel_key,
    clear_session,
    generate_client_key,
    get_current_user,
    get_map_by_slug,
    get_or_create_room,
    hash_client_key,
    hash_password,
    read_session_client_key,
    set_session,
    user_has_admin_panel_access,
    verify_password,
)
from app.database import get_db
from app.locations_service import get_map_locations
from app.radiation_service import get_map_radiation
from app.maps_service import list_enabled_maps, resolve_map_config
from app.marker_upload import delete_marker_image_file, save_marker_image
from app.avatar_upload import delete_avatar_file, save_avatar_image
from app.accounts import (
    adopt_matching_memberships,
    avatar_url_of,
    broadcast_avatar_to_memberships,
    create_account_for_user,
    ensure_user_account,
    find_account_for_new_membership,
    list_memberships_for_account,
    profile_password_hash_of,
    sync_all_memberships,
    sync_membership_profile_fields,
    verify_user_profile_password,
)
from app.poi_icons import normalize_poi_icon
from app.poi_upload import delete_poi_image_file, save_poi_image
from app.models import MapDeath, MapPoi, Marker, Position, Room, ServerApiKey, Trader, TraderItem, TraderSection, TraderSubsection, User
from app.roads_service import create_segment, delete_segment, find_route, list_segments
from app.elevation_service import elevation_stats, lookup_elevation
from app.server_ingest import ingest_events, ingest_players, position_event_data
from app.schemas import (
    ClientSteamIdRequest,
    CoordsPayload,
    LoginRequest,
    LoginRequirementsRequest,
    LoginRequirementsResponse,
    LoginResponse,
    ServerPositionsRequest,
    ServerPositionsResponse,
    ServerEventsRequest,
    ServerEventsResponse,
    DeathEventResponse,
    MapConfigResponse,
    MapListItem,
    MapLocationsResponse,
    MapRadiationResponse,
    MapBuildingResponse,
    MarkerCreateRequest,
    MarkerResponse,
    MarkerUpdateRequest,
    NavigateRequest,
    NavigateResponse,
    PoiResponse,
    PositionResponse,
    ProfilePasswordRequest,
    PromoteMarkerToPoiRequest,
    RoadSegmentResponse,
    RoomSettingsResponse,
    RoomSettingsUpdateRequest,
    RoomStateResponse,
    StaffPoiCreateRequest,
    StaffPoiUpdateRequest,
    SwitchMembershipRequest,
    ProfileSteamIdRequest,
    TraderItemResponse,
)
from app.buildings_service import list_buildings
from app.seed import DEFAULT_MAP_SLUG
from app.settings_service import is_public_pin_creation
from app.websocket import manager

router = APIRouter(prefix="/api")

STASH_MANAGER_ROLES = {"admin", "moderator"}
# Map-scoped categories visible to all PIN groups on the same map.
MAP_SCOPED_MARKER_CATEGORIES = frozenset({"stash", "mutants", "hunting"})


def _can_manage_stashes(user: User) -> bool:
    return (user.role or "user") in STASH_MANAGER_ROLES


def _can_manage_map_staff(user: User) -> bool:
    return _can_manage_stashes(user)


def _marker_category_value(marker: Marker) -> str:
    return marker.marker_category or "group"


def _is_map_scoped_category(category: str | None) -> bool:
    return (category or "group") in MAP_SCOPED_MARKER_CATEGORIES


def _is_map_scoped_marker(marker: Marker) -> bool:
    return _is_map_scoped_category(_marker_category_value(marker)) and marker.map_id is not None


def _is_stash_marker(marker: Marker) -> bool:
    """True for any map-scoped server category (stash / mutants / hunting)."""
    return _is_map_scoped_marker(marker) or _is_map_scoped_category(_marker_category_value(marker))


def _marker_edit_allowed(user: User, marker: Marker) -> bool:
    if _is_stash_marker(marker):
        return _can_manage_stashes(user) and marker.map_id == user.room.map_id
    if marker.user.room_id == user.room_id:
        return True
    return _can_manage_map_staff(user) and marker.user.room.map_id == user.room.map_id


def _marker_delete_allowed(user: User, marker: Marker) -> bool:
    if _is_stash_marker(marker):
        return _can_manage_stashes(user) and marker.map_id == user.room.map_id
    if marker.user_id == user.id:
        return True
    return _can_manage_map_staff(user) and marker.user.room.map_id == user.room.map_id


async def _broadcast_pois_changed(db: AsyncSession, map_id: int) -> None:
    await _broadcast_to_map(db, map_id, {"type": "pois_changed"})


async def _trader_name_for_poi(db: AsyncSession, map_id: int, poi_id: int) -> str | None:
    result = await db.execute(
        select(Trader.name).where(Trader.map_id == map_id, Trader.poi_id == poi_id)
    )
    return result.scalar_one_or_none()


async def _poi_response(db: AsyncSession, poi: MapPoi) -> PoiResponse:
    trader_name = await _trader_name_for_poi(db, poi.map_id, poi.id)
    return PoiResponse(
        id=poi.id,
        title=poi.title,
        description=poi.description or "",
        description_image_url=poi.description_image_url,
        icon=poi.icon or "star",
        x=poi.x,
        y=poi.y,
        trader_name=trader_name,
    )


async def _get_map_poi(db: AsyncSession, map_id: int, poi_id: int) -> MapPoi:
    poi = await db.get(MapPoi, poi_id)
    if not poi or poi.map_id != map_id:
        raise HTTPException(status_code=404, detail="POI not found")
    return poi


def _can_manage_room(user: User) -> bool:
    room = user.room
    if room.created_by_user_id is None:
        return False
    return room.created_by_user_id == user.id


def _ensure_room_owner(room: Room, user: User) -> None:
    if room.created_by_user_id is None:
        room.created_by_user_id = user.id
    elif room.created_by_user_id != user.id:
        raise HTTPException(status_code=403, detail="Только создатель группы может изменять её настройки")


def _verify_room_entry_password(room: Room, room_password: str | None) -> None:
    if not room.entry_password_hash:
        return
    if not room_password or not verify_password(room_password, room.entry_password_hash):
        raise HTTPException(status_code=401, detail="Неверный пароль группы")


def _verify_profile_password(user: User, profile_password: str | None) -> None:
    if not profile_password_hash_of(user):
        return
    if not verify_user_profile_password(user, profile_password):
        raise HTTPException(status_code=401, detail="Неверный пароль профиля")


def _marker_nickname(marker: Marker) -> str:
    if _is_map_scoped_marker(marker):
        return "Сервер"
    if marker.user:
        return marker.user.nickname
    return "?"


async def _broadcast_to_map(db: AsyncSession, map_id: int, message: dict) -> None:
    result = await db.execute(select(Room.id).where(Room.map_id == map_id))
    for room_id in result.scalars().all():
        await manager.broadcast(channel_key(map_id, room_id), message)


async def _broadcast_marker_event(
    db: AsyncSession,
    user: User,
    marker: Marker,
    event: dict,
) -> None:
    if _is_map_scoped_marker(marker):
        await _broadcast_to_map(db, user.room.map_id, event)
    else:
        await manager.broadcast(channel_key(user.room.map_id, user.room_id), event)


def _load_marker_points(marker: Marker) -> list[list[float]] | None:
    if not marker.points_json:
        return None
    try:
        parsed = json.loads(marker.points_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    points: list[list[float]] = []
    for point in parsed:
        if (
            isinstance(point, list)
            and len(point) >= 2
            and isinstance(point[0], (int, float))
            and isinstance(point[1], (int, float))
        ):
            points.append([float(point[0]), float(point[1])])
    return points or None


def _normalize_points(points: list[list[float]] | None) -> list[list[float]] | None:
    if not points:
        return None
    normalized: list[list[float]] = []
    for point in points:
        if len(point) < 2:
            continue
        normalized.append([float(point[0]), float(point[1])])
    return normalized or None


def _normalize_marker_category(value: str | None) -> str:
    category = str(value or "group").strip().lower()
    if category not in {"group", "stash", "mutants", "hunting"}:
        raise HTTPException(status_code=400, detail="Unsupported marker_category")
    return category


def _marker_response(
    marker: Marker,
    nickname: str,
    avatar_url: str | None = None,
) -> MarkerResponse:
    points = _load_marker_points(marker)
    if avatar_url is None and marker.user:
        avatar_url = marker.user.avatar_url
    return MarkerResponse(
        id=marker.id,
        user_id=marker.user_id,
        nickname=nickname,
        avatar_url=avatar_url,
        x=marker.x,
        y=marker.y,
        type=marker.type,
        marker_category=marker.marker_category or "group",
        title=marker.title,
        description=marker.description,
        image_url=marker.image_url,
        geometry_kind=marker.geometry_kind or "point",
        points=points,
        radius=marker.radius,
        stroke_color=marker.stroke_color,
        fill_color=marker.fill_color,
        created_at=marker.created_at,
    )



@router.get("/maps", response_model=list[MapListItem])
async def list_maps(db: Annotated[AsyncSession, Depends(get_db)]):
    return await list_enabled_maps(db)


@router.get("/maps/{slug}/config", response_model=MapConfigResponse)
async def map_config(slug: str, db: Annotated[AsyncSession, Depends(get_db)]):
    return await resolve_map_config(db, slug)


@router.get("/maps/{slug}/locations", response_model=MapLocationsResponse)
async def map_locations(slug: str, db: Annotated[AsyncSession, Depends(get_db)]):
    game_map = await get_map_by_slug(db, slug)
    data = await get_map_locations(db, game_map)
    return MapLocationsResponse(**data)


@router.get("/maps/{slug}/radiation", response_model=MapRadiationResponse)
async def map_radiation(slug: str, db: Annotated[AsyncSession, Depends(get_db)]):
    game_map = await get_map_by_slug(db, slug)
    data = await get_map_radiation(db, game_map)
    return MapRadiationResponse(**data)


@router.get("/maps/{slug}/elevation")
async def map_elevation(
    slug: str,
    x: float,
    y: float,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Estimate terrain Z at game coords from bridge-fed elevation samples."""
    await get_map_by_slug(db, slug)
    result = lookup_elevation(slug, x, y)
    stats = elevation_stats(slug)
    result["cells"] = stats.get("cells")
    result["cell_size"] = stats.get("cell_size")
    return result


@router.get("/maps/{slug}/traders/items", response_model=list[TraderItemResponse])
async def map_trader_items(
    slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    q: str = "",
    limit: int = 250,
):
    game_map = await get_map_by_slug(db, slug)
    needle = q.strip().casefold()
    limit = max(1, min(limit, 20000))

    stmt = (
        select(
            TraderItem.id.label("item_id"),
            TraderItem.subsection_id,
            TraderItem.name.label("item_name"),
            TraderItem.buy_price,
            TraderItem.sell_price,
            TraderSubsection.id.label("subsection_id_value"),
            TraderSubsection.name.label("subsection_name"),
            TraderSection.id.label("section_id"),
            TraderSection.name.label("section_name"),
            Trader.id.label("trader_id"),
            Trader.name.label("trader_name"),
            Trader.x.label("trader_x"),
            Trader.y.label("trader_y"),
        )
        .join(TraderSubsection, TraderSubsection.id == TraderItem.subsection_id)
        .join(TraderSection, TraderSection.id == TraderSubsection.section_id)
        .join(Trader, Trader.id == TraderSection.trader_id)
        .where(Trader.map_id == game_map.id)
    )
    stmt = stmt.order_by(TraderItem.name.asc(), Trader.name.asc())

    rows = (await db.execute(stmt)).all()
    out: list[TraderItemResponse] = []
    for row in rows:
        if needle and needle not in str(row.item_name or "").casefold():
            continue
        out.append(
            TraderItemResponse(
                id=row.item_id,
                subsection_id=row.subsection_id,
                section_id=row.section_id,
                trader_id=row.trader_id,
                map_id=game_map.id,
                trader=row.trader_name,
                trader_x=row.trader_x,
                trader_y=row.trader_y,
                section=row.section_name,
                subsection=row.subsection_name,
                name=row.item_name,
                buy_price=int(row.buy_price or 0),
                sell_price=int(row.sell_price or 0),
            )
        )
        if len(out) >= limit:
            break
    return out


@router.get("/map/locations", response_model=MapLocationsResponse)
async def legacy_map_locations(db: Annotated[AsyncSession, Depends(get_db)]):
    """Backward-compatible locations endpoint for older deployments."""
    game_map = await get_map_by_slug(db, DEFAULT_MAP_SLUG)
    data = await get_map_locations(db, game_map)
    return MapLocationsResponse(**data)


@router.get("/map/config", response_model=MapConfigResponse)
async def legacy_map_config(db: Annotated[AsyncSession, Depends(get_db)]):
    """Backward-compatible endpoint for cached old map.js."""
    return await resolve_map_config(db, DEFAULT_MAP_SLUG)


@router.get("/auth/pin-policy")
async def pin_policy(db: Annotated[AsyncSession, Depends(get_db)]):
    return {"public_pin_creation": await is_public_pin_creation(db)}


@router.post("/auth/login-requirements", response_model=LoginRequirementsResponse)
async def login_requirements(
    payload: LoginRequirementsRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    pin = payload.pin.strip()
    nickname = payload.nickname.strip()
    game_map = await get_map_by_slug(db, payload.map_slug.strip().lower())

    result = await db.execute(select(Room).where(Room.map_id == game_map.id, Room.pin == pin))
    room = result.scalar_one_or_none()
    if room is None:
        return LoginRequirementsResponse(
            room_exists=False,
            is_new_user=True,
            room_password_required=False,
            profile_password_required=False,
        )

    result = await db.execute(
        select(User)
        .options(selectinload(User.account))
        .where(User.room_id == room.id, User.nickname == nickname)
    )
    user = result.scalar_one_or_none()
    return LoginRequirementsResponse(
        room_exists=True,
        is_new_user=user is None,
        room_password_required=bool(room.entry_password_hash),
        profile_password_required=bool(user and profile_password_hash_of(user)),
    )


@router.post("/auth/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    pin = payload.pin.strip()
    nickname = payload.nickname.strip()
    game_map = await get_map_by_slug(db, payload.map_slug.strip().lower())

    result = await db.execute(select(Room).where(Room.map_id == game_map.id, Room.pin == pin))
    room = result.scalar_one_or_none()
    room_is_new = False
    if room is None:
        if not await is_public_pin_creation(db):
            raise HTTPException(
                status_code=403,
                detail="Группа с таким PIN не найдена. Создание новых PIN отключено — обратитесь к администратору.",
            )
        room = await get_or_create_room(db, game_map.id, pin)
        room_is_new = True
    else:
        _verify_room_entry_password(room, payload.room_password)

    result = await db.execute(
        select(User)
        .options(selectinload(User.account))
        .where(User.room_id == room.id, User.nickname == nickname)
    )
    user = result.scalar_one_or_none()

    if user:
        _verify_profile_password(user, payload.profile_password)
        account = await ensure_user_account(db, user)
        if payload.profile_password and not account.profile_password_hash:
            account.profile_password_hash = hash_password(payload.profile_password.strip())
            sync_membership_profile_fields(user, account)
        account.display_name = nickname
        await adopt_matching_memberships(db, account)
        client_key = None
        message = "С возвращением! Используйте сохранённый ключ клиента."
    else:
        client_key = generate_client_key()
        profile_hash = None
        raw_pw = (payload.profile_password or "").strip() or None
        if raw_pw:
            if len(raw_pw) < 4:
                raise HTTPException(status_code=400, detail="Пароль профиля — минимум 4 символа")
            profile_hash = hash_password(raw_pw)

        account = await find_account_for_new_membership(
            db,
            nickname=nickname,
            profile_password=raw_pw,
        )
        if account is None:
            account = await create_account_for_user(
                db,
                nickname=nickname,
                profile_password_hash=profile_hash,
            )
        else:
            account.display_name = nickname
            if profile_hash and not account.profile_password_hash:
                account.profile_password_hash = profile_hash

        user = User(
            room_id=room.id,
            nickname=nickname,
            client_key_hash=hash_client_key(client_key),
            profile_password_hash=account.profile_password_hash,
            avatar_url=account.avatar_url,
            steam_id=account.steam_id,
            account_id=account.id,
        )
        db.add(user)
        await db.flush()
        sync_membership_profile_fields(user, account)
        if room.created_by_user_id is None:
            room.created_by_user_id = user.id
        await adopt_matching_memberships(db, account)
        message = "Аккаунт создан. Сохраните ключ клиента — он показывается один раз."
        if account.profile_password_hash:
            message += " Пароль профиля установлен."

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Не удалось создать группу с этим PIN на выбранной карте. Попробуйте другой PIN или обновите сервер.",
        ) from None
    await db.refresh(user)
    set_session(response, user.id, client_key if client_key else None)

    return LoginResponse(
        nickname=nickname,
        pin=pin,
        map_slug=game_map.slug,
        map_name=game_map.name,
        client_key=client_key or "",
        message=message,
    )


@router.post("/auth/reset-key", response_model=LoginResponse)
async def reset_client_key(
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    client_key = generate_client_key()
    user.client_key_hash = hash_client_key(client_key)
    await db.commit()
    await db.refresh(user)
    game_map = user.room.map
    set_session(response, user.id, client_key)
    return LoginResponse(
        nickname=user.nickname,
        pin=user.room.pin,
        map_slug=game_map.slug,
        map_name=game_map.name,
        client_key=client_key,
        message="Новый ключ клиента создан.",
    )


@router.post("/auth/logout")
async def logout(response: Response):
    clear_session(response)
    return {"ok": True}


@router.get("/auth/client-key")
async def get_client_key(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
):
    client_key = read_session_client_key(request)
    if not client_key:
        raise HTTPException(
            status_code=404,
            detail="Ключ не сохранён в сессии. Если потеряли — нажмите «Создать новый ключ».",
        )
    return {"client_key": client_key}


@router.get("/auth/me")
async def me(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    account = await ensure_user_account(db, user)
    await adopt_matching_memberships(db, account)
    await sync_all_memberships(db, account)
    await db.commit()
    memberships = await list_memberships_for_account(
        db, account.id, current_user_id=user.id
    )
    return {
        "nickname": user.nickname,
        "pin": user.room.pin,
        "map_slug": user.room.map.slug,
        "map_name": user.room.map.name,
        "user_id": user.id,
        "account_id": account.id,
        "role": user.role or "user",
        "can_manage_stashes": _can_manage_stashes(user),
        "can_access_admin_panel": await user_has_admin_panel_access(request, db, user),
        "has_profile_password": bool(profile_password_hash_of(user)),
        "can_manage_room": _can_manage_room(user),
        "room_entry_password_enabled": bool(user.room.entry_password_hash),
        "avatar_url": avatar_url_of(user),
        "steam_id": account.steam_id or user.steam_id,
        "memberships": memberships,
    }


@router.post("/auth/switch-membership")
async def switch_membership(
    payload: SwitchMembershipRequest,
    response: Response,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    account = await ensure_user_account(db, user)
    result = await db.execute(
        select(User)
        .options(
            selectinload(User.room).selectinload(Room.map),
            selectinload(User.account),
        )
        .where(User.id == payload.user_id, User.account_id == account.id)
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Членство не найдено в вашем профиле")

    client_key = read_session_client_key(request)
    set_session(response, target.id, client_key)
    memberships = await list_memberships_for_account(
        db, account.id, current_user_id=target.id
    )
    return {
        "ok": True,
        "nickname": target.nickname,
        "pin": target.room.pin,
        "map_slug": target.room.map.slug,
        "map_name": target.room.map.name,
        "user_id": target.id,
        "account_id": account.id,
        "role": target.role or "user",
        "can_manage_stashes": _can_manage_stashes(target),
        "can_access_admin_panel": await user_has_admin_panel_access(request, db, target),
        "has_profile_password": bool(profile_password_hash_of(target)),
        "can_manage_room": _can_manage_room(target),
        "room_entry_password_enabled": bool(target.room.entry_password_hash),
        "avatar_url": avatar_url_of(target),
        "steam_id": account.steam_id or target.steam_id,
        "memberships": memberships,
    }


@router.put("/auth/profile/password")
async def update_profile_password(
    payload: ProfilePasswordRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    account = await ensure_user_account(db, user)
    stored = profile_password_hash_of(user)
    new_password = (payload.new_password or "").strip()
    if stored:
        if not payload.current_password or not verify_password(payload.current_password, stored):
            raise HTTPException(status_code=401, detail="Неверный текущий пароль профиля")

    if not new_password:
        account.profile_password_hash = None
        message = "Пароль профиля отключён. Вход снова только по PIN и никнейму."
    else:
        if len(new_password) < 4:
            raise HTTPException(status_code=400, detail="Пароль профиля — минимум 4 символа")
        account.profile_password_hash = hash_password(new_password)
        message = "Пароль профиля обновлён."

    await sync_all_memberships(db, account)
    await adopt_matching_memberships(db, account)
    await db.commit()
    return {
        "ok": True,
        "has_profile_password": bool(account.profile_password_hash),
        "message": message,
    }


@router.post("/auth/profile/avatar")
async def upload_profile_avatar(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
):
    account = await ensure_user_account(db, user)
    delete_avatar_file(account.avatar_url)
    account.avatar_url = await save_avatar_image(f"acc{account.id}", file)
    await sync_all_memberships(db, account)
    # Room relation needed for WS fan-out.
    result = await db.execute(
        select(User)
        .options(selectinload(User.room))
        .where(User.account_id == account.id)
    )
    members = list(result.scalars().all())
    await db.commit()
    await broadcast_avatar_to_memberships(manager, members, account.avatar_url)
    return {"ok": True, "avatar_url": account.avatar_url}


@router.delete("/auth/profile/avatar")
async def remove_profile_avatar(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    account = await ensure_user_account(db, user)
    delete_avatar_file(account.avatar_url)
    account.avatar_url = None
    await sync_all_memberships(db, account)
    result = await db.execute(
        select(User)
        .options(selectinload(User.room))
        .where(User.account_id == account.id)
    )
    members = list(result.scalars().all())
    await db.commit()
    await broadcast_avatar_to_memberships(manager, members, None)
    return {"ok": True, "avatar_url": None}


@router.get("/room/settings", response_model=RoomSettingsResponse)
async def get_room_settings(user: Annotated[User, Depends(get_current_user)]):
    return RoomSettingsResponse(
        pin=user.room.pin,
        entry_password_enabled=bool(user.room.entry_password_hash),
        can_manage=_can_manage_room(user),
    )


@router.put("/room/settings", response_model=RoomSettingsResponse)
async def update_room_settings(
    payload: RoomSettingsUpdateRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    room = user.room
    _ensure_room_owner(room, user)

    if room.entry_password_hash:
        if not payload.current_room_password or not verify_password(
            payload.current_room_password, room.entry_password_hash
        ):
            raise HTTPException(status_code=401, detail="Неверный текущий пароль группы")

    if payload.new_pin is not None:
        new_pin = payload.new_pin.strip()
        if new_pin == room.pin:
            pass
        else:
            exists = await db.execute(
                select(Room).where(
                    Room.map_id == room.map_id,
                    Room.pin == new_pin,
                    Room.id != room.id,
                )
            )
            if exists.scalar_one_or_none():
                raise HTTPException(status_code=409, detail="Группа с таким PIN уже существует")
            room.pin = new_pin

    if payload.remove_entry_password:
        room.entry_password_hash = None
    elif payload.new_entry_password is not None:
        entry_password = payload.new_entry_password.strip()
        if not entry_password:
            room.entry_password_hash = None
        else:
            if len(entry_password) < 4:
                raise HTTPException(status_code=400, detail="Пароль группы — минимум 4 символа")
            room.entry_password_hash = hash_password(entry_password)

    await db.commit()
    await db.refresh(room)
    return RoomSettingsResponse(
        pin=room.pin,
        entry_password_enabled=bool(room.entry_password_hash),
        can_manage=True,
    )


@router.get("/room/state", response_model=RoomStateResponse)
async def room_state(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await _build_room_state(db, user)


@router.post("/client/position")
async def update_position(
    payload: CoordsPayload,
    user: Annotated[User, Depends(authenticate_client)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Position).where(Position.user_id == user.id))
    position = result.scalar_one_or_none()
    if position:
        position.x = payload.x
        position.y = payload.y
    else:
        position = Position(user_id=user.id, x=payload.x, y=payload.y)
        db.add(position)
    await db.commit()
    await db.refresh(position)

    ch = channel_key(user.room.map_id, user.room_id)
    event = {
        "type": "position",
        "data": position_event_data(user, position),
    }
    await manager.broadcast(ch, event)
    return {"ok": True}


@router.post("/server/positions", response_model=ServerPositionsResponse)
async def server_push_positions(
    payload: ServerPositionsRequest,
    api_key: Annotated[ServerApiKey, Depends(authenticate_server_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Game-server agent: push live player coords (RCON / logs). Auth: Bearer smk_…"""
    players = [p.model_dump() for p in payload.players]
    result = await ingest_players(db, api_key, players)
    return ServerPositionsResponse(**result)


@router.post("/server/events", response_model=ServerEventsResponse)
async def server_push_events(
    payload: ServerEventsRequest,
    api_key: Annotated[ServerApiKey, Depends(authenticate_server_api_key)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Game-server agent: push death and other map events. Auth: Bearer smk_…"""
    events = [e.model_dump() for e in payload.events]
    result = await ingest_events(db, api_key, events)
    return ServerEventsResponse(**result)


@router.post("/client/marker", response_model=MarkerResponse)
async def add_marker(
    payload: CoordsPayload,
    user: Annotated[User, Depends(authenticate_client)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    marker = Marker(
        user_id=user.id,
        x=payload.x,
        y=payload.y,
        type=payload.type or "marker",
        marker_category="group",
        geometry_kind="point",
    )
    db.add(marker)
    await db.commit()
    await db.refresh(marker)

    ch = channel_key(user.room.map_id, user.room_id)
    resp = _marker_response(marker, user.nickname, user.avatar_url)
    await manager.broadcast(ch, {"type": "marker_added", "data": resp.model_dump(mode="json")})
    return resp


@router.post("/markers", response_model=MarkerResponse)
async def create_marker(
    payload: MarkerCreateRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    kind = (payload.geometry_kind or "point").strip().lower()
    if kind not in {"point", "circle", "line"}:
        raise HTTPException(status_code=400, detail="Unsupported geometry_kind")

    points = _normalize_points(payload.points)
    x = payload.x
    y = payload.y
    if kind == "line":
        if not points or len(points) < 2:
            raise HTTPException(status_code=400, detail="Line requires at least 2 points")
        x = points[0][0]
        y = points[0][1]
    else:
        if x is None or y is None:
            raise HTTPException(status_code=400, detail="Point and circle require x/y coordinates")

    radius = payload.radius
    if kind == "circle":
        radius = float(radius or 300.0)
        if radius <= 0:
            raise HTTPException(status_code=400, detail="Circle radius must be greater than zero")
    else:
        radius = None

    category = _normalize_marker_category(payload.marker_category)
    if _is_map_scoped_category(category) and not _can_manage_stashes(user):
        raise HTTPException(
            status_code=403,
            detail="Only admins and moderators can create map-scoped markers",
        )

    marker = Marker(
        user_id=user.id,
        x=float(x),
        y=float(y),
        type=(payload.type or "marker").strip() or "marker",
        marker_category=category,
        map_id=user.room.map_id if _is_map_scoped_category(category) else None,
        title=payload.title,
        description=payload.description,
        image_url=payload.image_url,
        geometry_kind=kind,
        points_json=json.dumps(points, ensure_ascii=False) if points else None,
        radius=radius,
        stroke_color=payload.stroke_color,
        fill_color=payload.fill_color,
    )
    db.add(marker)
    await db.commit()
    await db.refresh(marker)

    resp = _marker_response(marker, _marker_nickname(marker), user.avatar_url)
    await _broadcast_marker_event(
        db,
        user,
        marker,
        {"type": "marker_added", "data": resp.model_dump(mode="json")},
    )
    return resp


ALLOWED_COMMANDS = {"zoom_in", "zoom_out", "zoom_reset", "focus_me"}


@router.post("/client/command")
async def send_map_command(
    payload: dict,
    user: Annotated[User, Depends(authenticate_client)],
):
    """Send a UI command to the requesting user's own browser."""
    action = str(payload.get("action", "")).strip().lower()
    if action not in ALLOWED_COMMANDS:
        raise HTTPException(status_code=400, detail=f"Unknown action '{action}'")

    await manager.send_to_user(user.id, {"type": "map_command", "data": {"action": action}})
    return {"ok": True}


@router.put("/auth/profile/steam-id")
async def update_profile_steam_id(
    payload: ProfileSteamIdRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    raw = (payload.steam_id or "").strip()
    account = await ensure_user_account(db, user)
    if not raw:
        account.steam_id = None
    elif not raw.isdigit() or not (15 <= len(raw) <= 20):
        raise HTTPException(status_code=400, detail="Укажите SteamID64 (15–20 цифр)")
    else:
        account.steam_id = raw
    await sync_all_memberships(db, account)
    await adopt_matching_memberships(db, account)
    await db.commit()
    return {"ok": True, "steam_id": account.steam_id}


@router.delete("/auth/profile/steam-id")
async def clear_profile_steam_id(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    account = await ensure_user_account(db, user)
    account.steam_id = None
    await sync_all_memberships(db, account)
    await db.commit()
    return {"ok": True, "steam_id": None}


@router.post("/client/steam-id")
async def client_set_steam_id(
    payload: ClientSteamIdRequest,
    user: Annotated[User, Depends(authenticate_client)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Bind SteamID64 to the map user (from ScumMapClient auto-detect)."""
    raw = payload.steam_id.strip()
    if not raw.isdigit() or not (15 <= len(raw) <= 20):
        raise HTTPException(status_code=400, detail="steam_id must be SteamID64 digits")
    account = await ensure_user_account(db, user)
    account.steam_id = raw
    await sync_all_memberships(db, account)
    await adopt_matching_memberships(db, account)
    await db.commit()
    return {"ok": True, "steam_id": raw}


@router.patch("/markers/{marker_id}", response_model=MarkerResponse)
async def update_marker(
    marker_id: int,
    payload: MarkerUpdateRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Marker).options(selectinload(Marker.user)).where(Marker.id == marker_id)
    )
    marker = result.scalar_one_or_none()
    if not marker:
        raise HTTPException(status_code=404, detail="Marker not found")

    is_stash = _is_stash_marker(marker)
    if is_stash:
        if not _can_manage_stashes(user):
            raise HTTPException(status_code=403, detail="Only admins and moderators can edit map-scoped markers")
        if marker.map_id != user.room.map_id:
            raise HTTPException(status_code=403, detail="Marker not on this map")
    elif not _marker_edit_allowed(user, marker):
        raise HTTPException(status_code=403, detail="Marker not in your group")

    if payload.type is not None:
        marker.type = payload.type
    if payload.marker_category is not None:
        new_category = _normalize_marker_category(payload.marker_category)
        if _is_map_scoped_category(new_category) and not _can_manage_stashes(user):
            raise HTTPException(
                status_code=403,
                detail="Only admins and moderators can create map-scoped markers",
            )
        marker.marker_category = new_category
        if _is_map_scoped_category(new_category):
            marker.map_id = user.room.map_id
        elif marker.map_id is not None:
            marker.map_id = None
    if payload.x is not None:
        marker.x = payload.x
    if payload.y is not None:
        marker.y = payload.y
    if payload.title is not None:
        marker.title = payload.title
    if payload.description is not None:
        marker.description = payload.description
    if payload.image_url is not None:
        marker.image_url = payload.image_url
    if payload.geometry_kind is not None:
        kind = payload.geometry_kind.strip().lower()
        if kind not in {"point", "circle", "line"}:
            raise HTTPException(status_code=400, detail="Unsupported geometry_kind")
        marker.geometry_kind = kind
        if kind != "line":
            marker.points_json = None
        if kind != "circle":
            marker.radius = None
    if payload.points is not None:
        points = _normalize_points(payload.points)
        if marker.geometry_kind == "line":
            if not points or len(points) < 2:
                raise HTTPException(status_code=400, detail="Line requires at least 2 points")
            marker.points_json = json.dumps(points, ensure_ascii=False)
            marker.x = points[0][0]
            marker.y = points[0][1]
        else:
            marker.points_json = None
    if payload.radius is not None:
        if marker.geometry_kind != "circle":
            marker.radius = None
        else:
            if payload.radius <= 0:
                raise HTTPException(status_code=400, detail="Circle radius must be greater than zero")
            marker.radius = payload.radius
    if payload.stroke_color is not None:
        marker.stroke_color = payload.stroke_color
    if payload.fill_color is not None:
        marker.fill_color = payload.fill_color

    await db.commit()
    await db.refresh(marker)

    resp = _marker_response(marker, _marker_nickname(marker))
    await _broadcast_marker_event(
        db,
        user,
        marker,
        {"type": "marker_updated", "data": resp.model_dump(mode="json")},
    )
    return resp


@router.post("/markers/{marker_id}/image", response_model=MarkerResponse)
async def upload_marker_image(
    marker_id: int,
    file: Annotated[UploadFile, File()],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Marker).options(selectinload(Marker.user)).where(Marker.id == marker_id)
    )
    marker = result.scalar_one_or_none()
    if not marker:
        raise HTTPException(status_code=404, detail="Marker not found")

    is_stash = _is_stash_marker(marker)
    if is_stash:
        if not _can_manage_stashes(user):
            raise HTTPException(status_code=403, detail="Only admins and moderators can edit map-scoped markers")
        if marker.map_id != user.room.map_id:
            raise HTTPException(status_code=403, detail="Marker not on this map")
    elif not _marker_edit_allowed(user, marker):
        raise HTTPException(status_code=403, detail="Marker not in your group")

    old_url = marker.image_url
    image_url = await save_marker_image(marker_id, file)
    marker.image_url = image_url
    await db.commit()
    await db.refresh(marker)

    # delete old file after successful save
    if old_url:
        delete_marker_image_file(old_url)

    resp = _marker_response(marker, _marker_nickname(marker))
    await _broadcast_marker_event(
        db,
        user,
        marker,
        {"type": "marker_updated", "data": resp.model_dump(mode="json")},
    )
    return resp


@router.delete("/markers/{marker_id}")
async def delete_marker(
    marker_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Marker).options(selectinload(Marker.user)).where(Marker.id == marker_id)
    )
    marker = result.scalar_one_or_none()
    if not marker:
        raise HTTPException(status_code=404, detail="Marker not found")

    is_stash = _is_stash_marker(marker)
    if is_stash:
        if not _can_manage_stashes(user):
            raise HTTPException(status_code=403, detail="Only admins and moderators can delete map-scoped markers")
        if marker.map_id != user.room.map_id:
            raise HTTPException(status_code=403, detail="Marker not on this map")
    elif not _marker_delete_allowed(user, marker):
        raise HTTPException(status_code=403, detail="Can only delete own markers")

    old_url = marker.image_url
    map_id = user.room.map_id
    await db.delete(marker)
    await db.commit()
    if old_url:
        delete_marker_image_file(old_url)
    event = {"type": "marker_deleted", "data": {"id": marker_id}}
    if is_stash:
        await _broadcast_to_map(db, map_id, event)
    else:
        await manager.broadcast(channel_key(map_id, user.room_id), event)
    return {"ok": True}


async def _build_room_state(db: AsyncSession, user: User) -> RoomStateResponse:
    users_result = await db.execute(
        select(User)
        .options(
            selectinload(User.position),
            selectinload(User.markers),
            selectinload(User.account),
        )
        .where(User.room_id == user.room_id)
    )
    users = users_result.scalars().all()

    pois_result = await db.execute(select(MapPoi).where(MapPoi.map_id == user.room.map_id))
    pois = pois_result.scalars().all()

    trader_rows = (
        await db.execute(
            select(Trader).where(Trader.map_id == user.room.map_id, Trader.poi_id.is_not(None))
        )
    ).scalars().all()
    trader_name_by_poi = {t.poi_id: t.name for t in trader_rows}

    positions: list[PositionResponse] = []
    markers: list[MarkerResponse] = []

    for u in users:
        avatar = avatar_url_of(u)
        if u.position:
            positions.append(
                PositionResponse(
                    user_id=u.id,
                    nickname=u.nickname,
                    avatar_url=avatar,
                    x=u.position.x,
                    y=u.position.y,
                    z=u.position.z,
                    updated_at=u.position.updated_at,
                    travel_mode=u.position.travel_mode,
                    vehicle_role=u.position.vehicle_role,
                    vehicle_type=u.position.vehicle_type,
                )
            )
        for m in u.markers:
            if _is_map_scoped_category(m.marker_category):
                continue
            markers.append(_marker_response(m, u.nickname, avatar))

    scoped_result = await db.execute(
        select(Marker)
        .options(selectinload(Marker.user))
        .where(
            Marker.map_id == user.room.map_id,
            Marker.marker_category.in_(tuple(MAP_SCOPED_MARKER_CATEGORIES)),
        )
    )
    for m in scoped_result.scalars().all():
        markers.append(_marker_response(m, _marker_nickname(m)))

    # Legacy stashes not yet linked to map_id (pre-migration).
    linked_stash_ids = {m.id for m in markers if _marker_category_value(m) == "stash"}
    for u in users:
        for m in u.markers:
            if _marker_category_value(m) != "stash" or m.id in linked_stash_ids:
                continue
            markers.append(_marker_response(m, u.nickname))
            linked_stash_ids.add(m.id)

    game_map = user.room.map

    # Recent deaths (24h), newest first — keep map readable.
    # Include map-wide deaths (room_id null) and this room's deaths.
    death_since = datetime.now(timezone.utc) - timedelta(hours=24)
    deaths_q = (
        select(MapDeath)
        .where(
            MapDeath.map_id == user.room.map_id,
            MapDeath.died_at >= death_since,
            or_(MapDeath.room_id.is_(None), MapDeath.room_id == user.room_id),
        )
        .order_by(MapDeath.died_at.desc())
        .limit(200)
    )
    death_rows = (await db.execute(deaths_q)).scalars().all()
    deaths = [
        DeathEventResponse(
            id=d.id,
            nickname=d.nickname,
            steam_id=d.steam_id,
            profile_id=d.profile_id,
            x=d.x,
            y=d.y,
            z=d.z,
            died_at=d.died_at,
        )
        for d in death_rows
    ]

    return RoomStateResponse(
        map_slug=game_map.slug,
        map_name=game_map.name,
        positions=positions,
        markers=markers,
        pois=[
            PoiResponse(
                id=p.id,
                title=p.title,
                description=p.description,
                description_image_url=p.description_image_url,
                icon=p.icon or "star",
                x=p.x,
                y=p.y,
                trader_name=trader_name_by_poi.get(p.id),
            )
            for p in pois
        ],
        deaths=deaths,
    )


@router.delete("/deaths/{death_id}")
async def delete_death(
    death_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Remove a death marker from the map (any room member on that map)."""
    result = await db.execute(select(MapDeath).where(MapDeath.id == death_id))
    death = result.scalar_one_or_none()
    if not death:
        raise HTTPException(status_code=404, detail="Death not found")
    if death.map_id != user.room.map_id:
        raise HTTPException(status_code=403, detail="Death is on another map")
    if death.room_id is not None and death.room_id != user.room_id:
        raise HTTPException(status_code=403, detail="Death is in another room")

    await db.delete(death)
    await db.commit()

    event = {"type": "death_deleted", "data": {"id": death_id}}
    if death.room_id is not None:
        await manager.broadcast(channel_key(death.map_id, death.room_id), event)
    else:
        await _broadcast_to_map(db, death.map_id, event)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Server POIs — staff management on web map
# ---------------------------------------------------------------------------


@router.post("/pois", response_model=PoiResponse)
async def create_poi(
    payload: StaffPoiCreateRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not _can_manage_map_staff(user):
        raise HTTPException(status_code=403, detail="Only admins and moderators can manage server markers")
    poi = MapPoi(
        map_id=user.room.map_id,
        title=payload.title.strip()[:128],
        description=(payload.description or "").strip(),
        icon=normalize_poi_icon(payload.icon),
        x=float(payload.x),
        y=float(payload.y),
    )
    db.add(poi)
    await db.commit()
    await db.refresh(poi)
    await _broadcast_pois_changed(db, user.room.map_id)
    return await _poi_response(db, poi)


@router.put("/pois/{poi_id}", response_model=PoiResponse)
async def update_poi(
    poi_id: int,
    payload: StaffPoiUpdateRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not _can_manage_map_staff(user):
        raise HTTPException(status_code=403, detail="Only admins and moderators can manage server markers")
    poi = await _get_map_poi(db, user.room.map_id, poi_id)
    if payload.title is not None:
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="Title is required")
        poi.title = title[:128]
    if payload.description is not None:
        poi.description = payload.description.strip()
    if payload.icon is not None:
        poi.icon = normalize_poi_icon(payload.icon)
    if payload.x is not None:
        poi.x = float(payload.x)
    if payload.y is not None:
        poi.y = float(payload.y)
    await db.commit()
    await db.refresh(poi)
    await _broadcast_pois_changed(db, user.room.map_id)
    return await _poi_response(db, poi)


@router.delete("/pois/{poi_id}")
async def delete_poi(
    poi_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not _can_manage_map_staff(user):
        raise HTTPException(status_code=403, detail="Only admins and moderators can manage server markers")
    poi = await _get_map_poi(db, user.room.map_id, poi_id)
    delete_poi_image_file(poi.description_image_url)
    await db.execute(update(Trader).where(Trader.poi_id == poi_id).values(poi_id=None))
    await db.delete(poi)
    await db.commit()
    await _broadcast_pois_changed(db, user.room.map_id)
    return {"ok": True}


@router.post("/pois/{poi_id}/image", response_model=PoiResponse)
async def upload_poi_image(
    poi_id: int,
    file: Annotated[UploadFile, File()],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not _can_manage_map_staff(user):
        raise HTTPException(status_code=403, detail="Only admins and moderators can manage server markers")
    poi = await _get_map_poi(db, user.room.map_id, poi_id)
    delete_poi_image_file(poi.description_image_url)
    poi.description_image_url = await save_poi_image(poi_id, file)
    await db.commit()
    await db.refresh(poi)
    await _broadcast_pois_changed(db, user.room.map_id)
    return await _poi_response(db, poi)


@router.post("/markers/{marker_id}/promote-to-poi", response_model=PoiResponse)
async def promote_marker_to_poi(
    marker_id: int,
    payload: PromoteMarkerToPoiRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not _can_manage_map_staff(user):
        raise HTTPException(status_code=403, detail="Only admins and moderators can manage server markers")
    result = await db.execute(
        select(Marker).options(selectinload(Marker.user)).where(Marker.id == marker_id)
    )
    marker = result.scalar_one_or_none()
    if not marker:
        raise HTTPException(status_code=404, detail="Marker not found")
    if not _marker_edit_allowed(user, marker):
        raise HTTPException(status_code=403, detail="Marker not accessible")
    if (marker.geometry_kind or "point") != "point":
        raise HTTPException(status_code=400, detail="Only point markers can become server markers")

    title = (payload.title or marker.title or "Метка").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    description = payload.description if payload.description is not None else (marker.description or "")
    description = description.strip()
    if description.lower() == title.lower():
        description = ""

    poi = MapPoi(
        map_id=user.room.map_id,
        title=title[:128],
        description=description,
        icon=normalize_poi_icon(payload.icon),
        x=float(marker.x),
        y=float(marker.y),
        description_image_url=marker.image_url,
    )
    db.add(poi)
    marker_id_value = marker.id
    map_id = user.room.map_id
    await db.delete(marker)
    await db.commit()
    await db.refresh(poi)

    await _broadcast_to_map(
        db,
        map_id,
        {"type": "marker_deleted", "data": {"id": marker_id_value}},
    )
    await _broadcast_pois_changed(db, map_id)
    return await _poi_response(db, poi)


# ---------------------------------------------------------------------------
# Roads — public endpoints (read-only + navigate)
# ---------------------------------------------------------------------------

@router.get("/maps/{slug}/roads", response_model=list[RoadSegmentResponse])
async def get_map_roads(slug: str, db: Annotated[AsyncSession, Depends(get_db)]):
    """Return all road segments for the given map."""
    game_map = await get_map_by_slug(db, slug)
    return await list_segments(db, game_map.id)


@router.get("/maps/{slug}/buildings", response_model=list[MapBuildingResponse])
async def get_map_buildings(slug: str, db: Annotated[AsyncSession, Depends(get_db)]):
    """Return custom server building footprints for the given map."""
    game_map = await get_map_by_slug(db, slug)
    return await list_buildings(db, game_map.id, enabled_only=True)


@router.post("/maps/{slug}/navigate", response_model=NavigateResponse)
async def navigate(
    slug: str,
    payload: NavigateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Find a route between two map coordinates using A* on the road graph."""
    game_map = await get_map_by_slug(db, slug)
    result = await find_route(
        db, game_map,
        payload.from_x, payload.from_y,
        payload.to_x, payload.to_y,
    )
    return NavigateResponse(**result)
