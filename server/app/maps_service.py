from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import CLIENT_DOWNLOAD_URL, MAP_ATTRIBUTION, SCUM_CLIENT_DOWNLOAD_URL, SERVER_PUBLIC_URL
from app.models import DayZMap
from app.schemas import MapConfigResponse, MapListItem
from app.scum_profile import (
    SCUM_BOUNDS,
    SCUM_MAP_PX,
    SCUM_MAX_ZOOM,
    SCUM_MIN_ZOOM,
    SCUM_TILE_SIZE,
    SCUM_ZOOM_OFFSET,
    is_scum_map,
)
from app.seed import DEFAULT_MAP_NAME, DEFAULT_MAP_SLUG, default_map_kwargs, ensure_maps_seeded


def map_to_config(game_map: DayZMap) -> MapConfigResponse:
    if is_scum_map(game_map.slug):
        return MapConfigResponse(
            slug=game_map.slug,
            name=game_map.name,
            bounds=dict(SCUM_BOUNDS),
            map_size=float(game_map.map_size or SCUM_MAP_PX),
            max_native_zoom=game_map.max_native_zoom or SCUM_MAX_ZOOM,
            extra_zoom=game_map.extra_zoom or 0,
            tiles_satellite=game_map.tiles_satellite,
            tiles_topographic=game_map.tiles_topographic or game_map.tiles_satellite,
            attribution="SCUM tiles · mirrored from scum-map.com via mustard0207/scum_map",
            server_url=SERVER_PUBLIC_URL,
            client_download_url=SCUM_CLIENT_DOWNLOAD_URL,
            coord_system="scum",
            tile_size=SCUM_TILE_SIZE,
            min_zoom=SCUM_MIN_ZOOM,
            zoom_offset=SCUM_ZOOM_OFFSET,
        )

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
        coord_system="dayz",
        tile_size=256,
        min_zoom=0,
        zoom_offset=0,
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
        coord_system="dayz",
        tile_size=256,
        min_zoom=0,
        zoom_offset=0,
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
