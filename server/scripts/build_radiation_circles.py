"""Extract radiation zones as smooth circles from reference map image.

Usage (from server/):
  python scripts/build_radiation_circles.py
"""

from __future__ import annotations

import colorsys
import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

MAP_SIZE = 20480
REF = Path(__file__).resolve().parent.parent / "static/data/pripyat-radiation-ref.jpg"
OUT_ZONES = Path(__file__).resolve().parent.parent / "static/data/pripyat-radiation-zones.json"
MAIN_JSON = Path(__file__).resolve().parent.parent / "static/data/pripyat-radiation.json"

TIERS = [
    {
        "id": "green",
        "color": "#4caf50",
        "label": "Слабая радиация",
        "fillOpacity": 0.32,
        "strokeOpacity": 0.88,
        "weight": 2,
        "scatter_min": 280,
        "scatter_max": 750,
        "min_circularity": 0.80,
    },
    {
        "id": "yellow",
        "color": "#cddc39",
        "label": "Средняя",
        "fillOpacity": 0.35,
        "strokeOpacity": 0.9,
        "weight": 2,
        "scatter_min": 200,
        "scatter_max": 680,
        "min_circularity": 0.78,
    },
    {
        "id": "orange",
        "color": "#ff9800",
        "label": "Высокая",
        "fillOpacity": 0.38,
        "strokeOpacity": 0.92,
        "weight": 2,
        "scatter_min": 180,
        "scatter_max": 640,
        "min_circularity": 0.78,
    },
    {
        "id": "red",
        "color": "#f44336",
        "label": "Смертельная",
        "fillOpacity": 0.4,
        "strokeOpacity": 0.95,
        "weight": 2,
        "scatter_min": 160,
        "scatter_max": 540,
        "min_circularity": 0.80,
    },
]

CNPP = {"x": 7310.0, "y": 15285.0}
# Concentric rings at CNPP — calibrated from reference map radii.
CNPP_RINGS = [
    ("green", 4300.0),
    ("yellow", 2850.0),
    ("orange", 1650.0),
    ("red", 1150.0),
]
MAX_SIDE = 3072
CENTER_MERGE_DIST = 300
CNPP_EXCLUDE_PAD = 500.0


def radiation_tier(rgb: np.ndarray) -> np.ndarray:
    """Vectorized tier index per pixel (0..3) or -1."""
    rgb_f = rgb.astype(np.float32) / 255.0
    r, g, b = rgb_f[..., 0], rgb_f[..., 1], rgb_f[..., 2]
    maxc = np.maximum(np.maximum(r, g), b)
    minc = np.minimum(np.minimum(r, g), b)
    v = maxc
    s = np.divide(maxc - minc, maxc, out=np.zeros_like(maxc), where=maxc > 0)

    h = np.zeros_like(r)
    mask = maxc == minc
    rc = np.where(mask, 0, (maxc - r) / (maxc - minc + 1e-6))
    gc = np.where(mask, 0, (maxc - g) / (maxc - minc + 1e-6))
    bc = np.where(mask, 0, (maxc - b) / (maxc - minc + 1e-6))
    h = np.where((maxc == r) & ~mask, bc - gc, h)
    h = np.where((maxc == g) & ~mask, 2.0 + rc - bc, h)
    h = np.where((maxc == b) & ~mask, 4.0 + gc - rc, h)
    h = (h / 6.0) % 1.0

    out = np.full(r.shape, -1, dtype=np.int8)
    base = (v >= 0.42) & (s >= 0.55)
    ri, gi, bi = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    out = np.where(base & (h < 0.055) & (ri > 148) & (ri > gi + 48), 3, out)
    out = np.where(base & (h >= 0.055) & (h < 0.12) & (ri > 158) & (gi < 128), 2, out)
    out = np.where(base & (h >= 0.12) & (h < 0.19) & (ri > 152) & (gi > 98) & (bi < 88), 1, out)
    out = np.where(base & (h >= 0.19) & (h < 0.37) & (gi > 118) & (gi > ri + 28) & (bi < 118), 0, out)
    return out


def px_to_game(px: float, py: float, w: float, h: float) -> tuple[float, float]:
    return px / w * MAP_SIZE, (1.0 - py / h) * MAP_SIZE


def px_radius_to_game(r: float, w: float, h: float) -> float:
    return r * ((MAP_SIZE / w) + (MAP_SIZE / h)) / 2.0


def _circularity(contour: np.ndarray) -> float:
    area = cv2.contourArea(contour)
    perim = cv2.arcLength(contour, True)
    if perim <= 0 or area <= 0:
        return 0.0
    return float(4.0 * np.pi * area / (perim * perim))


