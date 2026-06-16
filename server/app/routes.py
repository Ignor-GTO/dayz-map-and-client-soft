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
from app.config import CLIENT_DOWNLOAD_URL, MAP_ATTRIBUTION, SERVER_PUBLIC_URL
from app.database import get_db
from app.models import DayZMap, MapPoi, Marker, Position, User
from app.schemas import (
    CoordsPayload,
    LoginRequest,
    LoginResponse,
    MapConfigResponse,
    MapListItem,
    MarkerResponse,
    PoiResponse,
    PositionResponse,
    RoomStateResponse,
)
from app.websocket import manager

router = APIRouter(prefix="/api")


def map_to_config(game_map: DayZMap) -> MapConfigResponse:
    size = game_map.map_size
    return MapConfigResponse(
        slug=game_map.slug,
        name=game_map.name,
        bounds={
            "min_x": 0,
            "max_x": size,
            "min_y": 0,
            "max_y": size,
        },
        map_size=size,
        max_native_zoom=game_map.max_native_zoom,
        extra_zoom=game_map.extra_zoom,
        tiles_satellite=game_map.tiles_satellite,
        tiles_topographic=game_map.tiles_topographic,
        attribution=MAP_ATTRIBUTION,
        server_url=SERVER_PUBLIC_URL,
        client_download_url=CLIENT_DOWNLOAD_URL,
    )


@router.get("/maps", response_model=list[MapListItem])
async def list_maps(db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(
        select(DayZMap).where(DayZMap.enabled.is_(True)).order_by(DayZMap.sort_order, DayZMap.name)
    )
    return [MapListItem(slug=m.slug, name=m.name) for m in result.scalars().all()]


@router.get("/maps/{slug}/config", response_model=MapConfigResponse)
async def map_config(slug: str, db: Annotated[AsyncSession, Depends(get_db)]):
    game_map = await get_map_by_slug(db, slug)
    return map_to_config(game_map)


@router.post("/auth/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    pin = payload.pin.strip()
    nickname = payload.nickname.strip()
    game_map = await get_map_by_slug(db, payload.map_slug.strip().lower())
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
    marker = Marker(user_id=user.id, x=payload.x, y=payload.y)
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
            PoiResponse(id=p.id, title=p.title, description=p.description, x=p.x, y=p.y)
            for p in pois
        ],
    )
