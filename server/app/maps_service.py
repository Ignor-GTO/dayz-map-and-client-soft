from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import CLIENT_DOWNLOAD_URL, MAP_ATTRIBUTION, SERVER_PUBLIC_URL
from app.models import DayZMap
from app.schemas import MapConfigResponse, MapListItem
from app.seed import DEFAULT_MAP_NAME, DEFAULT_MAP_SLUG, default_map_kwargs, ensure_maps_seeded


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


def env_fallback_config(slug: str = DEFAULT_MAP_SLUG) -> MapConfigResponse:
    defaults = default_map_kwargs()
    size = defaults["map_size"]
    return MapConfigResponse(
        slug=slug,
        name=defaults["name"],
        bounds={
            "min_x": 0,
            "max_x": size,
            "min_y": 0,
            "max_y": size,
        },
        map_size=size,
        max_native_zoom=defaults["max_native_zoom"],
        extra_zoom=defaults["extra_zoom"],
        tiles_satellite=defaults["tiles_satellite"],
        tiles_topographic=defaults["tiles_topographic"],
        attribution=MAP_ATTRIBUTION,
        server_url=SERVER_PUBLIC_URL,
        client_download_url=CLIENT_DOWNLOAD_URL,
    )


async def list_enabled_maps(db: AsyncSession) -> list[MapListItem]:
    await ensure_maps_seeded(db)
    result = await db.execute(
        select(DayZMap).where(DayZMap.enabled.is_(True)).order_by(DayZMap.sort_order, DayZMap.name)
    )
    maps = [MapListItem(slug=m.slug, name=m.name) for m in result.scalars().all()]
    if maps:
        return maps
    return [MapListItem(slug=DEFAULT_MAP_SLUG, name=DEFAULT_MAP_NAME)]


async def resolve_map_config(db: AsyncSession, slug: str) -> MapConfigResponse:
    await ensure_maps_seeded(db)
    normalized = slug.strip().lower()
    result = await db.execute(select(DayZMap).where(DayZMap.slug == normalized))
    game_map = result.scalar_one_or_none()
    if game_map and game_map.enabled:
        return map_to_config(game_map)
    if normalized == DEFAULT_MAP_SLUG:
        return env_fallback_config(normalized)
    raise HTTPException(status_code=404, detail="Map not found")
