"""Coarse elevation map built from live player Z samples (SCUM bridge).

Grid cells store a running average of reported heights so #Teleport / click
lookup can estimate Z where no player is standing.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# ~10 km cells in SCUM cm units — enough for teleport, sparse enough to store.
CELL_SIZE = 10_000.0
MAX_SAMPLE_DIST = 35_000.0  # reject lookups farther than this from any sample
DATA_DIR = Path(__file__).resolve().parent.parent / "static" / "data" / "elevation"

_lock = threading.Lock()
# slug -> { "cell_key": {"z": float, "n": int, "updated": float} }
_cache: dict[str, dict[str, dict]] = {}
_dirty: dict[str, bool] = {}
_last_save_at: dict[str, float] = {}
_SAVE_INTERVAL_SEC = 5.0


def _path_for(slug: str) -> Path:
    safe = "".join(c for c in slug.lower() if c.isalnum() or c in "-_") or "map"
    return DATA_DIR / f"{safe}-elevation.json"


def _cell_key(x: float, y: float) -> str:
    cx = math.floor(x / CELL_SIZE)
    cy = math.floor(y / CELL_SIZE)
    return f"{cx}:{cy}"


def _cell_center(key: str) -> tuple[float, float]:
    cx_s, cy_s = key.split(":")
    cx, cy = int(cx_s), int(cy_s)
    return (cx + 0.5) * CELL_SIZE, (cy + 0.5) * CELL_SIZE


def _load(slug: str) -> dict[str, dict]:
    if slug in _cache:
        return _cache[slug]
    path = _path_for(slug)
    data: dict[str, dict] = {}
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            cells = raw.get("cells") if isinstance(raw, dict) else None
            if isinstance(cells, dict):
                data = cells
        except Exception:
            logger.exception("Failed to load elevation grid for %s", slug)
    _cache[slug] = data
    return data


def _save(slug: str) -> None:
    path = _path_for(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": "scum_elevation_v1",
        "cell_size": CELL_SIZE,
        "updated_at": time.time(),
        "cells": _cache.get(slug) or {},
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def record_elevation_sample(slug: str, x: float, y: float, z: float) -> None:
    """Update running average for the cell containing (x, y)."""
    if not slug or not math.isfinite(x) or not math.isfinite(y) or not math.isfinite(z):
        return
    # Ignore absurd heights (under map / skybox glitches).
    if z < -50_000 or z > 500_000:
        return
    key = _cell_key(x, y)
    with _lock:
        cells = _load(slug)
        prev = cells.get(key)
        if prev and isinstance(prev.get("z"), (int, float)) and int(prev.get("n") or 0) > 0:
            n = int(prev["n"])
            # Cap influence of old samples so terrain changes (new builds) adapt.
            n_eff = min(n, 40)
            new_z = (float(prev["z"]) * n_eff + float(z)) / (n_eff + 1)
            cells[key] = {"z": new_z, "n": n + 1, "updated": time.time()}
        else:
            cells[key] = {"z": float(z), "n": 1, "updated": time.time()}
        _cache[slug] = cells
        _dirty[slug] = True
        now = time.time()
        if now - _last_save_at.get(slug, 0) >= _SAVE_INTERVAL_SEC:
            try:
                _save(slug)
                _dirty[slug] = False
                _last_save_at[slug] = now
            except Exception:
                logger.exception("Failed to save elevation grid for %s", slug)


def lookup_elevation(slug: str, x: float, y: float) -> dict:
    """Inverse-distance weighted estimate from nearby cells."""
    with _lock:
        cells = dict(_load(slug))

    if not cells:
        return {"ok": True, "z": None, "source": "empty", "samples": 0, "distance": None}

    key = _cell_key(x, y)
    if key in cells and isinstance(cells[key].get("z"), (int, float)):
        return {
            "ok": True,
            "z": float(cells[key]["z"]),
            "source": "cell",
            "samples": int(cells[key].get("n") or 1),
            "distance": 0.0,
        }

    cx = math.floor(x / CELL_SIZE)
    cy = math.floor(y / CELL_SIZE)
    candidates: list[tuple[float, float, int]] = []
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            k = f"{cx + dx}:{cy + dy}"
            cell = cells.get(k)
            if not cell or not isinstance(cell.get("z"), (int, float)):
                continue
            ccx, ccy = _cell_center(k)
            dist = math.hypot(x - ccx, y - ccy)
            candidates.append((dist, float(cell["z"]), int(cell.get("n") or 1)))

    if not candidates:
        best = None
        for k, cell in cells.items():
            if not isinstance(cell.get("z"), (int, float)):
                continue
            ccx, ccy = _cell_center(k)
            dist = math.hypot(x - ccx, y - ccy)
            if best is None or dist < best[0]:
                best = (dist, float(cell["z"]), int(cell.get("n") or 1))
        if best is None:
            return {"ok": True, "z": None, "source": "empty", "samples": 0, "distance": None}
        candidates = [best]

    candidates.sort(key=lambda t: t[0])
    near = [c for c in candidates if c[0] <= MAX_SAMPLE_DIST][:8]
    if not near:
        dist, z, n = candidates[0]
        return {
            "ok": True,
            "z": None,
            "source": "too_far",
            "samples": n,
            "distance": dist,
            "nearest_z": z,
        }

    num = 0.0
    den = 0.0
    for dist, z, n in near:
        w = (1.0 / max(dist, 1.0) ** 2) * math.log1p(n)
        num += w * z
        den += w
    z_est = num / den if den else near[0][1]
    return {
        "ok": True,
        "z": z_est,
        "source": "idw",
        "samples": len(near),
        "distance": near[0][0],
    }


def elevation_stats(slug: str) -> dict:
    with _lock:
        cells = _load(slug)
        return {"ok": True, "cells": len(cells), "cell_size": CELL_SIZE}
