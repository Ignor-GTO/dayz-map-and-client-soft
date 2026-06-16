"""Extract radiation zones as smooth circles from reference map image.

Usage (from server/):
  python scripts/build_radiation_circles.py
"""

from __future__ import annotations

import colorsys
import json
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
        "fillOpacity": 0.35,
        "strokeOpacity": 0.9,
        "weight": 2,
        "min_r_px": 10,
        "max_r_px": 520,
        "hough_p2": 24,
    },
    {
        "id": "yellow",
        "color": "#cddc39",
        "label": "Средняя",
        "fillOpacity": 0.38,
        "strokeOpacity": 0.92,
        "weight": 2,
        "min_r_px": 8,
        "max_r_px": 320,
        "hough_p2": 25,
    },
    {
        "id": "orange",
        "color": "#ff9800",
        "label": "Высокая",
        "fillOpacity": 0.4,
        "strokeOpacity": 0.95,
        "weight": 2,
        "min_r_px": 6,
        "max_r_px": 240,
        "hough_p2": 24,
    },
    {
        "id": "red",
        "color": "#f44336",
        "label": "Смертельная",
        "fillOpacity": 0.42,
        "strokeOpacity": 1.0,
        "weight": 2,
        "min_r_px": 5,
        "max_r_px": 160,
        "hough_p2": 23,
    },
]

CNPP = {"x": 7310, "y": 15285}
CNPP_EXCLUDE_RADIUS = 3200
CNPP_RINGS = [
    ("green", 5800),
    ("yellow", 3800),
    ("orange", 2200),
    ("red", 950),
]
MAX_SIDE = 3072
MIN_GAME_RADIUS = 250
MAX_GAME_RADIUS = 5800
MIN_RING_COVERAGE = 0.45
CENTER_MERGE_DIST = 280


def radiation_tier(r: int, g: int, b: int) -> int | None:
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    if v < 0.42 or s < 0.55:
        return None
    if h < 0.055 and r > 148 and r > g + 48:
        return 3
    if 0.055 <= h < 0.12 and r > 158 and g < 128:
        return 2
    if 0.12 <= h < 0.19 and r > 152 and g > 98 and b < 88:
        return 1
    if 0.19 <= h < 0.37 and g > 118 and g > r + 28 and b < 118:
        return 0
    return None


def px_to_game(px: float, py: float, w: float, h: float) -> tuple[float, float]:
    gx = px / w * MAP_SIZE
    gy = (1.0 - py / h) * MAP_SIZE
    return gx, gy


def px_radius_to_game(r: float, w: float, h: float) -> float:
    return r * ((MAP_SIZE / w) + (MAP_SIZE / h)) / 2.0


def _circularity(contour: np.ndarray) -> float:
    area = cv2.contourArea(contour)
    perim = cv2.arcLength(contour, True)
    if perim <= 0 or area <= 0:
        return 0.0
    return float(4.0 * np.pi * area / (perim * perim))


def _dedupe_circles(circles: list[tuple[float, float, float]], dist_factor: float = 0.35) -> list[tuple[float, float, float]]:
    circles.sort(key=lambda c: c[2], reverse=True)
    kept: list[tuple[float, float, float]] = []
    for cx, cy, r in circles:
        dup = False
        for kx, ky, kr in kept:
            if abs(cx - kx) < dist_factor * min(r, kr) and abs(cy - ky) < dist_factor * min(r, kr):
                if abs(r - kr) < max(r, kr) * 0.25:
                    dup = True
                    break
        if not dup:
            kept.append((cx, cy, r))
    return kept


def _ring_coverage(raw_mask: np.ndarray, cx: float, cy: float, r: float) -> float:
    if r < 2:
        return 0.0
    hits = 0
    total = 36
    h, w = raw_mask.shape
    for i in range(total):
        ang = 2.0 * np.pi * i / total
        x = int(round(cx + r * np.cos(ang)))
        y = int(round(cy + r * np.sin(ang)))
        if 0 <= x < w and 0 <= y < h and raw_mask[y, x] > 0:
            hits += 1
    return hits / total


