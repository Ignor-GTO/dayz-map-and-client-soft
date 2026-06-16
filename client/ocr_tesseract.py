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

_TESS_CONFIGS = (
    "--oem 1 --psm 7 -c tessedit_char_whitelist=0123456789-/–— ",
    "--oem 1 --psm 13 -c tessedit_char_whitelist=0123456789-/–— ",
    "--oem 1 --psm 6 -c tessedit_char_whitelist=0123456789-/–— ",
)


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


def recognize_digits_all(image: Image.Image) -> list[str]:
    import pytesseract

    cmd = tesseract_cmd()
    if not cmd:
        return []
    pytesseract.pytesseract.tesseract_cmd = cmd
    gray = image.convert("L")
    seen: set[str] = set()
    out: list[str] = []
    for cfg in _TESS_CONFIGS:
        text = pytesseract.image_to_string(gray, config=cfg).strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def recognize_digits(image: Image.Image) -> str:
    parts = recognize_digits_all(image)
    return parts[0] if parts else ""
