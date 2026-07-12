"""Read item name from inventory tooltip near cursor."""

from __future__ import annotations

import re
from typing import Callable

from PIL import Image, ImageEnhance

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
_GARBAGE_LINE_RE = re.compile(r"^[\d\W_]+$")
_LATIN_CONFUSABLES = str.maketrans(
    {
        "A": "А",
        "B": "В",
        "C": "С",
        "E": "Е",
        "H": "Н",
        "K": "К",
        "M": "М",
        "O": "О",
        "P": "Р",
        "T": "Т",
        "X": "Х",
        "Y": "У",
        "a": "а",
        "c": "с",
        "e": "е",
        "o": "о",
        "p": "р",
        "x": "х",
        "y": "у",
    }
)


def _line_score(line: str) -> tuple[int, int, int]:
    cyr = len(re.findall(r"[А-Яа-яЁё]", line))
    latin = len(re.findall(r"[A-Za-z]", line))
    alnum = len(re.findall(r"[\wА-Яа-яЁё]", line))
    return (cyr, alnum, -latin)


def _upscale_raw(image: Image.Image) -> Image.Image:
    rgb = image.convert("RGB")
    w, h = rgb.size
    scale = max(3, min(4, 220 // max(h, 1)))
    if scale > 1:
        rgb = rgb.resize((w * scale, h * scale), Image.Resampling.LANCZOS)
    return ImageEnhance.Contrast(rgb).enhance(1.12)


def _recognize_tooltip_variant(prepared: Image.Image) -> str:
    from ocr_engine import recognize_general_text

    return recognize_general_text(prepared).strip()


def recognize_tooltip_text(image: Image.Image) -> str:
    seen: set[str] = set()
    names: list[str] = []

    for prepared in [_upscale_raw(image), *preprocess_tooltip_variants(image)]:
        text = _recognize_tooltip_variant(prepared)
        if not text or text in seen:
            continue
        seen.add(text)
        name = extract_item_name(text)
        if name:
            names.append(name)

    best = pick_best_name(names)
    return best or ""


def normalize_item_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(name or "").strip())
    return cleaned.translate(_LATIN_CONFUSABLES)


def is_valid_item_name(name: str | None) -> bool:
    if not name:
        return False
    line = re.sub(r"\s+", " ", name.strip())
    if len(line) < 2 or len(line) > 72:
        return False
    if _GARBAGE_LINE_RE.match(line):
        return False
    if re.fullmatch(r"\d+", line.replace(" ", "")):
        return False
    if re.fullmatch(r"[A-Za-zА-Яа-яЁё]", line):
        return False
    if _SKIP_LINE_RE.search(line):
        return False
    if _DESC_LINE_RE.match(line):
        return False
    return bool(re.search(r"[\wА-Яа-яЁё]", line))


def extract_item_name(ocr_text: str) -> str | None:
    lines = [ln.strip() for ln in ocr_text.replace("\r", "\n").split("\n") if ln.strip()]
    candidates: list[str] = []
    for line in lines:
        cleaned = normalize_item_name(line)
        if not is_valid_item_name(cleaned):
            continue
        candidates.append(cleaned)
    if not candidates:
        return None
    candidates.sort(key=_line_score, reverse=True)
    return candidates[0]


def pick_best_name(names: list[str]) -> str | None:
    valid = [normalize_item_name(n) for n in names if is_valid_item_name(normalize_item_name(n))]
    if not valid:
        return None
    valid.sort(key=_line_score, reverse=True)
    return valid[0]


def read_item_name_at_cursor(
    cfg: dict,
    *,
    on_search: Callable[[str], None] | None = None,
) -> str | None:
    region, _method = find_tooltip_region(cfg)
    if region is None:
        if on_search:
            on_search("hint")
        return None

    image = grab_region(int(cfg.get("monitor_index", 1)), region)
    if image is None:
        return None
    name = recognize_tooltip_text(image)
    if not is_valid_item_name(name):
        return None
    return normalize_item_name(name or "")
