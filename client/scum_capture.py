"""Capture SCUM `show position` HUD via screen OCR."""

from __future__ import annotations

from typing import Sequence

import mss
from PIL import Image

from scum_coords import parse_scum_clipboard

# Default: top-left band where F1 show position usually appears.
DEFAULT_SCUM_OCR_REGION = (0, 0, 900, 280)


def normalize_region(region: Sequence[int] | None) -> tuple[int, int, int, int]:
    if not region or len(region) < 4:
        return DEFAULT_SCUM_OCR_REGION
    left, top, right, bottom = (int(region[0]), int(region[1]), int(region[2]), int(region[3]))
    if right <= left or bottom <= top:
        return DEFAULT_SCUM_OCR_REGION
    return left, top, right, bottom


def grab_region_image(region: Sequence[int] | None = None) -> Image.Image:
    left, top, right, bottom = normalize_region(region)
    with mss.mss() as sct:
        shot = sct.grab({"left": left, "top": top, "width": right - left, "height": bottom - top})
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def ocr_scum_coords(region: Sequence[int] | None = None) -> tuple[tuple[float, float] | None, str]:
    """Return ((x, y) or None, raw OCR text)."""
    image = grab_region_image(region)
    from ocr_engine import recognize_general_text

    raw = recognize_general_text(image) or ""
    # OCR often inserts spaces: "X = 123" already handled by regex.
    coords = parse_scum_clipboard(raw)
    if coords:
        return coords, raw
    # Retry on a lightly contrasted variant
    from ocr_engine import recognize_text

    raw2 = recognize_text(image) or ""
    coords = parse_scum_clipboard(raw2)
    return coords, raw2 or raw
