"""Bundled offline OCR fallback when Windows OCR language packs are missing."""

from __future__ import annotations

import logging

import numpy as np
from PIL import Image, ImageEnhance, ImageOps

_engine = None
_log = logging.getLogger(__name__)


def preprocess_coordinate_region(image: Image.Image) -> Image.Image:
    """Upscale and boost contrast — helps small in-game coordinate text."""
    gray = image.convert("L")
    gray = ImageOps.autocontrast(gray, cutoff=2)
    w, h = gray.size
    scale = max(2, min(4, 140 // max(h, 1)))
    if scale > 1:
        gray = gray.resize((w * scale, h * scale), Image.Resampling.LANCZOS)
    gray = ImageEnhance.Contrast(gray).enhance(1.6)
    return gray.convert("RGB")


def _get_engine():
    global _engine
    if _engine is None:
        logging.getLogger("rapidocr").setLevel(logging.WARNING)
        from rapidocr import RapidOCR

        _engine = RapidOCR()
    return _engine


def recognize_text(image: Image.Image) -> str:
    engine = _get_engine()
    arr = np.asarray(image.convert("RGB"))
    result = engine(arr)
    if result is None:
        return ""
    txts = getattr(result, "txts", None)
    if not txts:
        return ""
    return " ".join(str(t) for t in txts if t)
