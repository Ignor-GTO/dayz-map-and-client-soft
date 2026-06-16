"""Fetch and normalize map location data (iZurvive / xam.nu formats).

Based on https://github.com/WoozyMasta/dzmap coordinate conversion.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DayZMap

logger = logging.getLogger(__name__)

CACHE_TTL_SEC = 3600

CATEGORY_LABELS = {
    "cities": "Города",
    "military": "Военные",
    "local": "Локации",
    "water": "Водоёмы",
    "terrain": "Рельеф",
}

DEFAULT_IZURVIVE_URLS: dict[str, str] = {
    "pripyat": "https://www.izurvive.com/assets/pripyat/citynames-d65541f5.json",
}

XAM_JSON_URLS: dict[str, str] = {
    "chernarusplus": "https://static.xam.nu/dayz/json/chernarusplus/1.28-2.json",
    "chernarus": "https://static.xam.nu/dayz/json/chernarusplus/1.28-2.json",
    "livonia": "https://static.xam.nu/dayz/json/livonia/1.28-2.json",
    "enoch": "https://static.xam.nu/dayz/json/livonia/1.28-2.json",
    "sakhal": "https://static.xam.nu/dayz/json/sakhal/1.28-2.json",
}

_cache: dict[str, tuple[float, list[dict]]] = {}


@dataclass
class ParsedLocation:
    title: str
    category: str
    type: str
    label_class: str
    x: float
    y: float
    min_zoom: int


def izurvive_to_game(lng: float, lat: float, map_size: float) -> tuple[float, float]:
    pi = math.pi
    game_x = (lng + 180.0) * map_size / 360.0
    lat_rad = lat * pi / 180.0
    mercator_y = math.log(math.tan(pi * 0.25 + lat_rad * 0.5))
    game_y = (mercator_y + pi) * map_size / (2.0 * pi)
    return game_x, game_y


def xam_to_game(xam_y: float, xam_x: float, map_size: float) -> tuple[float, float]:
    game_x = (xam_x * map_size) / 256.0
    game_y = ((256.0 + xam_y) * map_size) / 256.0
    return game_x, game_y


def normalize_category(raw_type: str) -> str:
    t = raw_type.lower()
    if t in {"namecitycapital", "namecity", "namevillage", "flatareacity", "flatareacitysmall"}:
        return "cities"
    if t == "strongpointarea":
        return "military"
    if t == "namemarine":
        return "water"
    if t in {"hill", "rockarea"}:
        return "terrain"
    return "local"


def label_class(raw_type: str) -> str:
    t = raw_type.lower()
    if "capital" in t:
        return "capital"
    if t == "namecity":
        return "city"
    if t in {"namevillage", "flatareacity", "flatareacitysmall"}:
        return "village"
    if t == "namemarine":
        return "marine"
    if t == "hill":
        return "hill"
    if t == "strongpointarea":
        return "camp"
    if t == "rockarea":
        return "ruin"
    return "local"


def parse_izurvive(data: list, map_size: float) -> list[ParsedLocation]:
    out: list[ParsedLocation] = []
    for item in data:
        lng = item.get("lng")
        lat = item.get("lat")
        if lng is None or lat is None:
            continue
        raw_type = str(item.get("type") or "NameLocal")
        title = item.get("nameRU") or item.get("nameEN") or "?"
        x, y = izurvive_to_game(float(lng), float(lat), map_size)
        out.append(
            ParsedLocation(
                title=str(title),
                category=normalize_category(raw_type),
                type=raw_type,
                label_class=label_class(raw_type),
                x=x,
                y=y,
                min_zoom=int(item.get("minZoom") or 4),
            )
        )
    return out


def parse_xam(data: dict, map_size: float) -> list[ParsedLocation]:
    out: list[ParsedLocation] = []
    locations = data.get("markers", {}).get("locations") or []
    for item in locations:
        pos = item.get("p") or []
        if len(pos) < 2:
            continue
        raw_type = str(item.get("w") or "local")
        names = item.get("s") or []
        title = names[0] if names else "?"
        x, y = xam_to_game(float(pos[0]), float(pos[1]), map_size)
        out.append(
            ParsedLocation(
                title=str(title),
                category=normalize_category(raw_type),
                type=raw_type,
                label_class=label_class(raw_type),
                x=x,
                y=y,
                min_zoom=3,
            )
        )
    return out


async def _fetch_json(url: str) -> object:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "DayZMapClient/1.0"})
        resp.raise_for_status()
        return resp.json()


def _resolve_sources(game_map: DayZMap) -> tuple[str, str] | None:
    if game_map.locations_url:
        source = (game_map.locations_source or "izurvive").lower()
        return game_map.locations_url, source
    slug = game_map.slug.lower()
    if slug in DEFAULT_IZURVIVE_URLS:
        return DEFAULT_IZURVIVE_URLS[slug], "izurvive"
    if slug in XAM_JSON_URLS:
        return XAM_JSON_URLS[slug], "xam"
    return None


async def get_map_locations(db: AsyncSession, game_map: DayZMap) -> dict:
    cache_key = f"{game_map.slug}:{game_map.map_size}"
    cached = _cache.get(cache_key)
    if cached and time.time() - cached[0] < CACHE_TTL_SEC:
        return cached[1]

    resolved = _resolve_sources(game_map)
    if not resolved:
        result = {"categories": [], "locations": []}
        _cache[cache_key] = (time.time(), result)
        return result

    url, source = resolved
    try:
        raw = await _fetch_json(url)
        if source == "xam":
            parsed = parse_xam(raw if isinstance(raw, dict) else {}, game_map.map_size)
        else:
            parsed = parse_izurvive(raw if isinstance(raw, list) else [], game_map.map_size)
    except Exception:
        logger.exception("Failed to fetch locations for %s from %s", game_map.slug, url)
        result = {"categories": [], "locations": []}
        _cache[cache_key] = (time.time(), result)
        return result

    counts: dict[str, int] = {}
    locations = []
    for loc in parsed:
        counts[loc.category] = counts.get(loc.category, 0) + 1
        locations.append(
            {
                "title": loc.title,
                "category": loc.category,
                "type": loc.type,
                "label_class": loc.label_class,
                "x": loc.x,
                "y": loc.y,
                "min_zoom": loc.min_zoom,
            }
        )

    categories = [
        {"id": cat_id, "label": CATEGORY_LABELS.get(cat_id, cat_id), "count": counts[cat_id]}
        for cat_id in CATEGORY_LABELS
        if counts.get(cat_id, 0) > 0
    ]

    result = {"categories": categories, "locations": locations}
    _cache[cache_key] = (time.time(), result)
    logger.info("Loaded %d locations for %s", len(locations), game_map.slug)
    return result