def _contour_circles(mask: np.ndarray, min_circ: float, min_area: float = 100.0) -> list[tuple[float, float, float]]:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out: list[tuple[float, float, float]] = []
    for contour in contours:
        if cv2.contourArea(contour) < min_area:
            continue
        if _circularity(contour) < min_circ:
            continue
        (cx, cy), r = cv2.minEnclosingCircle(contour)
        out.append((float(cx), float(cy), float(r)))
    return out


def _dedupe_zones(zones: list[dict]) -> list[dict]:
    from collections import defaultdict

    by_color: dict[str, list[dict]] = defaultdict(list)
    for z in zones:
        by_color[z["color"]].append(z)

    out: list[dict] = []
    for items in by_color.values():
        items.sort(key=lambda z: z["radius"], reverse=True)
        kept: list[dict] = []
        for z in items:
            ok = True
            for k in kept:
                d = math.hypot(z["x"] - k["x"], z["y"] - k["y"])
                if d < CENTER_MERGE_DIST:
                    dr = abs(z["radius"] - k["radius"])
                    if dr < max(z["radius"], k["radius"]) * 0.2:
                        ok = False
                        break
            if ok:
                kept.append(z)
        out.extend(kept)
    return out


def _cnpp_zones() -> list[dict]:
    zones: list[dict] = []
    for tier_id, radius in CNPP_RINGS:
        tier = next(t for t in TIERS if t["id"] == tier_id)
        zones.append(
            {
                "id": f"cnpp-{tier_id}",
                "label": tier["label"],
                "x": CNPP["x"],
                "y": CNPP["y"],
                "radius": radius,
                "color": tier["color"],
                "fillOpacity": tier["fillOpacity"],
                "strokeOpacity": tier["strokeOpacity"],
                "weight": tier["weight"],
            }
        )
    return zones


def _scatter_zones(tier_masks: list[np.ndarray], w: int, h: int) -> list[dict]:
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    cnpp_radii = {tid: r for tid, r in CNPP_RINGS}
    zones: list[dict] = []
    counts: dict[str, int] = {t["id"]: 0 for t in TIERS}

    for tier_idx, tier in enumerate(TIERS):
        raw = tier_masks[tier_idx]
        if not raw.any():
            continue
        closed = cv2.morphologyEx(raw, cv2.MORPH_CLOSE, kernel, iterations=1)
        px_circles = _contour_circles(closed, tier["min_circularity"], min_area=120.0)
        exclude = max(cnpp_radii.values()) + CNPP_EXCLUDE_PAD

        for cx, cy, r_px in px_circles:
            gx, gy = px_to_game(cx, cy, w, h)
            radius = px_radius_to_game(r_px, w, h)
            if radius < tier["scatter_min"] or radius > tier["scatter_max"]:
                continue
            if math.hypot(gx - CNPP["x"], gy - CNPP["y"]) < exclude:
                continue
            counts[tier["id"]] += 1
            zones.append(
                {
                    "id": f"{tier['id']}-{counts[tier['id']]}",
                    "label": tier["label"],
                    "x": round(gx, 1),
                    "y": round(gy, 1),
                    "radius": round(radius, 1),
                    "color": tier["color"],
                    "fillOpacity": tier["fillOpacity"],
                    "strokeOpacity": tier["strokeOpacity"],
                    "weight": tier["weight"],
                }
            )
    return zones


def main() -> None:
    if not REF.is_file():
        raise SystemExit(f"Reference image not found: {REF}")

    img = Image.open(REF).convert("RGB")
    w0, h0 = img.size
    scale = min(1.0, MAX_SIDE / max(w0, h0))
    if scale < 1.0:
        img = img.resize((int(w0 * scale), int(h0 * scale)), Image.Resampling.LANCZOS)
    arr = np.asarray(img)
    h, w = arr.shape[:2]

    tier_idx_map = radiation_tier(arr)
    tier_masks = [(tier_idx_map == i).astype(np.uint8) * 255 for i in range(len(TIERS))]

    scattered = _scatter_zones(tier_masks, w, h)
    cnpp = _cnpp_zones()
    zones = _dedupe_zones(scattered + cnpp)

    payload = {
        "zones": zones,
        "legend": [{"color": t["color"], "label": t["label"]} for t in TIERS],
    }

    OUT_ZONES.parent.mkdir(parents=True, exist_ok=True)
    OUT_ZONES.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    main_cfg = {
        "overlay": None,
        "zonesUrl": "/data/pripyat-radiation-zones.json",
        "zones": [],
        "legend": payload["legend"],
    }
    MAIN_JSON.write_text(json.dumps(main_cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    by_tier: dict[str, int] = {}
    for z in zones:
        key = z["id"].split("-")[0]
        by_tier[key] = by_tier.get(key, 0) + 1
    print(f"zones: {len(zones)} ({by_tier})")
    print(f"wrote {OUT_ZONES} ({OUT_ZONES.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
