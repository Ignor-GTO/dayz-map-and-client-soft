"""CRUD for custom server building footprints on the map."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MapBuilding

BUILDING_TYPES = {
    "structure": "Строение",
    "residential": "Жилое",
    "industrial": "Промышленное",
    "military": "Военное",
    "commercial": "Коммерческое",
    "other": "Прочее",
}


def _building_to_dict(b: MapBuilding) -> dict:
    return {
        "id": b.id,
        "map_id": b.map_id,
        "title": b.title,
        "classname": b.classname,
        "description": b.description or "",
        "building_type": b.building_type or "structure",
        "x": b.x,
        "y": b.y,
        "width": b.width,
        "depth": b.depth,
        "yaw": b.yaw,
        "stroke_color": b.stroke_color,
        "fill_color": b.fill_color,
        "enabled": bool(b.enabled),
        "created_at": b.created_at.isoformat() if b.created_at else None,
    }


async def list_buildings(db: AsyncSession, map_id: int, *, enabled_only: bool = False) -> list[dict]:
    query = select(MapBuilding).where(MapBuilding.map_id == map_id).order_by(MapBuilding.id)
    if enabled_only:
        query = query.where(MapBuilding.enabled.is_(True))
    result = await db.execute(query)
    return [_building_to_dict(b) for b in result.scalars().all()]


async def create_building(db: AsyncSession, map_id: int, data: dict) -> dict:
    building_type = (data.get("building_type") or "structure").strip().lower()
    if building_type not in BUILDING_TYPES:
        building_type = "structure"
    width = float(data.get("width") or 20.0)
    depth = float(data.get("depth") or 15.0)
    if width <= 0 or depth <= 0:
        raise ValueError("Width and depth must be greater than zero")
    row = MapBuilding(
        map_id=map_id,
        title=(data.get("title") or "Здание").strip()[:128],
        classname=(data.get("classname") or None),
        description=(data.get("description") or "").strip(),
        building_type=building_type,
        x=float(data["x"]),
        y=float(data["y"]),
        width=width,
        depth=depth,
        yaw=float(data.get("yaw") or 0.0),
        stroke_color=data.get("stroke_color"),
        fill_color=data.get("fill_color"),
        enabled=bool(data.get("enabled", True)),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _building_to_dict(row)


async def update_building(db: AsyncSession, building_id: int, map_id: int, data: dict) -> dict | None:
    result = await db.execute(
        select(MapBuilding).where(MapBuilding.id == building_id, MapBuilding.map_id == map_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    if "title" in data and data["title"] is not None:
        row.title = str(data["title"]).strip()[:128]
    if "classname" in data:
        row.classname = data["classname"] or None
    if "description" in data and data["description"] is not None:
        row.description = str(data["description"]).strip()
    if "building_type" in data and data["building_type"] is not None:
        bt = str(data["building_type"]).strip().lower()
        row.building_type = bt if bt in BUILDING_TYPES else row.building_type
    if "x" in data and data["x"] is not None:
        row.x = float(data["x"])
    if "y" in data and data["y"] is not None:
        row.y = float(data["y"])
    if "width" in data and data["width"] is not None:
        row.width = max(1.0, float(data["width"]))
    if "depth" in data and data["depth"] is not None:
        row.depth = max(1.0, float(data["depth"]))
    if "yaw" in data and data["yaw"] is not None:
        row.yaw = float(data["yaw"])
    if "stroke_color" in data:
        row.stroke_color = data["stroke_color"] or None
    if "fill_color" in data:
        row.fill_color = data["fill_color"] or None
    if "enabled" in data and data["enabled"] is not None:
        row.enabled = bool(data["enabled"])
    await db.commit()
    await db.refresh(row)
    return _building_to_dict(row)


async def delete_building(db: AsyncSession, building_id: int, map_id: int) -> bool:
    result = await db.execute(
        select(MapBuilding).where(MapBuilding.id == building_id, MapBuilding.map_id == map_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True
