"""Build radiation zone circles for the web map.

Primary source: pripyat-radiation-circles-src.json — circle centers/radii
digitized from the reference radiation map image (1000×1000 logical coords).

Optional: auto-extract from pripyat-radiation-ref.png when --auto is passed.

Usage (from server/):
  python scripts/build_radiation_circles.py
  python scripts/build_radiation_circles.py --auto
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

MAP_SIZE = 20480
DATA_DIR = Path(__file__).resolve().parent.parent / "static/data"
SRC_CIRCLES = DATA_DIR / "pripyat-radiation-circles-src.json"
REF = DATA_DIR / "pripyat-radiation-ref.png"
REF_FALLBACK = DATA_DIR / "pripyat-radiation-ref.jpg"
OUT_ZONES = DATA_DIR / "pripyat-radiation-zones.json"
MAIN_JSON = DATA_DIR / "pripyat-radiation.json"

TIERS = {
    "green": {
        "color": "#4caf50",
        "label": "250 мЗв/ч",
        "fillOpacity": 0.34,
        "strokeOpacity": 0.9,
        "weight": 2,
    },
    "yellow": {
        "color": "#cddc39",
        "label": "280 мЗв/ч",
        "fillOpacity": 0.36,
        "strokeOpacity": 0.92,
        "weight": 2,
    },
    "orange": {
        "color": "#ff9800",
        "label": "350 мЗв/ч",
        "fillOpacity": 0.38,
        "strokeOpacity": 0.94,
        "weight": 2,
    },
    "red": {
        "color": "#f44336",
        "label": "530 мЗв/ч",
        "fillOpacity": 0.4,
        "strokeOpacity": 0.96,
        "weight": 2,
    },
}

REF_RGB = {
    "green": np.array([63, 99, 25], dtype=np.float32),
    "yellow": np.array([98, 95, 46], dtype=np.float32),
    "orange": np.array([122, 85, 21], dtype=np.float32),
    "red": np.array([89, 54, 41], dtype=np.float32),
}


def ref_to_game(px: float, py: float, r: float, ref_size: float = 1000.0) -> tuple[float, float, float]:
    gx = px / ref_size * MAP_SIZE
    gy = (1.0 - py / ref_size) * MAP_SIZE
    gr = r / ref_size * MAP_SIZE
    return gx, gy, gr


def _zones_from_src() -> list[dict]:
    data = json.loads(SRC_CIRCLES.read_text(encoding="utf-8"))
    ref_size = float(data.get("refSize", 1000))
    counts: dict[str, int] = {k: 0 for k in TIERS}
    zones: list[dict] = []
    for item in data.get("circles", []):
        tier_id = str(item["tier"])
        tier = TIERS.get(tier_id)
        if not tier:
            continue
        gx, gy, gr = ref_to_game(float(item["x"]), float(item["y"]), float(item["r"]), ref_size)
        counts[tier_id] += 1
        zones.append(
            {
                "id": f"{tier_id}-{counts[tier_id]}",
                "label": tier["label"],
                "x": round(gx, 1),
                "y": round(gy, 1),
                "radius": round(gr, 1),
                "color": tier["color"],
                "fillOpacity": tier["fillOpacity"],
                "strokeOpacity": tier["strokeOpacity"],
                "weight": tier["weight"],
            }
        )
    return zones


def _auto_from_image() -> list[dict]:
    """Best-effort auto extract — prefer hand-tuned SRC file for production."""
    ref_path = REF if REF.is_file() else REF_FALLBACK
    if not ref_path.is_file():
        raise SystemExit(f"Reference image not found: {REF}")

    img = Image.open(ref_path).convert("RGB")
    arr = np.asarray(img)
    h0, _ = arr.shape[:2]
    y0 = int(h0 * 0.085)
    arr = arr[y0:, :]
    h, w = arr.shape[:2]

    rgb = arr.astype(np.float32)
    dist = {tid: np.linalg.norm(rgb - REF_RGB[tid], axis=2) for tid in TIERS}
    stack = np.stack(list(dist.values()), axis=2)
    best_idx = np.argmin(stack, axis=2)
    best_dist = np.min(stack, axis=2)
    mask = (best_dist < 48.0).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)), 1)

    counts: dict[str, int] = {k: 0 for k in TIERS}
    zones: list[dict] = []
    tier_ids = list(TIERS.keys())
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 80:
            continue
        M = cv2.moments(contour)
        if M["m00"] <= 0:
            continue
        cx = M["m10"] / M["m00"]
        cy = M["m01"] / M["m00"]
        (_, _), r_enc = cv2.minEnclosingCircle(contour)
        r_px = r_enc * 0.6 + math.sqrt(area / math.pi) * 0.4
        gx = cx / w * MAP_SIZE
        gy = (1.0 - cy / h) * MAP_SIZE
        gr = r_px * ((MAP_SIZE / w) + (MAP_SIZE / h)) / 2.0
        if gr < 120 or gr > 3500:
            continue
        tier_id = tier_ids[int(best_idx[int(cy), int(cx)])]
        tier = TIERS[tier_id]
        counts[tier_id] += 1
        zones.append(
            {
                "id": f"{tier_id}-{counts[tier_id]}",
                "label": tier["label"],
                "x": round(gx, 1),
                "y": round(gy, 1),
                "radius": round(gr, 1),
                "color": tier["color"],
                "fillOpacity": tier["fillOpacity"],
                "strokeOpacity": tier["strokeOpacity"],
                "weight": tier["weight"],
            }
        )
    return zones


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--auto", action="store_true", help="Auto-detect from reference PNG (experimental)")
    args = parser.parse_args()

    if args.auto:
        zones = _auto_from_image()
        source = "auto"
    else:
        if not SRC_CIRCLES.is_file():
            raise SystemExit(f"Source circles file not found: {SRC_CIRCLES}")
        zones = _zones_from_src()
        source = SRC_CIRCLES.name

    payload = {
        "zones": zones,
        "legend": [{"color": t["color"], "label": t["label"]} for t in TIERS.values()],
    }

    OUT_ZONES.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    MAIN_JSON.write_text(
        json.dumps(
            {
                "overlay": None,
                "zonesUrl": "/data/pripyat-radiation-zones.json",
                "zones": [],
                "legend": payload["legend"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    by_tier: dict[str, int] = {}
    for z in zones:
        key = z["id"].split("-")[0]
        by_tier[key] = by_tier.get(key, 0) + 1
    print(f"source: {source}")
    print(f"zones: {len(zones)} ({by_tier})")
    print(f"wrote {OUT_ZONES}")


if __name__ == "__main__":
    main()
