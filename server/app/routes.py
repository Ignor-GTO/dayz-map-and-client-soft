import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import (
    authenticate_client,
    channel_key,
    clear_session,
    generate_client_key,
    get_current_user,
    get_map_by_slug,
    get_or_create_room,
    hash_client_key,
    set_session,
)
from app.database import get_db
from app.locations_service import get_map_locations
from app.radiation_service import get_map_radiation
from app.maps_service import list_enabled_maps, resolve_map_config
from app.marker_upload import delete_marker_image_file, save_marker_image
from app.models import MapPoi, Marker, Position, Room, User
from app.roads_service import create_segment, delete_segment, find_route, list_segments
from app.schemas import (
    CoordsPayload,
    LoginRequest,
    LoginResponse,
    MapConfigResponse,
    MapListItem,
    MapLocationsResponse,
    MapRadiationResponse,
    MarkerCreateRequest,
    MarkerResponse,
    MarkerUpdateRequest,
    NavigateRequest,
    NavigateResponse,
    PoiResponse,
    PositionResponse,
    RoadSegmentResponse,
    RoomStateResponse,
)
from app.seed import DEFAULT_MAP_SLUG
from app.settings_service import is_public_pin_creation
from app.websocket import manager

router = APIRouter(prefix="/api")


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
    if category not in {"group", "stash"}:
        raise HTTPException(status_code=400, detail="Unsupported marker_category")
    return category


def _marker_response(marker: Marker, nickname: str) -> MarkerResponse:
    points = _load_marker_points(marker)
    return MarkerResponse(
        id=marker.id,
        user_id=marker.user_id,
        nickname=nickname,
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
    if room is None:
        if not await is_public_pin_creation(db):
            raise HTTPException(
                status_code=403,
                detail="Группа с таким PIN не найдена. Создание новых PIN отключено — обратитесь к администратору.",
            )
        room = await get_or_create_room(db, game_map.id, pin)

    result = await db.execute(
        select(User).where(User.room_id == room.id, User.nickname == nickname)
    )
    user = result.scalar_one_or_none()

    if user:
        client_key = None
        message = "С возвращением! Используйте сохранённый ключ клиента."
    else:
        client_key = generate_client_key()
        user = User(
            room_id=room.id,
            nickname=nickname,
            client_key_hash=hash_client_key(client_key),
        )
        db.add(user)
        message = "Аккаунт создан. Сохраните ключ клиента — он показывается один раз."

    await db.commit()
    await db.refresh(user)
    set_session(response, user.id)

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
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    client_key = generate_client_key()
    user.client_key_hash = hash_client_key(client_key)
    await db.commit()
    await db.refresh(user)
    game_map = user.room.map
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


@router.get("/auth/me")
async def me(user: Annotated[User, Depends(get_current_user)]):
    return {
        "nickname": user.nickname,
        "pin": user.room.pin,
        "map_slug": user.room.map.slug,
        "map_name": user.room.map.name,
        "user_id": user.id,
    }


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
        "data": {
            "user_id": user.id,
            "nickname": user.nickname,
            "x": position.x,
            "y": position.y,
            "updated_at": position.updated_at.isoformat(),
        },
    }
    await manager.broadcast(ch, event)
    return {"ok": True}


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
    resp = _marker_response(marker, user.nickname)
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

    marker = Marker(
        user_id=user.id,
        x=float(x),
        y=float(y),
        type=(payload.type or "marker").strip() or "marker",
        marker_category=_normalize_marker_category(payload.marker_category),
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

    ch = channel_key(user.room.map_id, user.room_id)
    resp = _marker_response(marker, user.nickname)
    await manager.broadcast(ch, {"type": "marker_added", "data": resp.model_dump(mode="json")})
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
    if marker.user.room_id != user.room_id:
        raise HTTPException(status_code=403, detail="Marker not in your group")

    if payload.type is not None:
        marker.type = payload.type
    if payload.marker_category is not None:
        marker.marker_category = _normalize_marker_category(payload.marker_category)
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

    resp = _marker_response(marker, marker.user.nickname)
    ch = channel_key(user.room.map_id, user.room_id)
    await manager.broadcast(ch, {"type": "marker_updated", "data": resp.model_dump(mode="json")})
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
    if marker.user.room_id != user.room_id:
        raise HTTPException(status_code=403, detail="Marker not in your group")

    old_url = marker.image_url
    image_url = await save_marker_image(marker_id, file)
    marker.image_url = image_url
    await db.commit()
    await db.refresh(marker)

    # delete old file after successful save
    if old_url:
        delete_marker_image_file(old_url)

    resp = _marker_response(marker, marker.user.nickname)
    ch = channel_key(user.room.map_id, user.room_id)
    await manager.broadcast(ch, {"type": "marker_updated", "data": resp.model_dump(mode="json")})
    return resp


@router.delete("/markers/{marker_id}")
async def delete_marker(
    marker_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Marker).where(Marker.id == marker_id))
    marker = result.scalar_one_or_none()
    if not marker:
        raise HTTPException(status_code=404, detail="Marker not found")
    if marker.user_id != user.id:
        raise HTTPException(status_code=403, detail="Can only delete own markers")

    old_url = marker.image_url
    ch = channel_key(user.room.map_id, user.room_id)
    await db.delete(marker)
    await db.commit()
    if old_url:
        delete_marker_image_file(old_url)
    await manager.broadcast(ch, {"type": "marker_deleted", "data": {"id": marker_id}})
    return {"ok": True}


async def _build_room_state(db: AsyncSession, user: User) -> RoomStateResponse:
    users_result = await db.execute(
        select(User)
        .options(
            selectinload(User.position),
            selectinload(User.markers),
        )
        .where(User.room_id == user.room_id)
    )
    users = users_result.scalars().all()

    pois_result = await db.execute(select(MapPoi).where(MapPoi.map_id == user.room.map_id))
    pois = pois_result.scalars().all()

    positions: list[PositionResponse] = []
    markers: list[MarkerResponse] = []

    for u in users:
        if u.position:
            positions.append(
                PositionResponse(
                    user_id=u.id,
                    nickname=u.nickname,
                    x=u.position.x,
                    y=u.position.y,
                    updated_at=u.position.updated_at,
                )
            )
        for m in u.markers:
            markers.append(_marker_response(m, u.nickname))

    game_map = user.room.map
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
            )
            for p in pois
        ],
    )


# ---------------------------------------------------------------------------
# Roads — public endpoints (read-only + navigate)
# ---------------------------------------------------------------------------

@router.get("/maps/{slug}/roads", response_model=list[RoadSegmentResponse])
async def get_map_roads(slug: str, db: Annotated[AsyncSession, Depends(get_db)]):
    """Return all road segments for the given map."""
    game_map = await get_map_by_slug(db, slug)
    return await list_segments(db, game_map.id)


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
