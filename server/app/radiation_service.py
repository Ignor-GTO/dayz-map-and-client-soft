"""Radiation zones: image overlay + vector circles in game coordinates."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DayZMap

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

DEFAULT_RADIATION_FILES: dict[str, str] = {
    "pripyat": "/static/data/pripyat-radiation.json",
}

_cache: dict[str, dict] = {}


def _static_json_path(url: str) -> Path | None:
    if url.startswith("/static/"):
        return STATIC_DIR / url.removeprefix("/static/")
    return None


def _normalize_payload(raw: dict, map_size: float) -> dict:
    overlay = raw.get("overlay")
    if overlay and isinstance(overlay, dict):
        bounds = overlay.get("bounds") or {}
        overlay = {
            "url": str(overlay.get("url", "")),
            "opacity": float(overlay.get("opacity", 0.55)),
            "bounds": {
                "x1": float(bounds.get("x1", 0)),
                "y1": float(bounds.get("y1", 0)),
                "x2": float(bounds.get("x2", map_size)),
                "y2": float(bounds.get("y2", map_size)),
            },
        }

    zones = []
    for z in raw.get("zones") or []:
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
                "weight": int(z.get("weight", 2)),
            }
        )

    legend = []
    for item in raw.get("legend") or []:
        if isinstance(item, dict) and item.get("label"):
            legend.append({"color": str(item.get("color", "#ccc")), "label": str(item["label"])})

    return {"overlay": overlay, "zones": zones, "legend": legend}


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
    url = resolve_radiation_url(game_map)
    if not url:
        return {"overlay": None, "zones": [], "legend": []}

    cache_key = f"{game_map.slug}:{url}"
    if cache_key in _cache:
        return _cache[cache_key]

    try:
        raw = await _fetch_json(url)
        data = _normalize_payload(raw, game_map.map_size)
        _cache[cache_key] = data
        return data
    except Exception as exc:
        logger.warning("radiation load failed for %s: %s", game_map.slug, exc)
        return {"overlay": None, "zones": [], "legend": []}
