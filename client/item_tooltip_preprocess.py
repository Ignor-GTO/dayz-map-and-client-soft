"""Preprocess inventory tooltip title strip for OCR."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageEnhance, ImageOps


def _upscale(gray: Image.Image) -> Image.Image:
    gray = ImageOps.expand(gray, border=6, fill=0)
    w, h = gray.size
    scale = max(3, min(5, 180 // max(h, 1)))
    if scale > 1:
        gray = gray.resize((w * scale, h * scale), Image.Resampling.LANCZOS)
    return ImageEnhance.Contrast(gray).enhance(1.4).convert("RGB")


def preprocess_tooltip_orange(image: Image.Image) -> Image.Image:
    """Orange/yellow item title on dark tooltip panel."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    orange = (red > 120) & (green > 70) & (blue < 130) & (red >= blue * 1.05)
    bright = (red > 185) & (green > 185) & (blue > 185)
    mask = orange | bright
    binary = np.where(mask, 255, 0).astype(np.uint8)
    gray = Image.fromarray(binary, mode="L")
    gray = ImageOps.autocontrast(gray, cutoff=1)
    gray = ImageOps.invert(gray)
    return _upscale(gray)


def preprocess_tooltip_high_contrast(image: Image.Image) -> Image.Image:
    gray = ImageOps.autocontrast(image.convert("L"), cutoff=2)
    if float(np.asarray(gray).mean()) < 120:
        gray = ImageOps.invert(gray)
    return _upscale(gray)


def preprocess_tooltip_color_boost(image: Image.Image) -> Image.Image:
    """Keep orange/yellow title pixels on black background for Windows OCR."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    orange = (red > 100) & (green > 50) & (blue < 150) & (red >= blue)
    yellow = (red > 165) & (green > 140) & (blue < 180)
    mask = orange | yellow
    binary = np.where(mask, 255, 0).astype(np.uint8)
    gray = Image.fromarray(binary, mode="L")
    return _upscale(gray)


def preprocess_tooltip_variants(image: Image.Image) -> list[Image.Image]:
    return [
        preprocess_tooltip_color_boost(image),
        preprocess_tooltip_orange(image),
        preprocess_tooltip_high_contrast(image),
        _upscale(ImageOps.autocontrast(image.convert("L"), cutoff=1)),
    ]
