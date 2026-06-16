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

TIER_EXTRACT_PARAMS: dict[str, tuple[int, int, int, int]] = {
    "orange": (30, 120, 8, 70),
    "yellow": (34, 50, 10, 80),
    "green": (42, 50, 12, 90),
}

# Hand-tuned red zones (auto-detect picks terrain noise for red).
RED_CIRCLES_SRC = [
    {"tier": "red", "x": 345, "y": 275, "r": 60},
    {"tier": "red", "x": 375, "y": 380, "r": 30},
    {"tier": "red", "x": 930, "y": 125, "r": 25},
]

LEGEND_CROP_RATIO = 0.085
EXPECTED_COUNTS = {"red": 3, "orange": 11, "yellow": 22, "green": 28}


REF_RGB = {
    "green": np.array([63, 99, 25], dtype=np.float32),
    "yellow": np.array([98, 95, 46], dtype=np.float32),
    "orange": np.array([122, 85, 21], dtype=np.float32),
    "red": np.array([89, 54, 41], dtype=np.float32),
}


def _load_ref_array() -> tuple[np.ndarray, int, int]:
    ref_path = REF if REF.is_file() else REF_FALLBACK
    if not ref_path.is_file():
        raise SystemExit(f"Reference image not found: {REF}")
    img = Image.open(ref_path).convert("RGB")
    arr = np.asarray(img)
    h0, _ = arr.shape[:2]
    y0 = int(h0 * LEGEND_CROP_RATIO)
    arr = arr[y0:, :]
    h, w = arr.shape[:2]
    return arr, w, h


def _extract_tier_circles(arr: np.ndarray, w: int, h: int, tier: str) -> list[dict]:
    if tier not in TIER_EXTRACT_PARAMS:
        return []
    max_dist, min_area, min_r, max_r = TIER_EXTRACT_PARAMS[tier]
    rgb = arr.astype(np.float32)
    self_d = np.linalg.norm(rgb - REF_RGB[tier], axis=2)
    others = np.min(
        np.stack([np.linalg.norm(rgb - REF_RGB[tid], axis=2) for tid in REF_RGB if tid != tier], axis=0),
        axis=0,
    )
    mask = ((self_d < max_dist) & (self_d + 6 < others)).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)

    circles: list[dict] = []
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        if cv2.contourArea(contour) < min_area:
            continue
        (cx, cy), r_enc = cv2.minEnclosingCircle(contour)
        x = cx / w * 1000.0
        y = cy / h * 1000.0
        r = r_enc / w * 1000.0
        if r < min_r or r > max_r:
            continue
        circles.append({"tier": tier, "x": round(x, 1), "y": round(y, 1), "r": round(r, 1)})
    return circles


def _extract_all_circles() -> list[dict]:
    arr, w, h = _load_ref_array()
    circles = list(RED_CIRCLES_SRC)
    for tier in ("orange", "yellow", "green"):
        circles.extend(_extract_tier_circles(arr, w, h, tier))
    return circles


def ref_to_game(px: float, py: float, r: float, ref_size: float = 1000.0) -> tuple[float, float, float]:
    gx = px / ref_size * MAP_SIZE
    gy = (1.0 - py / ref_size) * MAP_SIZE
    gr = r / ref_size * MAP_SIZE
    return gx, gy, gr


def _zones_from_src() -> list[dict]:
    data = json.loads(SRC_CIRCLES.read_text(encoding="utf-8"))
    return _zones_from_circles(data.get("circles", []), float(data.get("refSize", 1000)))


def _zones_from_circles(circles: list[dict], ref_size: float = 1000.0) -> list[dict]:
    counts: dict[str, int] = {k: 0 for k in TIERS}
    zones: list[dict] = []
    for item in circles:
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


def _validate_counts(circles: list[dict]) -> None:
    from collections import Counter

    got = Counter(str(c["tier"]) for c in circles)
    for tier, want in EXPECTED_COUNTS.items():
        if got.get(tier, 0) != want:
            raise SystemExit(f"Circle count mismatch for {tier}: got {got.get(tier, 0)}, want {want}")
    if sum(EXPECTED_COUNTS.values()) != len(circles):
        raise SystemExit(f"Total circles {len(circles)} != {sum(EXPECTED_COUNTS.values())}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--auto", action="store_true", help="Re-extract circles from reference PNG")
    args = parser.parse_args()

    if args.auto or not SRC_CIRCLES.is_file():
        circles = _extract_all_circles()
        _validate_counts(circles)
        SRC_CIRCLES.write_text(
            json.dumps({"refSize": 1000, "circles": circles}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        zones = _zones_from_circles(circles)
        source = f"extracted -> {SRC_CIRCLES.name}"
    else:
        zones = _zones_from_src()
        _validate_counts(json.loads(SRC_CIRCLES.read_text(encoding="utf-8")).get("circles", []))
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