def _hough_circles(mask: np.ndarray, tier: dict) -> list[tuple[float, float, float]]:
    blur = cv2.GaussianBlur(mask, (5, 5), 1.4)
    found = cv2.HoughCircles(
        blur,
        cv2.HOUGH_GRADIENT,
        dp=1.4,
        minDist=max(30, tier["min_r_px"] * 2),
        param1=100,
        param2=tier["hough_p2"],
        minRadius=tier["min_r_px"],
        maxRadius=tier["max_r_px"],
    )
    if found is None:
        return []
    out: list[tuple[float, float, float]] = []
    for c in found[0]:
        out.append((float(c[0]), float(c[1]), float(c[2])))
    return out


def _contour_circles(mask: np.ndarray, min_area: float = 120.0) -> list[tuple[float, float, float]]:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out: list[tuple[float, float, float]] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area:
            continue
        if _circularity(contour) < 0.45:
            continue
        (cx, cy), r = cv2.minEnclosingCircle(contour)
        out.append((float(cx), float(cy), float(r)))
    return out


def _dedupe_zones(zones: list[dict]) -> list[dict]:
    import math
    from collections import defaultdict

    by_color: dict[str, list[dict]] = defaultdict(list)
    for z in zones:
        by_color[z["color"]].append(z)

    out: list[dict] = []
    for color, items in by_color.items():
        items.sort(key=lambda z: z["radius"], reverse=True)
        kept: list[dict] = []
        for z in items:
            ok = True
            for k in kept:
                d = math.hypot(z["x"] - k["x"], z["y"] - k["y"])
                if d < CENTER_MERGE_DIST:
                    dr = abs(z["radius"] - k["radius"])
                    if dr < max(z["radius"], k["radius"]) * 0.18:
                        ok = False
                        break
            if ok:
                kept.append(z)
        out.extend(kept)
    return out


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

    tier_masks = [np.zeros((h, w), dtype=np.uint8) for _ in TIERS]
    for y in range(h):
        row = arr[y]
        for x in range(w):
            r, g, b = int(row[x, 0]), int(row[x, 1]), int(row[x, 2])
            tier = radiation_tier(r, g, b)
            if tier is not None:
                tier_masks[tier][y, x] = 255

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    zones: list[dict] = []

    for tier_idx, tier in enumerate(TIERS):
        raw_mask = tier_masks[tier_idx]
        if not raw_mask.any():
            continue
        mask = cv2.dilate(raw_mask, kernel, iterations=1)

        px_circles = _hough_circles(mask, tier)
        px_circles = _dedupe_circles(px_circles, dist_factor=0.45)

        tier_count = 0
        for cx, cy, r_px in px_circles:
            if _ring_coverage(raw_mask, cx, cy, r_px) < MIN_RING_COVERAGE:
                continue
            gx, gy = px_to_game(cx, cy, w, h)
            radius = px_radius_to_game(r_px, w, h)
            if radius < MIN_GAME_RADIUS or radius > MAX_GAME_RADIUS:
                continue
            tier_count += 1
            zones.append(
                {
                    "id": f"{tier['id']}-{tier_count}",
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

    zones = _dedupe_zones(zones)

    import math

    zones = [
        z
        for z in zones
        if math.hypot(z["x"] - CNPP["x"], z["y"] - CNPP["y"]) > CNPP_EXCLUDE_RADIUS
    ]
    for tier_id, radius in CNPP_RINGS:
        tier = next(t for t in TIERS if t["id"] == tier_id)
        zones.append(
            {
                "id": f"cnpp-{tier_id}",
                "label": tier["label"],
                "x": float(CNPP["x"]),
                "y": float(CNPP["y"]),
                "radius": float(radius),
                "color": tier["color"],
                "fillOpacity": tier["fillOpacity"],
                "strokeOpacity": tier["strokeOpacity"],
                "weight": tier["weight"],
            }
        )

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

    print(f"zones: {len(zones)}")
    print(f"wrote {OUT_ZONES} ({OUT_ZONES.stat().st_size // 1024} KB)")
    print(f"updated {MAIN_JSON}")


if __name__ == "__main__":
    main()
