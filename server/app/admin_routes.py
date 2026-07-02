from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    clear_admin_session,
    require_admin,
    set_admin_session,
)
from app.database import get_db
from app.models import (
    DayZMap,
    MapPoi,
    Room,
    Setting,
    Trader,
    TraderItem,
    TraderSection,
    TraderSubsection,
    User,
)
from app.poi_icons import POI_ICONS, normalize_poi_icon
from app.poi_upload import delete_poi_image_file, save_poi_image
from app.radiation_service import (
    get_map_radiation,
    load_raw_radiation_config_async,
    save_radiation_config,
)
from app.radiation_upload import delete_overlay_file, save_radiation_overlay
from app.roads_service import create_segment, delete_segment, list_segments, update_segment, clear_segments, create_segments_bulk
from app.schemas import (
    AdminLoginRequest,
    AdminPasswordRequest,
    AdminPinCreateRequest,
    AdminPinPolicyRequest,
    MapCreateRequest,
    MapUpdateRequest,
    PoiCreateRequest,
    PoiUpdateRequest,
    RadiationSaveRequest,
    RoadSegmentCreate,
    RoadSegmentResponse,
    RoadSegmentUpdate,
    TraderCreateRequest,
    TraderItemCreateRequest,
    TraderItemImportRequest,
    TraderItemResponse,
    TraderItemUpdateRequest,
    TraderResponse,
    TraderSectionCreateRequest,
    TraderSectionResponse,
    TraderSubsectionCreateRequest,
    TraderSubsectionResponse,
    TraderUpdateRequest,
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


def _clean_name(value: str, *, field: str = "name", max_len: int = 160) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"{field} is required")
    if len(cleaned) > max_len:
        raise HTTPException(status_code=400, detail=f"{field} is too long")
    return cleaned


def _same_name(a: str | None, b: str | None) -> bool:
    return str(a or "").strip().casefold() == str(b or "").strip().casefold()


async def _find_trader(db: AsyncSession, map_id: int, name: str) -> Trader | None:
    rows = (await db.execute(select(Trader).where(Trader.map_id == map_id))).scalars().all()
    for row in rows:
        if _same_name(row.name, name):
            return row
    return None


async def _find_section(db: AsyncSession, trader_id: int, name: str) -> TraderSection | None:
    rows = (await db.execute(select(TraderSection).where(TraderSection.trader_id == trader_id))).scalars().all()
    for row in rows:
        if _same_name(row.name, name):
            return row
    return None


async def _find_subsection(db: AsyncSession, section_id: int, name: str) -> TraderSubsection | None:
    rows = (await db.execute(select(TraderSubsection).where(TraderSubsection.section_id == section_id))).scalars().all()
    for row in rows:
        if _same_name(row.name, name):
            return row
    return None


async def _find_item(db: AsyncSession, subsection_id: int, name: str) -> TraderItem | None:
    rows = (await db.execute(select(TraderItem).where(TraderItem.subsection_id == subsection_id))).scalars().all()
    for row in rows:
        if _same_name(row.name, name):
            return row
    return None


def _item_response(item: TraderItem, subsection: TraderSubsection, section: TraderSection, trader: Trader) -> TraderItemResponse:
    return TraderItemResponse(
        id=item.id,
        subsection_id=subsection.id,
        section_id=section.id,
        trader_id=trader.id,
        map_id=trader.map_id,
        trader=trader.name,
        trader_x=trader.x,
        trader_y=trader.y,
        section=section.name,
        subsection=subsection.name,
        name=item.name,
        buy_price=int(item.buy_price or 0),
        sell_price=int(item.sell_price or 0),
    )


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
            "description_image_url": p.description_image_url or "",
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
    delete_poi_image_file(poi.description_image_url)
    await db.delete(poi)
    await db.commit()
    return {"ok": True}


