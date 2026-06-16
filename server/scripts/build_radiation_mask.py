"""Build transparent radiation mask PNG from reference map image.

Usage (from server/):
  python scripts/build_radiation_mask.py
"""

from __future__ import annotations

import colorsys
from pathlib import Path

import numpy as np
from PIL import Image

MAP_SIZE = 20480
REF = Path(__file__).resolve().parent.parent / "static/data/pripyat-radiation-ref.jpg"
OUT = Path(__file__).resolve().parent.parent / "static/data/pripyat-radiation-mask.png"
OUT_SMALL = Path(__file__).resolve().parent.parent / "static/data/pripyat-radiation-mask.webp"


def is_radiation_pixel(r: int, g: int, b: int) -> bool:
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    if v < 0.40 or s < 0.52:
        return False
    # Red / deep orange (hot zones)
    if h < 0.055 and r > 145 and r > g + 45:
        return True
    if 0.055 <= h < 0.12 and r > 155 and g < 130:
        return True
    # Yellow / amber rings
    if 0.12 <= h < 0.19 and r > 150 and g > 95 and b < 90:
        return True
    # Lime / yellow-green radiation rings (not terrain)
    if 0.19 <= h < 0.38 and g > 115 and g > r + 25 and b < 120:
        return True
    return False


def main() -> None:
    if not REF.is_file():
        raise SystemExit(f"Reference image not found: {REF}")

    img = Image.open(REF).convert("RGB")
    arr = np.asarray(img)
    h, w = arr.shape[:2]

    mask = np.zeros((h, w), dtype=bool)
    for y in range(h):
        row = arr[y]
        for x in range(w):
            r, g, b = int(row[x, 0]), int(row[x, 1]), int(row[x, 2])
            if is_radiation_pixel(r, g, b):
                mask[y, x] = True

    # Slight dilation so thin ring lines stay visible when scaled
    try:
        from scipy import ndimage

        mask = ndimage.binary_dilation(mask, iterations=1)
    except ImportError:
        pass

    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., :3] = arr
    rgba[..., 3] = np.where(mask, 210, 0)

    out = Image.fromarray(rgba, "RGBA")
    # Downscale for web — keeps alignment via bounds 0..20480
    max_side = 4096
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        out = out.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.save(OUT, optimize=True)
    out.save(OUT_SMALL, format="WEBP", quality=88)
    covered = int(mask.sum())
    print(f"mask pixels: {covered} / {w*h} ({100*covered/(w*h):.1f}%)")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
    print(f"wrote {OUT_SMALL} ({OUT_SMALL.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
