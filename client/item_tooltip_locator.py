"""Locate DayZ inventory tooltip title strip near the cursor."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from capture import grab_region, resolve_monitor
from mouse_util import get_cursor_pos


@dataclass(frozen=True)
class SearchArea:
    image: Image.Image
    origin_x: int
    origin_y: int
    cursor_x: int
    cursor_y: int
    monitor_width: int
    monitor_height: int


# Fallback offsets when image scan finds nothing (tooltip beside hovered cell).
_CURSOR_TITLE_BOXES = (
    (12, -108, 520, 58),
    (20, -88, 540, 54),
    (28, -68, 500, 52),
    (8, -128, 560, 60),
    (-400, -96, 420, 54),
    (-360, -72, 440, 52),
    (-440, -48, 400, 50),
    (-320, -112, 460, 56),
    (180, -40, 480, 54),
    (220, 0, 460, 52),
    (140, 40, 500, 54),
    (80, 80, 520, 56),
    (0, 100, 540, 58),
    (0, 140, 520, 56),
    (-72, 20, 520, 56),
    (-120, 36, 480, 54),
    (-48, 52, 500, 56),
    (-520, -96, 420, 54),
    (60, -96, 460, 52),
)


def _box_center(box: tuple[int, int, int, int]) -> tuple[float, float]:
    x0, y0, x1, y1 = box
    return (x0 + x1) / 2.0, (y0 + y1) / 2.0


def _cursor_distance(box: tuple[int, int, int, int], cursor_x: int, cursor_y: int) -> float:
    cx, cy = _box_center(box)
    return ((cx - cursor_x) ** 2 + (cy - cursor_y) ** 2) ** 0.5


def _dark_mask(rgb: np.ndarray) -> np.ndarray:
    red = rgb[..., 0]
    green = rgb[..., 1]
    blue = rgb[..., 2]
    return (red <= 102) & (green <= 102) & (blue <= 108)


def _title_only_mask(rgb: np.ndarray) -> np.ndarray:
    red = rgb[..., 0].astype(np.int16)
    green = rgb[..., 1].astype(np.int16)
    blue = rgb[..., 2].astype(np.int16)
    orange = (red >= 108) & (green >= 58) & (blue <= 148) & (red >= blue + 10)
    yellow = (red >= 168) & (green >= 142) & (blue <= 178) & (red >= green - 8)
    white = (red >= 190) & (green >= 190) & (blue >= 190)
    green_txt = (green >= 118) & (green >= red + 18) & (green >= blue + 18)
    return (orange | yellow | white) & ~green_txt


def grab_tooltip_search_area(cfg: dict) -> SearchArea | None:
    monitor_index = int(cfg.get("monitor_index", 1))
    mon = resolve_monitor(monitor_index)
    if not mon:
        return None

    cx, cy = get_cursor_pos()
    cursor_x = cx - mon.left
    cursor_y = cy - mon.top

    search_cfg = cfg.get("item_tooltip_search") or {}
    mode = str(search_cfg.get("mode", "cursor")).strip().lower()

    if mode == "center":
        mx = int(search_cfg.get("margin_x", max(48, int(mon.width * 0.10))))
        my = int(search_cfg.get("margin_y", max(72, int(mon.height * 0.14))))
        left = mx
        top = my
        right = mon.width - mx
        bottom = mon.height - max(36, int(mon.height * 0.05))
    else:
        max_left = int(search_cfg.get("max_left", 480))
        max_right = int(search_cfg.get("max_right", 580))
        pad_left = max(int(search_cfg.get("left", 120)), max_left)
        pad_right = max(int(search_cfg.get("right", 560)), max_right)
        pad_up = int(search_cfg.get("up", 220))
        pad_down = int(search_cfg.get("down", 300))
        left = max(0, cursor_x - pad_left)
        top = max(0, cursor_y - pad_up)
        right = min(mon.width, cursor_x + pad_right)
        bottom = min(mon.height, cursor_y + pad_down)

    if right <= left + 120 or bottom <= top + 60:
        return None

    image = grab_region(monitor_index, (left, top, right, bottom))
    if image is None:
        return None

    return SearchArea(
        image=image,
        origin_x=left,
        origin_y=top,
        cursor_x=cursor_x - left,
        cursor_y=cursor_y - top,
        monitor_width=mon.width,
        monitor_height=mon.height,
    )


def _clamp_box(x0: int, y0: int, x1: int, y1: int, w: int, h: int) -> tuple[int, int, int, int] | None:
    x0 = max(0, min(w - 8, x0))
    y0 = max(0, min(h - 8, y0))
    x1 = max(x0 + 24, min(w, x1))
    y1 = max(y0 + 16, min(h, y1))
    if x1 - x0 < 48 or y1 - y0 < 14:
        return None
    return (x0, y0, x1, y1)


def _dedupe_boxes(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    out: list[tuple[int, int, int, int]] = []
    for box in boxes:
        duplicate = False
        x0, y0, x1, y1 = box
        for ox0, oy0, ox1, oy1 in out:
            ix0 = max(x0, ox0)
            iy0 = max(y0, oy0)
            ix1 = min(x1, ox1)
            iy1 = min(y1, oy1)
            if ix1 <= ix0 or iy1 <= iy0:
                continue
            inter = (ix1 - ix0) * (iy1 - iy0)
            area = (x1 - x0) * (y1 - y0)
            if area and inter / area > 0.72:
                duplicate = True
                break
        if not duplicate:
            out.append(box)
    return out


def _title_stats(rgb: np.ndarray, box: tuple[int, int, int, int]) -> tuple[int, float, int]:
    x0, y0, x1, y1 = box
    crop = rgb[y0:y1, x0:x1]
    if crop.size == 0:
        return 0, 0.0, 0
    title = _title_only_mask(crop)
    dark = _dark_mask(crop)
    title_px = int(title.sum())
    dark_ratio = float(dark.mean())

    upper = title[: max(1, (y1 - y0) // 2)]
    cols = np.where(upper.any(axis=0))[0]
    span = int(cols[-1] - cols[0] + 1) if cols.size else 0

    best_run = span
    for row in upper:
        for x0c, x1c in _clusters_from_row(row, min_width=6):
            best_run = max(best_run, x1c - x0c + 1)
    return title_px, dark_ratio, best_run


def _is_hud_strip(box: tuple[int, int, int, int], w_img: int) -> bool:
    x0, y0, x1, y1 = box
    bw = x1 - x0
    bh = y1 - y0
    return y0 < 160 and bw > w_img * 0.48 and bh < 78


def _is_client_overlay_zone(search: SearchArea, box: tuple[int, int, int, int]) -> bool:
    """Exclude our own top-right price hint overlay from tooltip detection."""
    x0, y0, x1, y1 = box
    abs_x0 = search.origin_x + x0
    abs_y1 = search.origin_y + y1
    margin_x = max(320, int(search.monitor_width * 0.20))
    margin_y = max(140, int(search.monitor_height * 0.11))
    if abs_y1 <= margin_y and abs_x0 >= search.monitor_width - margin_x:
        return True
    if search.origin_y + y1 <= margin_y and search.origin_x + x1 >= search.monitor_width - 80:
        return True
    return False


def region_ocr_priority(search: SearchArea, box: tuple[int, int, int, int]) -> float:
    """Higher = OCR this region first. Primary signal: title text on dark tooltip."""
    x0, y0, x1, y1 = box
    rgb = np.asarray(search.image.convert("RGB"))
    w_img = rgb.shape[1]
    title_px, dark_ratio, title_run = _title_stats(rgb, box)
    bw = x1 - x0
    bh = y1 - y0
    dist = _cursor_distance(box, search.cursor_x, search.cursor_y)
    abs_y0 = search.origin_y + y0
    box_cx = (x0 + x1) / 2.0
    x_delta = abs(box_cx - search.cursor_x)

    score = title_px * 18.0 + title_run * 8.0 + dark_ratio * 1200.0
    if title_px < 35 or title_run < 24:
        score -= 12000
    if title_px > 700:
        score -= 15000
    if 60 <= title_px <= 420:
        score += 1200
    if dark_ratio < 0.42:
        score -= 8000
    if 120 <= bw <= 560 and 28 <= bh <= 78:
        score += 900
    if _is_hud_strip(box, w_img):
        score -= 20000
    if _is_client_overlay_zone(search, box):
        score -= 30000
    # Tooltip title is often horizontally aligned with hovered item.
    score -= x_delta * 1.8
    score -= dist * 0.6
    if x_delta <= 180:
        score += 500
    if abs_y0 < 110:
        score -= 15000
    return score


def _region_excluded(search: SearchArea, box: tuple[int, int, int, int], rgb: np.ndarray) -> bool:
    if search.origin_y + box[1] < 100:
        return True
    w_img = rgb.shape[1]
    if _is_hud_strip(box, w_img):
        return True
    if _is_client_overlay_zone(search, box):
        return True
    title_px, dark_ratio, title_run = _title_stats(rgb, box)
    if title_px < 22 or title_run < 14:
        return True
    if title_px > 700:
        return True
    if dark_ratio < 0.32:
        return True
    return False


def _clusters_from_row(row: np.ndarray, *, min_width: int = 8) -> list[tuple[int, int]]:
    xs = np.where(row)[0]
    if xs.size == 0:
        return []
    clusters: list[tuple[int, int]] = []
    start = int(xs[0])
    prev = int(xs[0])
    for x in xs[1:]:
        x = int(x)
        if x - prev > 3:
            if prev - start + 1 >= min_width:
                clusters.append((start, prev))
            start = x
        prev = x
    if prev - start + 1 >= min_width:
        clusters.append((start, prev))
    return clusters


def _title_box_from_panel(panel: tuple[int, int, int, int], w: int, h: int) -> tuple[int, int, int, int] | None:
    tx, ty, rx, by = panel
    title_h = min(64, max(44, (by - ty) // 5))
    return _clamp_box(tx + 8, ty + 4, rx - 8, ty + title_h, w, h)


def _find_dark_panel_titles_global(search: SearchArea) -> list[tuple[int, int, int, int]]:
    """Scan the whole search image for DayZ tooltip panels (dark box + title strip)."""
    rgb = np.asarray(search.image.convert("RGB"))
    rel_cursor_x = search.cursor_x
    rel_cursor_y = search.cursor_y
    dark = _dark_mask(rgb)
    h, w = dark.shape
    scored: list[tuple[float, tuple[int, int, int, int]]] = []

    y_min = 36
    y_max = h - 80
    for ty in range(y_min, y_max, 8):
        for tx in range(0, w - 160, 10):
            if dark[ty : ty + 8, tx : tx + 24].mean() < 0.45:
                continue

            rx = tx
            for x in range(tx + 100, min(w, tx + 680), 6):
                col = dark[ty : min(h, ty + 44), max(tx, x - 10) : min(w, x + 10)].mean()
                if col < 0.38:
                    break
                rx = x
            bw = rx - tx
            if bw < 160:
                continue

            by = ty
            for y in range(ty + 56, min(h, ty + 460), 8):
                row = dark[y, tx : rx + 1].mean()
                if row < 0.4:
                    by = y
                    break
                by = y
            bh = by - ty
            if bh < 68:
                continue

            panel = (tx, ty, rx, by)
            title = _title_box_from_panel(panel, w, h)
            if not title:
                continue
            x0, y0, x1, y1 = title
            if y0 < 100 or _is_hud_strip(title, w):
                continue
            if _is_client_overlay_zone(search, title):
                continue
            title_px, dark_ratio, title_run = _title_stats(rgb, title)
            if title_px < 35 or title_run < 20 or dark_ratio < 0.42:
                continue
            if title_px > 700:
                continue

            dist = _cursor_distance(title, rel_cursor_x, rel_cursor_y)
            score = title_px * 14.0 + title_run * 5.0 + min(bw, 560) - dist * 1.5
            if 60 <= title_px <= 420:
                score += 900
            if ty < 60:
                score -= 8000
            if bh > h * 0.82:
                score -= 6000
            scored.append((score, title))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [box for _, box in scored[:20]]


def _find_title_row_boxes_global(search: SearchArea) -> list[tuple[int, int, int, int]]:
    """Find orange/white title lines on dark background anywhere in the search area."""
    rgb = np.asarray(search.image.convert("RGB"))
    rel_cursor_x = search.cursor_x
    rel_cursor_y = search.cursor_y
    title = _title_only_mask(rgb)
    dark = _dark_mask(rgb)
    h, w = title.shape
    bands: list[tuple[float, tuple[int, int, int, int]]] = []

    y = 36
    while y < h - 20:
        clusters = _clusters_from_row(title[y], min_width=10)
        if not clusters:
            y += 1
            continue
        max_run = max(x1 - x0 + 1 for x0, x1 in clusters)
        if max_run < 36:
            y += 1
            continue

        y0 = y
        merged: dict[tuple[int, int], int] = {c: 1 for c in clusters}
        y1 = y + 1
        while y1 < h - 8:
            next_clusters = _clusters_from_row(title[y1], min_width=10)
            if not next_clusters:
                break
            hit = False
            for cluster in next_clusters:
                for key in list(merged.keys()):
                    if abs(cluster[0] - key[0]) <= 28 and abs(cluster[1] - key[1]) <= 40:
                        merged[key] += 1
                        hit = True
                        break
                if not hit:
                    merged[cluster] = 1
            if not hit:
                break
            y1 += 1

        for (x0, x1), row_span in merged.items():
            bw = x1 - x0 + 1
            if bw < 56 or bw > 640:
                continue
            top = max(0, y0 - 6)
            bottom = min(h, y1 + 10)
            bg = float(dark[top:bottom, x0 : x1 + 1].mean())
            if bg < 0.45:
                continue
            pixels = int(title[top:bottom, x0 : x1 + 1].sum())
            if pixels < 40:
                continue

            box = _clamp_box(max(0, x0 - 12), top, min(w, x1 + 14), max(top + 42, bottom), w, h)
            if not box:
                continue
            if _is_hud_strip(box, w):
                continue
            if _is_client_overlay_zone(search, box):
                continue
            title_px = int(title[top:bottom, x0 : x1 + 1].sum())
            if title_px > 700:
                continue
            dist = _cursor_distance(box, rel_cursor_x, rel_cursor_y)
            score = title_px * 10.0 + bw * 2.0 + bg * 800.0 - dist * 1.2
            if 60 <= title_px <= 420:
                score += 900
            if y0 < 100:
                score -= 8000
            bands.append((score, box))
        y = max(y + 1, y1)

    bands.sort(key=lambda item: item[0], reverse=True)
    return [box for _, box in bands[:20]]


def to_monitor_boxes(
    search: SearchArea,
    boxes: list[tuple[int, int, int, int]],
) -> list[tuple[int, int, int, int]]:
    return [
        (search.origin_x + x0, search.origin_y + y0, search.origin_x + x1, search.origin_y + y1)
        for x0, y0, x1, y1 in boxes
    ]


def search_monitor_rect(search: SearchArea) -> tuple[int, int, int, int]:
    w, h = search.image.size
    return (search.origin_x, search.origin_y, search.origin_x + w, search.origin_y + h)


def cursor_monitor_point(search: SearchArea) -> tuple[int, int]:
    return (search.origin_x + search.cursor_x, search.origin_y + search.cursor_y)


def _cursor_fallback_regions(search: SearchArea, limit: int = 4) -> list[tuple[int, int, int, int]]:
    w, h = search.image.size
    cx, cy = search.cursor_x, search.cursor_y
    out: list[tuple[int, int, int, int]] = []
    for dx, dy, rw, rh in _CURSOR_TITLE_BOXES:
        box = _clamp_box(cx + dx, cy + dy, cx + dx + rw, cy + dy + rh, w, h)
        if box:
            out.append(box)
        if len(out) >= limit:
            break
    return out


def find_title_regions_in_search(search: SearchArea) -> list[tuple[int, int, int, int]]:
    """Return local (L,T,R,B) title crops, best tooltip title first."""
    rgb = np.asarray(search.image.convert("RGB"))
    h, w = rgb.shape[:2]
    cx, cy = search.cursor_x, search.cursor_y
    boxes: list[tuple[int, int, int, int]] = []

    # Primary: scan entire search area for real tooltip title strips.
    for box in _find_dark_panel_titles_global(search):
        if not _region_excluded(search, box, rgb):
            boxes.append(box)

    for box in _find_title_row_boxes_global(search):
        if not _region_excluded(search, box, rgb):
            boxes.append(box)

    # Fallback: cursor-relative presets (only if they contain title-colored pixels).
    for dx, dy, rw, rh in _CURSOR_TITLE_BOXES:
        box = _clamp_box(cx + dx, cy + dy, cx + dx + rw, cy + dy + rh, w, h)
        if box and not _region_excluded(search, box, rgb):
            boxes.append(box)

    deduped = _dedupe_boxes(boxes)
    if not deduped:
        deduped = _cursor_fallback_regions(search, limit=4)
    deduped.sort(key=lambda b: region_ocr_priority(search, b), reverse=True)
    return deduped


def find_tooltip_region(cfg: dict) -> tuple[tuple[int, int, int, int] | None, str]:
    search = grab_tooltip_search_area(cfg)
    if search is None:
        return None, "none"

    regions = find_title_regions_in_search(search)
    if not regions:
        return None, "none"

    x0, y0, x1, y1 = regions[0]
    return (
        search.origin_x + x0,
        search.origin_y + y0,
        search.origin_x + x1,
        search.origin_y + y1,
    ), "cursor"
