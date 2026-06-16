"""Image preprocessing for iZurvive / DayZ coordinate strip."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageEnhance, ImageOps

# Bottom-left coord strip on 1920x1080 — wide enough for "15100 / 879" (white or lime).
IZURVIVE_OCR_REGION = (130, 888, 500, 970)
IZURVIVE_OCR_REGION_FULL = (8, 896, 300, 962)


def _upscale(gray: Image.Image) -> Image.Image:
    from PIL import ImageOps

    gray = ImageOps.expand(gray, border=8, fill=0)
    width, height = gray.size
    scale = max(4, min(7, 220 // max(height, 1)))
    if scale > 1:
        gray = gray.resize((width * scale, height * scale), Image.Resampling.LANCZOS)
    return ImageEnhance.Contrast(gray).enhance(1.5).convert("RGB")


def preprocess_lime_on_dark(image: Image.Image) -> Image.Image:
    """Lime/yellow-green digits on dark panel (iZurvive browser)."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    signal = np.maximum(green, red * 0.92) - blue * 0.88
    signal = np.clip(signal, 0, 255)
    if float(signal.max()) < 8:
        gray = image.convert("L")
    else:
        thresh = max(32.0, float(np.percentile(signal, 70)) * 0.55)
        binary = np.where(signal > thresh, 255, 0).astype(np.uint8)
        gray = Image.fromarray(binary, mode="L")
    gray = ImageOps.autocontrast(gray, cutoff=1)
    return _upscale(gray)


def preprocess_white_on_dark(image: Image.Image) -> Image.Image:
    """White/gray digits on dark background (in-game map overlay)."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    lum = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    p75, p92 = float(np.percentile(lum, 75)), float(np.percentile(lum, 92))
    thresh = max(135.0, p75 + (p92 - p75) * 0.45)
    bright = (lum >= thresh) & (lum > p75 + 18)
    binary = np.where(bright, 255, 0).astype(np.uint8)
    gray = Image.fromarray(binary, mode="L")
    gray = ImageOps.autocontrast(gray, cutoff=1)
    # Tesseract reads dark glyphs on light paper better.
    gray = ImageOps.invert(gray)
    return _upscale(gray)


def preprocess_high_contrast(image: Image.Image) -> Image.Image:
    """Fallback: autocontrast + invert if mostly dark."""
    gray = ImageOps.autocontrast(image.convert("L"), cutoff=2)
    if float(np.asarray(gray).mean()) < 110:
        gray = ImageOps.invert(gray)
    return _upscale(gray)


def preprocess_coordinate_region(image: Image.Image) -> Image.Image:
    """Default single variant (lime-first for backward compat)."""
    return preprocess_lime_on_dark(image)


def preprocess_variants(image: Image.Image) -> list[Image.Image]:
    """Try multiple preprocess paths — lime browser UI, white in-game UI, fallback."""
    return [
        preprocess_white_on_dark(image),
        preprocess_lime_on_dark(image),
        preprocess_high_contrast(image),
    ]
