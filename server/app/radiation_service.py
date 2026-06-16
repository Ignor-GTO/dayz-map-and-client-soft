"""Radiation zones: image overlay + vector circles in game coordinates."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DayZMap

from app.config import DATA_DIR

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
DATA_RADIATION_DIR = DATA_DIR / "radiation"

DEFAULT_RADIATION_FILES: dict[str, str] = {
    "pripyat": "/static/data/pripyat-radiation.json",
}

_cache: dict[str, dict] = {}

DEFAULT_LEGEND = [
    {"color": "#4caf50", "label": "250 мЗв/ч"},
    {"color": "#cddc39", "label": "280 мЗв/ч"},
    {"color": "#ff9800", "label": "350 мЗв/ч"},
    {"color": "#f44336", "label": "530 мЗв/ч"},
]


def radiation_config_path(slug: str) -> Path:
    return DATA_RADIATION_DIR / f"{slug}.json"


def radiation_config_fallback_path(slug: str) -> Path:
    return STATIC_DIR / "data" / f"{slug}-radiation.json"


def resolve_radiation_config_file(slug: str) -> Path | None:
    preferred = radiation_config_path(slug)
    if preferred.is_file():
        return preferred
    fallback = radiation_config_fallback_path(slug)
    if fallback.is_file():
        return fallback
    return None


async def load_radiation_raw(game_map: DayZMap) -> dict:
    local = resolve_radiation_config_file(game_map.slug)
    if local:
        return json.loads(local.read_text(encoding="utf-8"))
    url = resolve_radiation_url(game_map)
    if not url:
        return {"overlay": None, "zones": [], "legend": list(DEFAULT_LEGEND)}
    return await _fetch_json(url)


def invalidate_radiation_cache(slug: str) -> None:
    keys = [k for k in _cache if k.startswith(f"{slug}:")]
    for k in keys:
        _cache.pop(k, None)


async def load_raw_radiation_config_async(game_map: DayZMap) -> dict:
    try:
        return await load_radiation_raw(game_map)
    except Exception as exc:
        logger.warning("radiation raw load failed for %s: %s", game_map.slug, exc)
        return {"overlay": None, "zones": [], "legend": list(DEFAULT_LEGEND)}


async def save_radiation_config(game_map: DayZMap, db: AsyncSession, raw: dict) -> str:
    slug = game_map.slug
    path = radiation_config_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)

    zones = _normalize_zones(raw.get("zones") or [])
    legend = raw.get("legend") or list(DEFAULT_LEGEND)
    overlay = raw.get("overlay")

    payload = {
        "overlay": overlay,
        "zones": zones,
        "legend": legend,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    public_url = f"/static/data/{slug}-radiation.json"
    if not game_map.radiation_url:
        game_map.radiation_url = public_url
        await db.commit()

    invalidate_radiation_cache(slug)
    return public_url


def _static_json_path(url: str) -> Path | None:
    if url.startswith("/static/"):
        return STATIC_DIR / url.removeprefix("/static/")
    return None


def _public_static_url(url: str) -> str:
    """Browser paths: StaticFiles root is /static dir, so /data/... not /static/data/..."""
    if url.startswith("/static/"):
        return url.removeprefix("/static")
    return url


def _public_overlay_url(url: str) -> str:
    url = str(url or "").strip()
    if url.startswith("/uploads/"):
        return url
    return _public_static_url(url)


def _normalize_payload(raw: dict, map_size: float) -> dict:
    overlay_raw = raw.get("overlay")
    overlay = None
    if overlay_raw and isinstance(overlay_raw, dict):
        bounds = overlay_raw.get("bounds") or {}
        overlay = {
            "url": _public_overlay_url(str(overlay_raw.get("url", ""))),
            "enabled": bool(overlay_raw.get("enabled", False)) and not bool(overlay_raw.get("editorOnly")),
            "opacity": float(overlay_raw.get("opacity", 0.3)),
            "bounds": {
                "x1": float(bounds.get("x1", 0)),
                "y1": float(bounds.get("y1", 0)),
                "x2": float(bounds.get("x2", map_size)),
                "y2": float(bounds.get("y2", map_size)),
            },
        }

    zones = _normalize_zones(raw.get("zones") or [])

    legend = []
    for item in raw.get("legend") or []:
        if isinstance(item, dict) and item.get("label"):
            legend.append({"color": str(item.get("color", "#ccc")), "label": str(item["label"])})

    polygons = _normalize_polygons(raw.get("polygons") or [])

    return {"overlay": overlay, "polygons": polygons, "zones": zones, "legend": legend}


def _normalize_zones(items: list) -> list[dict]:
    zones = []
    for z in items:
        if not isinstance(z, dict):
            continue
        zones.append(
            {
                "id": str(z.get("id", "")),
                "label": str(z.get("label", "")),
                "x": float(z["x"]),
                "y": float(z["y"]),
                "radius": float(z["radius"]),
                "color": str(z.get("color", "#ff9800")),
                "fillOpacity": float(z.get("fillOpacity", 0.18)),
                "strokeOpacity": float(z.get("strokeOpacity", 0.9)),
                "weight": int(z.get("weight", 2)),
            }
        )
    return zones


async def _load_zones(raw: dict) -> list[dict]:
    if raw.get("zones"):
        return _normalize_zones(raw["zones"])
    url = raw.get("zonesUrl") or raw.get("zones_url")
    if not url:
        return []
    try:
        if isinstance(url, str) and url.startswith("/"):
            local = STATIC_DIR / url.lstrip("/")
            if local.is_file():
                data = json.loads(local.read_text(encoding="utf-8"))
                return _normalize_zones(data.get("zones") or [])
        data = await _fetch_json(url)
        if isinstance(data, dict):
            return _normalize_zones(data.get("zones") or [])
        return _normalize_zones(data if isinstance(data, list) else [])
    except Exception as exc:
        logger.warning("radiation zones load failed: %s", exc)
        return []


def _normalize_polygons(items: list) -> list[dict]:
    polygons = []
    for p in items:
        if not isinstance(p, dict):
            continue
        rings = []
        for ring in p.get("rings") or []:
            if not isinstance(ring, list) or len(ring) < 3:
                continue
            coords = []
            for pt in ring:
                if not isinstance(pt, (list, tuple)) or len(pt) < 2:
                    continue
                coords.append([float(pt[0]), float(pt[1])])
            if len(coords) >= 3:
                rings.append(coords)
        if not rings:
            continue
        polygons.append(
            {
                "id": str(p.get("id", "")),
                "tier": str(p.get("tier", "")),
                "label": str(p.get("label", "")),
                "color": str(p.get("color", "#ff9800")),
                "fillOpacity": float(p.get("fillOpacity", 0.4)),
                "strokeOpacity": float(p.get("strokeOpacity", 0.95)),
                "weight": int(p.get("weight", 2)),
                "rings": rings,
            }
        )
    return polygons


async def _load_polygons(raw: dict) -> list[dict]:
    if raw.get("polygons"):
        return _normalize_polygons(raw["polygons"])
    url = raw.get("polygonsUrl") or raw.get("polygons_url")
    if not url:
        return []
    try:
        if isinstance(url, str) and url.startswith("/"):
            local = STATIC_DIR / url.lstrip("/")
            if local.is_file():
                data = json.loads(local.read_text(encoding="utf-8"))
                return _normalize_polygons(data.get("polygons") or [])
        data = await _fetch_json(url)
        return _normalize_polygons(data.get("polygons") or data if isinstance(data, list) else [])
    except Exception as exc:
        logger.warning("radiation polygons load failed: %s", exc)
        return []


async def _fetch_json(url: str) -> dict:
    local = _static_json_path(url)
    if local and local.is_file():
        return json.loads(local.read_text(encoding="utf-8"))

    if url.startswith(("http://", "https://")):
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.json()

    raise FileNotFoundError(f"Radiation config not found: {url}")


def resolve_radiation_url(game_map: DayZMap) -> str | None:
    if game_map.radiation_url:
        return game_map.radiation_url.strip()
    return DEFAULT_RADIATION_FILES.get(game_map.slug)


async def get_map_radiation(db: AsyncSession, game_map: DayZMap) -> dict:
    del db  # reserved for future DB-stored zones
    cache_key = f"{game_map.slug}:{resolve_radiation_url(game_map) or 'data'}"
    if cache_key in _cache:
        return _cache[cache_key]

    try:
        raw = await load_radiation_raw(game_map)
        zones = await _load_zones(raw)
        polygons = await _load_polygons(raw) if not zones else []
        data = _normalize_payload(raw, game_map.map_size)
        data["zones"] = zones or data.get("zones") or []
        data["polygons"] = polygons if not data["zones"] else []
        _cache[cache_key] = data
        return data
    except Exception as exc:
        logger.warning("radiation load failed for %s: %s", game_map.slug, exc)
        return {"overlay": None, "polygons": [], "zones": [], "legend": []}
