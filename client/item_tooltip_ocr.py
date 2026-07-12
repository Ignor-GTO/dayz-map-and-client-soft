"""Read item name from inventory tooltip near cursor."""

from __future__ import annotations

import re
from typing import Callable

from PIL import Image, ImageEnhance

from item_tooltip_locator import SearchArea, find_title_regions_in_search, grab_tooltip_search_area
from item_tooltip_preprocess import preprocess_tooltip_variants


_HUD_GARBAGE_RE = re.compile(
    r"(\[\s*T\s*\d|floor|удержив|tab\b|shift|ctrl|alt\b|win\b|esc\b|page\s*up|page\s*down|"
    r"num\s*lock|caps|space|enter|click|double|mouse|клавиш|нажмите|удерж)",
    re.IGNORECASE,
)
_SKIP_LINE_RE = re.compile(
    r"(нетронуто|не\s*тронуто|поврежден|изношен|испорчен|кг|шт\.?|меньше|около|\d+\s*/\s*\d+|"
    r"техническ|раскач|отдач|урон|состоян|снаряжение|экипиров|сервопривод|контейнер|руки|поблизости|"
    r"штан|артефакт|floor|удержив|какая-то\s+дичь|passive|battery|magnification|"
    r"generation|optical|required|operation|army|container|artifact)",
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
    return (cyr + latin, alnum, len(line))


def _name_quality_score(name: str) -> tuple[int, int, int]:
    line = name.strip()
    score = _line_score(line)
    bonus = 0
    if _HUD_GARBAGE_RE.search(line):
        bonus -= 1000
    if "[" in line or "]" in line:
        bonus -= 500
    if "/" in line or "-" in line:
        bonus += 80
    if re.search(r"\d", line) and re.search(r"[A-Za-zА-Яа-яЁё]", line):
        bonus += 40
    return (score[0] + bonus, score[1], score[2])


def _upscale_raw(image: Image.Image) -> Image.Image:
    rgb = image.convert("RGB")
    w, h = rgb.size
    scale = max(3, min(5, 260 // max(h, 1)))
    if scale > 1:
        rgb = rgb.resize((w * scale, h * scale), Image.Resampling.LANCZOS)
    return ImageEnhance.Contrast(rgb).enhance(1.15)


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

    return pick_best_name(names) or ""


def normalize_item_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(name or "").strip())
    cleaned = cleaned.strip("·|•-— ")
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
    if _HUD_GARBAGE_RE.search(line):
        return False
    if re.search(r"[\[\]]", line):
        return False
    return bool(re.search(r"[\wА-Яа-яЁё]", line))


def extract_item_name(ocr_text: str) -> str | None:
    """Tooltip title is always the first valid line top-to-bottom."""
    lines = [ln.strip() for ln in ocr_text.replace("\r", "\n").split("\n") if ln.strip()]
    for line in lines:
        cleaned = normalize_item_name(line)
        if is_valid_item_name(cleaned):
            return cleaned
    return None


def pick_best_name(names: list[str]) -> str | None:
    valid: list[str] = []
    seen: set[str] = set()
    for raw in names:
        name = normalize_item_name(raw)
        key = name.casefold()
        if not is_valid_item_name(name) or key in seen:
            continue
        seen.add(key)
        valid.append(name)
    if not valid:
        return None
    valid.sort(key=_name_quality_score, reverse=True)
    return valid[0]


def _ocr_regions(search: SearchArea) -> list[str]:
    from item_tooltip_locator import region_ocr_priority

    names: list[str] = []
    regions = find_title_regions_in_search(search)
    regions.sort(
        key=lambda box: region_ocr_priority(search, box),
        reverse=True,
    )
    for box in regions[:6]:
        crop = search.image.crop(box)
        name = recognize_tooltip_text(crop)
        if name and is_valid_item_name(name):
            names.append(name)
    return names


def read_item_name_at_cursor(
    cfg: dict,
    *,
    on_search: Callable[[str], None] | None = None,
) -> str | None:
    search = grab_tooltip_search_area(cfg)
    if search is None:
        if on_search:
            on_search("hint")
        return None

    names = _ocr_regions(search)
    name = pick_best_name(names)
    if not is_valid_item_name(name):
        if on_search:
            on_search("hint")
        return None
    return normalize_item_name(name or "")
