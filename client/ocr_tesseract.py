"""Fast digit-only OCR via Tesseract (optional external install)."""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image

_TESS_CMD: str | None = None
_CHECKED = False

_DEFAULT_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)

# Digits and coordinate separators only — no letters.
_TESS_CONFIG = "--oem 1 --psm 7 -c tessedit_char_whitelist=0123456789-/–— "


def tesseract_cmd() -> str | None:
    global _TESS_CMD, _CHECKED
    if _CHECKED:
        return _TESS_CMD
    _CHECKED = True
    for path in _DEFAULT_PATHS:
        if Path(path).is_file():
            _TESS_CMD = path
            return _TESS_CMD
    found = shutil.which("tesseract")
    if found:
        _TESS_CMD = found
    return _TESS_CMD


def is_available() -> bool:
    return tesseract_cmd() is not None


def recognize_digits(image: Image.Image) -> str:
    import pytesseract

    cmd = tesseract_cmd()
    if not cmd:
        return ""
    pytesseract.pytesseract.tesseract_cmd = cmd
    gray = image.convert("L")
    return pytesseract.image_to_string(gray, config=_TESS_CONFIG).strip()
