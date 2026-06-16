"""Bundled offline OCR fallback when Windows OCR language packs are missing."""

from __future__ import annotations

import logging

import numpy as np
from PIL import Image

from ocr_preprocess import preprocess_coordinate_region

_engine = None


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
