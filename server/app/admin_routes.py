from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    clear_admin_session,
    require_admin,
    set_admin_session,
)
from app.database import get_db
from app.models import DayZMap, MapPoi, Room, Setting, User
from app.poi_icons import POI_ICONS, normalize_poi_icon
from app.schemas import (
    AdminLoginRequest,
    AdminPasswordRequest,
    AdminPinCreateRequest,
    AdminPinPolicyRequest,
    MapCreateRequest,
    MapUpdateRequest,
    PoiCreateRequest,
    PoiUpdateRequest,
)
from app.seed import ADMIN_PASSWORD_KEY, hash_admin_password, verify_admin_password
from app.settings_service import is_public_pin_creation, set_public_pin_creation

router = APIRouter(prefix="/api/admin")


async def _get_map(db: AsyncSession, slug: str) -> DayZMap:
    result = await db.execute(select(DayZMap).where(DayZMap.slug == slug.strip().lower()))
    game_map = result.scalar_one_or_none()
    if not game_map:
        raise HTTPException(status_code=404, detail="Map not found")
    return game_map


@router.post("/login")
async def admin_login(
    payload: AdminLoginRequest,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    setting = await db.get(Setting, ADMIN_PASSWORD_KEY)
    if not setting or not verify_admin_password(payload.password, setting.value):
        raise HTTPException(status_code=401, detail="Invalid password")
    set_admin_session(response)
    return {"ok": True}


@router.post("/logout")
async def admin_logout(response: Response):
    clear_admin_session(response)
    return {"ok": True}


@router.get("/me")
async def admin_me(_: Annotated[None, Depends(require_admin)]):
    return {"ok": True}


@router.get("/settings")
async def admin_get_settings(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    return {"public_pin_creation": await is_public_pin_creation(db)}


@router.put("/settings/pin-policy")
async def admin_set_pin_policy(
    payload: AdminPinPolicyRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    await set_public_pin_creation(db, payload.public_pin_creation)
    return {"public_pin_creation": payload.public_pin_creation}


@router.get("/rooms")
async def admin_list_rooms(
    map_slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    game_map = await _get_map(db, map_slug)
    result = await db.execute(
        select(Room, func.count(User.id))
        .outerjoin(User, User.room_id == Room.id)
        .where(Room.map_id == game_map.id)
        .group_by(Room.id)
        .order_by(Room.pin)
    )
    return [
        {
            "id": room.id,
            "pin": room.pin,
            "map_slug": game_map.slug,
            "user_count": count,
            "created_at": room.created_at.isoformat(),
        }
        for room, count in result.all()
    ]


@router.post("/rooms")
async def admin_create_room(
    payload: AdminPinCreateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    game_map = await _get_map(db, payload.map_slug)
    pin = payload.pin.strip()
    exists = await db.execute(select(Room).where(Room.map_id == game_map.id, Room.pin == pin))
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="PIN already exists for this map")
    room = Room(map_id=game_map.id, pin=pin)
    db.add(room)
    await db.commit()
    await db.refresh(room)
    return {"id": room.id, "pin": room.pin}


@router.delete("/rooms/{room_id}")
async def admin_delete_room(
    room_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    room = await db.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    await db.delete(room)
    await db.commit()
    return {"ok": True}


@router.post("/change-password")
async def change_password(
    payload: AdminPasswordRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    setting = await db.get(Setting, ADMIN_PASSWORD_KEY)
    if not setting or not verify_admin_password(payload.current_password, setting.value):
        raise HTTPException(status_code=401, detail="Wrong current password")
    setting.value = hash_admin_password(payload.new_password)
    await db.commit()
    return {"ok": True}


@router.get("/maps")
async def admin_list_maps(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    result = await db.execute(select(DayZMap).order_by(DayZMap.sort_order, DayZMap.name))
    maps = result.scalars().all()
    return [
        {
            "id": m.id,
            "slug": m.slug,
            "name": m.name,
            "map_size": m.map_size,
            "tiles_satellite": m.tiles_satellite,
            "tiles_topographic": m.tiles_topographic,
            "max_native_zoom": m.max_native_zoom,
            "extra_zoom": m.extra_zoom,
            "locations_url": m.locations_url or "",
            "locations_source": m.locations_source or "izurvive",
            "radiation_url": m.radiation_url or "",
            "enabled": m.enabled,
            "sort_order": m.sort_order,
        }
        for m in maps
    ]


@router.post("/maps")
async def admin_create_map(
    payload: MapCreateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    exists = await db.execute(select(DayZMap).where(DayZMap.slug == payload.slug.strip()))
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Slug already exists")
    game_map = DayZMap(
        slug=payload.slug.strip().lower(),
        name=payload.name.strip(),
        map_size=payload.map_size,
        tiles_satellite=payload.tiles_satellite.strip(),
        tiles_topographic=payload.tiles_topographic.strip(),
        max_native_zoom=payload.max_native_zoom,
        extra_zoom=payload.extra_zoom,
        locations_url=payload.locations_url.strip() or None,
        locations_source=(payload.locations_source or "izurvive").strip().lower(),
        radiation_url=payload.radiation_url.strip() or None,
        enabled=payload.enabled,
        sort_order=payload.sort_order,
    )
    db.add(game_map)
    await db.commit()
    await db.refresh(game_map)
    return {"id": game_map.id, "slug": game_map.slug}


@router.put("/maps/{map_id}")
async def admin_update_map(
    map_id: int,
    payload: MapUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    game_map = await db.get(DayZMap, map_id)
    if not game_map:
        raise HTTPException(status_code=404, detail="Map not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(game_map, field, value)
    await db.commit()
    return {"ok": True}


@router.delete("/maps/{map_id}")
async def admin_delete_map(
    map_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    game_map = await db.get(DayZMap, map_id)
    if not game_map:
        raise HTTPException(status_code=404, detail="Map not found")
    await db.delete(game_map)
    await db.commit()
    return {"ok": True}


@router.get("/poi-icons")
async def admin_poi_icons(_: Annotated[None, Depends(require_admin)]):
    return POI_ICONS


@router.get("/pois")
async def admin_list_pois(
    map_slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    game_map = await _get_map(db, map_slug)
    result = await db.execute(select(MapPoi).where(MapPoi.map_id == game_map.id).order_by(MapPoi.id))
    pois = result.scalars().all()
    return [
        {
            "id": p.id,
            "map_slug": game_map.slug,
            "title": p.title,
            "description": p.description,
            "icon": p.icon or "star",
            "x": p.x,
            "y": p.y,
        }
        for p in pois
    ]


@router.post("/pois")
async def admin_create_poi(
    payload: PoiCreateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    game_map = await _get_map(db, payload.map_slug)
    poi = MapPoi(
        map_id=game_map.id,
        title=payload.title.strip(),
        description=payload.description.strip(),
        icon=normalize_poi_icon(payload.icon),
        x=payload.x,
        y=payload.y,
    )
    db.add(poi)
    await db.commit()
    await db.refresh(poi)
    return {"id": poi.id}


@router.put("/pois/{poi_id}")
async def admin_update_poi(
    poi_id: int,
    payload: PoiUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    poi = await db.get(MapPoi, poi_id)
    if not poi:
        raise HTTPException(status_code=404, detail="POI not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field == "icon":
            value = normalize_poi_icon(value)
        setattr(poi, field, value)
    await db.commit()
    return {"ok": True}


@router.delete("/pois/{poi_id}")
async def admin_delete_poi(
    poi_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    poi = await db.get(MapPoi, poi_id)
    if not poi:
        raise HTTPException(status_code=404, detail="POI not found")
    await db.delete(poi)
    await db.commit()
    return {"ok": True}
