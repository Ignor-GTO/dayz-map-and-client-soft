"""Read item name from inventory tooltip near cursor."""

from __future__ import annotations

import re

from PIL import Image

from capture import grab_region, resolve_monitor
from item_tooltip_preprocess import preprocess_tooltip_variants
from mouse_util import get_cursor_pos


_SKIP_LINE_RE = re.compile(
    r"(нетронуто|поврежден|изношен|испорчен|кг|шт\.?|меньше|около|\d+\s*/\s*\d+)",
    re.IGNORECASE,
)


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
    for line in lines:
        if _SKIP_LINE_RE.search(line):
            continue
        if len(line) >= 2 and re.search(r"[\wА-Яа-яЁё]", line):
            return line
    return lines[0] if lines else None


def grab_tooltip_near_cursor(
    monitor_index: int,
    *,
    dx: int = 24,
    dy: int = -90,
    width: int = 420,
    height: int = 72,
) -> Image.Image | None:
    mon = resolve_monitor(monitor_index)
    if not mon:
        return None
    cx, cy = get_cursor_pos()
    lx = cx - mon.left
    ly = cy - mon.top
    left = max(0, lx + dx)
    top = max(0, ly + dy)
    right = min(mon.width, left + max(40, width))
    bottom = min(mon.height, top + max(24, height))
    if right <= left + 8 or bottom <= top + 8:
        return None
    return grab_region(monitor_index, (left, top, right, bottom))


def read_item_name_at_cursor(cfg: dict) -> str | None:
    capture = cfg.get("item_tooltip_capture") or {}
    image = grab_tooltip_near_cursor(
        int(cfg.get("monitor_index", 1)),
        dx=int(capture.get("dx", 24)),
        dy=int(capture.get("dy", -90)),
        width=int(capture.get("w", 420)),
        height=int(capture.get("h", 72)),
    )
    if image is None:
        return None
    text = recognize_tooltip_text(image)
    return extract_item_name(text)