@router.post("/pois/{poi_id}/image")
async def admin_upload_poi_image(
    poi_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
    file: UploadFile = File(...),
):
    poi = await db.get(MapPoi, poi_id)
    if not poi:
        raise HTTPException(status_code=404, detail="POI not found")
    delete_poi_image_file(poi.description_image_url)
    url = await save_poi_image(poi_id, file)
    poi.description_image_url = url
    await db.commit()
    return {"description_image_url": url}


@router.delete("/pois/{poi_id}/image")
async def admin_delete_poi_image(
    poi_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    poi = await db.get(MapPoi, poi_id)
    if not poi:
        raise HTTPException(status_code=404, detail="POI not found")
    delete_poi_image_file(poi.description_image_url)
    poi.description_image_url = None
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Traders
# ---------------------------------------------------------------------------


@router.get("/traders", response_model=list[TraderResponse])
async def admin_list_traders(
    map_slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    game_map = await _get_map(db, map_slug)
    traders = (
        await db.execute(
            select(Trader).where(Trader.map_id == game_map.id).order_by(Trader.name.asc())
        )
    ).scalars().all()
    return [TraderResponse(id=t.id, map_id=t.map_id, name=t.name, x=t.x, y=t.y) for t in traders]


@router.post("/traders", response_model=TraderResponse)
async def admin_create_trader(
    payload: TraderCreateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    game_map = await _get_map(db, payload.map_slug)
    name = _clean_name(payload.name, field="trader", max_len=128)
    existing = await _find_trader(db, game_map.id, name)
    if existing:
        if payload.x is not None:
            existing.x = float(payload.x)
        if payload.y is not None:
            existing.y = float(payload.y)
        await db.commit()
        await db.refresh(existing)
        return TraderResponse(id=existing.id, map_id=existing.map_id, name=existing.name, x=existing.x, y=existing.y)
    trader = Trader(
        map_id=game_map.id,
        name=name,
        x=float(payload.x) if payload.x is not None else None,
        y=float(payload.y) if payload.y is not None else None,
    )
    db.add(trader)
    await db.commit()
    await db.refresh(trader)
    return TraderResponse(id=trader.id, map_id=trader.map_id, name=trader.name, x=trader.x, y=trader.y)


@router.put("/traders/{trader_id}", response_model=TraderResponse)
async def admin_update_trader(
    trader_id: int,
    payload: TraderUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    trader = await db.get(Trader, trader_id)
    if not trader:
        raise HTTPException(status_code=404, detail="Trader not found")
    if payload.name is not None:
        trader.name = _clean_name(payload.name, field="trader", max_len=128)
    if payload.x is not None:
        trader.x = float(payload.x)
    if payload.y is not None:
        trader.y = float(payload.y)
    await db.commit()
    await db.refresh(trader)
    return TraderResponse(id=trader.id, map_id=trader.map_id, name=trader.name, x=trader.x, y=trader.y)


@router.delete("/traders/{trader_id}")
async def admin_delete_trader(
    trader_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    trader = await db.get(Trader, trader_id)
    if not trader:
        raise HTTPException(status_code=404, detail="Trader not found")
    await db.delete(trader)
    await db.commit()
    return {"ok": True}


@router.get("/trader-sections", response_model=list[TraderSectionResponse])
async def admin_list_trader_sections(
    trader_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    sections = (
        await db.execute(
            select(TraderSection).where(TraderSection.trader_id == trader_id).order_by(TraderSection.name.asc())
        )
    ).scalars().all()
    return [TraderSectionResponse(id=s.id, trader_id=s.trader_id, name=s.name) for s in sections]


@router.post("/trader-sections", response_model=TraderSectionResponse)
async def admin_create_trader_section(
    payload: TraderSectionCreateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    trader = await db.get(Trader, payload.trader_id)
    if not trader:
        raise HTTPException(status_code=404, detail="Trader not found")
    name = _clean_name(payload.name, field="section", max_len=128)
    existing = await _find_section(db, trader.id, name)
    if existing:
        return TraderSectionResponse(id=existing.id, trader_id=existing.trader_id, name=existing.name)
    section = TraderSection(trader_id=trader.id, name=name)
    db.add(section)
    await db.commit()
    await db.refresh(section)
    return TraderSectionResponse(id=section.id, trader_id=section.trader_id, name=section.name)


@router.delete("/trader-sections/{section_id}")
async def admin_delete_trader_section(
    section_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    section = await db.get(TraderSection, section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    await db.delete(section)
    await db.commit()
    return {"ok": True}


@router.get("/trader-subsections", response_model=list[TraderSubsectionResponse])
async def admin_list_trader_subsections(
    section_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    subsections = (
        await db.execute(
            select(TraderSubsection).where(TraderSubsection.section_id == section_id).order_by(TraderSubsection.name.asc())
        )
    ).scalars().all()
    return [TraderSubsectionResponse(id=s.id, section_id=s.section_id, name=s.name) for s in subsections]


@router.post("/trader-subsections", response_model=TraderSubsectionResponse)
async def admin_create_trader_subsection(
    payload: TraderSubsectionCreateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    section = await db.get(TraderSection, payload.section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    name = _clean_name(payload.name, field="subsection", max_len=128)
    existing = await _find_subsection(db, section.id, name)
    if existing:
        return TraderSubsectionResponse(
            id=existing.id,
            section_id=existing.section_id,
            name=existing.name,
        )
    subsection = TraderSubsection(section_id=section.id, name=name)
    db.add(subsection)
    await db.commit()
    await db.refresh(subsection)
    return TraderSubsectionResponse(id=subsection.id, section_id=subsection.section_id, name=subsection.name)


@router.delete("/trader-subsections/{subsection_id}")
async def admin_delete_trader_subsection(
    subsection_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    subsection = await db.get(TraderSubsection, subsection_id)
    if not subsection:
        raise HTTPException(status_code=404, detail="Subsection not found")
    await db.delete(subsection)
    await db.commit()
    return {"ok": True}


@router.get("/trader-items", response_model=list[TraderItemResponse])
async def admin_list_trader_items(
    map_slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
    q: str = "",
):
    game_map = await _get_map(db, map_slug)
    stmt = (
        select(TraderItem, TraderSubsection, TraderSection, Trader)
        .join(TraderSubsection, TraderSubsection.id == TraderItem.subsection_id)
        .join(TraderSection, TraderSection.id == TraderSubsection.section_id)
        .join(Trader, Trader.id == TraderSection.trader_id)
        .where(Trader.map_id == game_map.id)
    )
    needle = q.strip().casefold()
    stmt = stmt.order_by(TraderItem.name.asc())
    rows = (await db.execute(stmt)).all()
    out: list[TraderItemResponse] = []
    for item, subsection, section, trader in rows:
        if needle and needle not in str(item.name or "").casefold():
            continue
        out.append(_item_response(item, subsection, section, trader))
    return out


@router.post("/trader-items", response_model=TraderItemResponse)
async def admin_create_trader_item(
    payload: TraderItemCreateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    subsection = await db.get(TraderSubsection, payload.subsection_id)
    if not subsection:
        raise HTTPException(status_code=404, detail="Subsection not found")
    section = await db.get(TraderSection, subsection.section_id)
    trader = await db.get(Trader, section.trader_id) if section else None
    if not section or not trader:
        raise HTTPException(status_code=404, detail="Trader path not found")
    name = _clean_name(payload.name, field="item", max_len=160)
    existing = await _find_item(db, subsection.id, name)
    if existing:
        existing.buy_price = int(payload.buy_price)
        existing.sell_price = int(payload.sell_price)
        await db.commit()
        await db.refresh(existing)
        return _item_response(existing, subsection, section, trader)
    item = TraderItem(
        subsection_id=subsection.id,
        name=name,
        buy_price=int(payload.buy_price),
        sell_price=int(payload.sell_price),
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _item_response(item, subsection, section, trader)


@router.put("/trader-items/{item_id}", response_model=TraderItemResponse)
async def admin_update_trader_item(
    item_id: int,
    payload: TraderItemUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    item = await db.get(TraderItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if payload.subsection_id is not None:
        subsection = await db.get(TraderSubsection, payload.subsection_id)
        if not subsection:
            raise HTTPException(status_code=404, detail="Subsection not found")
        item.subsection_id = subsection.id
    subsection = await db.get(TraderSubsection, item.subsection_id)
    section = await db.get(TraderSection, subsection.section_id) if subsection else None
    trader = await db.get(Trader, section.trader_id) if section else None
    if not subsection or not section or not trader:
        raise HTTPException(status_code=404, detail="Trader path not found")

    if payload.name is not None:
        item.name = _clean_name(payload.name, field="item", max_len=160)
    if payload.buy_price is not None:
        item.buy_price = int(payload.buy_price)
    if payload.sell_price is not None:
        item.sell_price = int(payload.sell_price)
    await db.commit()
    await db.refresh(item)
    return _item_response(item, subsection, section, trader)


@router.delete("/trader-items/{item_id}")
async def admin_delete_trader_item(
    item_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    item = await db.get(TraderItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    await db.delete(item)
    await db.commit()
    return {"ok": True}


@router.post("/trader-items/import-json")
async def admin_import_trader_items_json(
    payload: TraderItemImportRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    game_map = await _get_map(db, payload.map_slug)
    if not payload.items:
        return {"ok": True, "created": 0, "updated": 0, "total": 0}

    # Deduplicate payload by full path+item name (case-insensitive).
    # Last duplicate entry wins.
    normalized_entries: dict[tuple[str, str, str, str], tuple[str, str, str, str, int, int]] = {}
    for entry in payload.items:
        trader_name = _clean_name(entry.trader, field="trader", max_len=128)
        section_name = _clean_name(entry.section, field="section", max_len=128)
        subsection_name = _clean_name(entry.subsection, field="subsection", max_len=128)
        item_name = _clean_name(entry.name, field="item", max_len=160)
        key = (
            trader_name.lower(),
            section_name.lower(),
            subsection_name.lower(),
            item_name.lower(),
        )
        normalized_entries[key] = (
            trader_name,
            section_name,
            subsection_name,
            item_name,
            int(entry.buy_price),
            int(entry.sell_price),
        )

    ordered_entries = list(normalized_entries.values())
    created = 0
    updated = 0
    try:
        for trader_name, section_name, subsection_name, item_name, buy_price, sell_price in ordered_entries:
            trader = await _find_trader(db, game_map.id, trader_name)
            if not trader:
                trader = Trader(map_id=game_map.id, name=trader_name)
                db.add(trader)
                await db.flush()

            section = await _find_section(db, trader.id, section_name)
            if not section:
                section = TraderSection(trader_id=trader.id, name=section_name)
                db.add(section)
                await db.flush()

            subsection = await _find_subsection(db, section.id, subsection_name)
            if not subsection:
                subsection = TraderSubsection(section_id=section.id, name=subsection_name)
                db.add(subsection)
                await db.flush()

            item = await _find_item(db, subsection.id, item_name)
            if item:
                item.buy_price = buy_price
                item.sell_price = sell_price
                updated += 1
            else:
                db.add(
                    TraderItem(
                        subsection_id=subsection.id,
                        name=item_name,
                        buy_price=buy_price,
                        sell_price=sell_price,
                    )
                )
                await db.flush()
                created += 1
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Конфликт данных при импорте (дубли trader/section/subsection/item). Проверьте JSON.",
        )

    return {"ok": True, "created": created, "updated": updated, "total": len(ordered_entries)}


@router.get("/radiation")
async def admin_get_radiation(
    map_slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    game_map = await _get_map(db, map_slug)
    raw = await load_raw_radiation_config_async(game_map)
    data = await get_map_radiation(db, game_map)
    overlay_raw = raw.get("overlay") if isinstance(raw.get("overlay"), dict) else None
    overlay = None
    if overlay_raw and overlay_raw.get("url"):
        bounds = overlay_raw.get("bounds") or {}
        overlay = {
            "url": overlay_raw.get("url", ""),
            "opacity": float(overlay_raw.get("opacity", 0.65)),
            "bounds": {
                "x1": float(bounds.get("x1", 0)),
                "y1": float(bounds.get("y1", 0)),
                "x2": float(bounds.get("x2", game_map.map_size)),
                "y2": float(bounds.get("y2", game_map.map_size)),
            },
            "editorOnly": bool(overlay_raw.get("editorOnly", True)),
        }
    return {
        "map_slug": game_map.slug,
        "map_size": game_map.map_size,
        "tiles_satellite": game_map.tiles_satellite,
        "max_native_zoom": game_map.max_native_zoom,
        "extra_zoom": game_map.extra_zoom,
        "zones": data.get("zones") or [],
        "psi_zones": data.get("psi_zones") or [],
        "legend": data.get("legend") or [],
        "overlay": overlay,
    }


@router.put("/radiation")
async def admin_save_radiation(
    payload: RadiationSaveRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    game_map = await _get_map(db, payload.map_slug)
    
    # Валидация: область не должна быть больше открытой карты
    map_size = game_map.map_size
    for i, z in enumerate(payload.zones):
        if z.x < 0 or z.x > map_size or z.y < 0 or z.y > map_size:
            raise HTTPException(
                status_code=400,
                detail=f"Центр зоны #{i+1} ({z.x}, {z.y}) выходит за границы карты [0, {map_size}]"
            )
        if z.radius <= 0 or z.radius > map_size:
            raise HTTPException(
                status_code=400,
                detail=f"Радиус зоны #{i+1} ({z.radius}) должен быть положительным и не превышать размер карты {map_size}"
            )

    for i, z in enumerate(payload.psi_zones):
        if z.x < 0 or z.x > map_size or z.y < 0 or z.y > map_size:
            raise HTTPException(
                status_code=400,
                detail=f"Центр пси-зоны #{i+1} ({z.x}, {z.y}) выходит за границы карты [0, {map_size}]"
            )
        if z.radius <= 0 or z.radius > map_size:
            raise HTTPException(
                status_code=400,
                detail=f"Радиус пси-зоны #{i+1} ({z.radius}) должен быть положительным и не превышать размер карты {map_size}"
            )

    if payload.overlay and payload.overlay.url:
        ob = payload.overlay.bounds
        min_allowed = -map_size
        max_allowed = map_size * 2
        if ob.x1 < min_allowed or ob.x1 > max_allowed or ob.x2 < min_allowed or ob.x2 > max_allowed or \
           ob.y1 < min_allowed or ob.y1 > max_allowed or ob.y2 < min_allowed or ob.y2 > max_allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Границы подложки слишком сильно выходят за пределы карты (разрешено от {min_allowed} до {max_allowed})"
            )
        if ob.x1 >= ob.x2 or ob.y1 >= ob.y2:
            raise HTTPException(
                status_code=400,
                detail="Некорректные границы подложки: x1 должен быть меньше x2, y1 меньше y2"
            )

    raw: dict = {
        "zones": [z.model_dump() for z in payload.zones],
        "psi_zones": [z.model_dump() for z in payload.psi_zones],
        "legend": [item.model_dump() for item in payload.legend],
        "overlay": None,
    }
    if payload.overlay and payload.overlay.url:
        raw["overlay"] = {
            "url": payload.overlay.url.strip(),
            "opacity": payload.overlay.opacity,
            "bounds": payload.overlay.bounds.model_dump(),
            "editorOnly": payload.overlay.editorOnly,
            "enabled": False,
        }
    url = await save_radiation_config(game_map, db, raw)
    return {"ok": True, "radiation_url": url, "zones": len(payload.zones)}


@router.post("/radiation/overlay")
async def admin_upload_radiation_overlay(
    map_slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
    file: UploadFile = File(...),
):
    import logging

    log = logging.getLogger(__name__)
    game_map = await _get_map(db, map_slug)
    url = await save_radiation_overlay(game_map.slug, file)
    bounds = {
        "x1": 0.0,
        "y1": 0.0,
        "x2": float(game_map.map_size),
        "y2": float(game_map.map_size),
    }
    try:
        raw = await load_raw_radiation_config_async(game_map)
        zones = raw.get("zones") or []
        if not zones:
            data = await get_map_radiation(db, game_map)
            zones = data.get("zones") or []
        await save_radiation_config(
            game_map,
            db,
            {
                "zones": zones,
                "psi_zones": raw.get("psi_zones") or [],
                "legend": raw.get("legend") or [],
                "overlay": {
                    "url": url,
                    "opacity": 0.65,
                    "bounds": bounds,
                    "editorOnly": True,
                    "enabled": False,
                },
            },
        )
    except Exception as exc:
        log.exception("radiation overlay config save failed for %s: %s", map_slug, exc)
    return {"url": url, "opacity": 0.65, "bounds": bounds, "editorOnly": True}


@router.delete("/radiation/overlay")
async def admin_delete_radiation_overlay(
    map_slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    game_map = await _get_map(db, map_slug)
    delete_overlay_file(game_map.slug)
    data = await get_map_radiation(db, game_map)
    raw = await load_raw_radiation_config_async(game_map)
    await save_radiation_config(
        game_map,
        db,
        {
            "zones": data.get("zones") or [],
            "psi_zones": data.get("psi_zones") or [],
            "legend": data.get("legend") or raw.get("legend") or [],
            "overlay": None,
        },
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Road segment admin CRUD
# ---------------------------------------------------------------------------

@router.get("/maps/{map_slug}/roads", response_model=list[RoadSegmentResponse])
async def admin_list_roads(
    map_slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    game_map = await _get_map(db, map_slug)
    return await list_segments(db, game_map.id)


@router.post("/maps/{map_slug}/roads", response_model=RoadSegmentResponse)
async def admin_create_road(
    map_slug: str,
    payload: RoadSegmentCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    if len(payload.points) < 2:
        raise HTTPException(status_code=400, detail="Сегмент дороги должен содержать минимум 2 точки.")
    game_map = await _get_map(db, map_slug)
    return await create_segment(db, game_map.id, payload.road_type, payload.points)


@router.put("/maps/{map_slug}/roads/{road_id}", response_model=RoadSegmentResponse)
async def admin_update_road(
    map_slug: str,
    road_id: int,
    payload: RoadSegmentUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    game_map = await _get_map(db, map_slug)
    result = await update_segment(db, road_id, game_map.id, payload.road_type, payload.points)
    if result is None:
        raise HTTPException(status_code=404, detail="Road segment not found")
    return result


@router.delete("/maps/{map_slug}/roads/{road_id}")
async def admin_delete_road(
    map_slug: str,
    road_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    game_map = await _get_map(db, map_slug)
    ok = await delete_segment(db, road_id, game_map.id)
    if not ok:
        raise HTTPException(status_code=404, detail="Road segment not found")
    return {"ok": True}


@router.delete("/maps/{map_slug}/roads")
async def admin_clear_roads(
    map_slug: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    game_map = await _get_map(db, map_slug)
    count = await clear_segments(db, game_map.id)
    return {"ok": True, "deleted": count}


@router.post("/maps/{map_slug}/roads/delete-bulk")
async def admin_delete_roads_bulk(
    map_slug: str,
    payload: list[int],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    game_map = await _get_map(db, map_slug)
    from sqlalchemy import delete
    result = await db.execute(
        delete(RoadSegment).where(RoadSegment.map_id == game_map.id, RoadSegment.id.in_(payload))
    )
    await db.commit()
    return {"ok": True, "deleted": result.rowcount}


@router.post("/maps/{map_slug}/roads/bulk", response_model=list[RoadSegmentResponse])
async def admin_create_roads_bulk(
    map_slug: str,
    payload: list[RoadSegmentCreate],
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[None, Depends(require_admin)],
):
    game_map = await _get_map(db, map_slug)
    segments_data = [{"road_type": p.road_type, "points": p.points} for p in payload]
    return await create_segments_bulk(db, game_map.id, segments_data)


