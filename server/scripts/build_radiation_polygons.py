"""Extract radiation zones as vector polygons from reference map image.

Usage (from server/):
  python scripts/build_radiation_polygons.py
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
OUT_JSON = Path(__file__).resolve().parent.parent / "static/data/pripyat-radiation-polygons.json"
MAIN_JSON = Path(__file__).resolve().parent.parent / "static/data/pripyat-radiation.json"

TIERS = [
    {
        "id": "green",
        "color": "#4caf50",
        "label": "Слабая радиация",
        "fillOpacity": 0.38,
        "weight": 2,
        "strokeOpacity": 0.95,
    },
    {
        "id": "yellow",
        "color": "#cddc39",
        "label": "Средняя",
        "fillOpacity": 0.42,
        "weight": 2,
        "strokeOpacity": 0.95,
    },
    {
        "id": "orange",
        "color": "#ff9800",
        "label": "Высокая",
        "fillOpacity": 0.46,
        "weight": 2,
        "strokeOpacity": 0.95,
    },
    {
        "id": "red",
        "color": "#f44336",
        "label": "Смертельная",
        "fillOpacity": 0.5,
        "weight": 2,
        "strokeOpacity": 1.0,
    },
]

MAX_SIDE = 2048
MIN_AREA = 180
DILATE_ITERS = 4
SIMPLIFY_EPS = 2.2


def radiation_tier(r: int, g: int, b: int) -> int | None:
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    if v < 0.40 or s < 0.52:
        return None
    if h < 0.055 and r > 145 and r > g + 45:
        return 3
    if 0.055 <= h < 0.12 and r > 155 and g < 130:
        return 2
    if 0.12 <= h < 0.19 and r > 150 and g > 95 and b < 90:
        return 1
    if 0.19 <= h < 0.38 and g > 115 and g > r + 25 and b < 120:
        return 0
    return None


def px_to_game(px: float, py: float, w: float, h: float) -> tuple[float, float]:
    gx = px / w * MAP_SIZE
    gy = (1.0 - py / h) * MAP_SIZE
    return round(gx, 1), round(gy, 1)


def simplify_ring(points: np.ndarray, epsilon: float) -> np.ndarray:
    if len(points) < 4:
        return points
    contour = points.reshape(-1, 1, 2).astype(np.float32)
    approx = cv2.approxPolyDP(contour, epsilon, True)
    return approx.reshape(-1, 2)


def ring_to_game(points: np.ndarray, w: float, h: float) -> list[list[float]]:
    return [[float(gx), float(gy)] for px, py in points for gx, gy in [px_to_game(float(px), float(py), w, h)]]


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

    polygons: list[dict] = []
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    for tier_idx, tier in enumerate(TIERS):
        mask = tier_masks[tier_idx]
        if not mask.any():
            continue
        mask = cv2.dilate(mask, kernel, iterations=DILATE_ITERS)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
        if hierarchy is None:
            continue

        hierarchy = hierarchy[0]
        for i, contour in enumerate(contours):
            area = cv2.contourArea(contour)
            if area < MIN_AREA:
                continue
            if hierarchy[i][3] != -1:
                continue

            rings: list[list[list[float]]] = []
            outer = simplify_ring(contour[:, 0, :], SIMPLIFY_EPS)
            if len(outer) < 3:
                continue
            rings.append(ring_to_game(outer, w, h))

            child = hierarchy[i][2]
            while child != -1:
                hole = contours[child]
                if cv2.contourArea(hole) >= MIN_AREA / 2:
                    inner = simplify_ring(hole[:, 0, :], SIMPLIFY_EPS)
                    if len(inner) >= 3:
                        rings.append(ring_to_game(inner, w, h))
                child = hierarchy[child][0]

            polygons.append(
                {
                    "id": f"{tier['id']}-{len(polygons) + 1}",
                    "tier": tier["id"],
                    "label": tier["label"],
                    "color": tier["color"],
                    "fillOpacity": tier["fillOpacity"],
                    "strokeOpacity": tier["strokeOpacity"],
                    "weight": tier["weight"],
                    "rings": rings,
                }
            )

    payload = {
        "polygons": polygons,
        "legend": [{"color": t["color"], "label": t["label"]} for t in TIERS],
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    size_kb = OUT_JSON.stat().st_size // 1024

    main_cfg = {
        "overlay": None,
        "polygonsUrl": "/data/pripyat-radiation-polygons.json",
        "zones": [],
        "legend": payload["legend"],
    }
    MAIN_JSON.write_text(json.dumps(main_cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"polygons: {len(polygons)}")
    print(f"wrote {OUT_JSON} ({size_kb} KB)")
    print(f"updated {MAIN_JSON}")


if __name__ == "__main__":
    main()
