"""Read item name from inventory tooltip near cursor."""

from __future__ import annotations

import re
from typing import Callable

from PIL import Image

from capture import grab_region
from item_tooltip_locator import find_tooltip_region
from item_tooltip_preprocess import preprocess_tooltip_variants


_SKIP_LINE_RE = re.compile(
    r"(нетронуто|поврежден|изношен|испорчен|кг|шт\.?|меньше|около|\d+\s*/\s*\d+)",
    re.IGNORECASE,
)
_DESC_LINE_RE = re.compile(
    r"^[A-Za-zäöüßÄÖÜ][A-Za-zäöüßÄÖÜ\s,\.\-]{35,}$",
)


def _line_score(line: str) -> tuple[int, int, int]:
    cyr = len(re.findall(r"[А-Яа-яЁё]", line))
    latin = len(re.findall(r"[A-Za-z]", line))
    return (cyr, -len(line), -latin)


def _recognize_general(prepared: Image.Image) -> str:
    from ocr_engine import _recognize_prepared, ensure_ocr_backend, recognize_text_fallback, _use_windows

    ensure_ocr_backend()
    if _use_windows:
        try:
            text = _recognize_prepared(prepared).strip()
            if text:
                return text
        except Exception:
            pass
    try:
        return recognize_text_fallback(prepared).strip()
    except Exception:
        return ""


def recognize_tooltip_text(image: Image.Image) -> str:
    for prepared in preprocess_tooltip_variants(image):
        text = _recognize_general(prepared)
        if text.strip():
            return text.strip()
    return ""


def extract_item_name(ocr_text: str) -> str | None:
    lines = [ln.strip() for ln in ocr_text.replace("\r", "\n").split("\n") if ln.strip()]
    candidates: list[str] = []
    for line in lines:
        if len(line) < 2 or len(line) > 72:
            continue
        if _SKIP_LINE_RE.search(line):
            continue
        if _DESC_LINE_RE.match(line):
            continue
        if not re.search(r"[\wА-Яа-яЁё]", line):
            continue
        candidates.append(line)
    if not candidates:
        return lines[0] if lines else None
    candidates.sort(key=_line_score, reverse=True)
    return candidates[0]


def read_item_name_at_cursor(
    cfg: dict,
    *,
    on_search: Callable[[str], None] | None = None,
) -> str | None:
    region, method = find_tooltip_region(cfg)
    if region is None:
        if on_search:
            on_search("hint")
        return None

    image = grab_region(int(cfg.get("monitor_index", 1)), region)
    if image is None:
        return None
    text = recognize_tooltip_text(image)
    return extract_item_name(text)
