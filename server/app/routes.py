from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
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
    MarkerResponse,
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
    marker = Marker(user_id=user.id, x=payload.x, y=payload.y, type=payload.type or "marker")
    db.add(marker)
    await db.commit()
    await db.refresh(marker)

    ch = channel_key(user.room.map_id, user.room_id)
    event = {
        "type": "marker_added",
        "data": {
            "id": marker.id,
            "user_id": user.id,
            "nickname": user.nickname,
            "x": marker.x,
            "y": marker.y,
            "type": marker.type,
            "created_at": marker.created_at.isoformat(),
        },
    }
    await manager.broadcast(ch, event)

    return MarkerResponse(
        id=marker.id,
        user_id=user.id,
        nickname=user.nickname,
        x=marker.x,
        y=marker.y,
        type=marker.type,
        created_at=marker.created_at,
    )


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

    ch = channel_key(user.room.map_id, user.room_id)
    await db.delete(marker)
    await db.commit()
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
            markers.append(
                MarkerResponse(
                    id=m.id,
                    user_id=u.id,
                    nickname=u.nickname,
                    x=m.x,
                    y=m.y,
                    type=m.type,
                    created_at=m.created_at,
                )
            )

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
