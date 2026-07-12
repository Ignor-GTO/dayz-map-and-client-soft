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


# Tooltip title strip offsets from hovered item (dx, dy, width, height).
# DayZ opens the panel beside the cursor — position depends on grid cell.
_CURSOR_TITLE_BOXES = (
    (12, -108, 520, 58),
    (20, -88, 540, 54),
    (28, -68, 500, 52),
    (8, -128, 560, 60),
    (36, -48, 480, 50),
    (-400, -96, 420, 54),
    (-360, -72, 440, 52),
    (-440, -48, 400, 50),
    (-320, -112, 460, 56),
    (-72, 20, 520, 56),
    (-120, 36, 480, 54),
    (-48, 52, 500, 56),
    (-40, -152, 480, 54),
    (0, -168, 520, 56),
    (-200, -80, 500, 54),
    (60, -96, 460, 52),
)


def _box_center(box: tuple[int, int, int, int]) -> tuple[float, float]:
    x0, y0, x1, y1 = box
    return (x0 + x1) / 2.0, (y0 + y1) / 2.0


def _cursor_distance(box: tuple[int, int, int, int], cursor_x: int, cursor_y: int) -> float:
    cx, cy = _box_center(box)
    return ((cx - cursor_x) ** 2 + (cy - cursor_y) ** 2) ** 0.5


def region_ocr_priority(search: SearchArea, box: tuple[int, int, int, int]) -> float:
    """Higher = OCR this region first. Primary signal: distance to cursor."""
    x0, y0, x1, y1 = box
    w, h = search.image.size
    bw = x1 - x0
    bh = y1 - y0
    dist = _cursor_distance(box, search.cursor_x, search.cursor_y)
    abs_y0 = search.origin_y + y0
    abs_x0 = search.origin_x + x0

    score = 5000.0 - dist * 14.0
    if dist <= 180:
        score += 800
    if dist <= 120:
        score += 600
    if 110 <= bw <= 540:
        score += 500
    if bw > 620:
        score -= 350
    if 34 <= bh <= 72:
        score += 250
    # Screen-top HUD / key hints (absolute coordinates).
    if abs_y0 < 95:
        score -= 6000
    if abs_y0 < 130 and abs_x0 > search.origin_x + w * 0.45:
        score -= 3500
    return score


def _region_excluded(search: SearchArea, box: tuple[int, int, int, int]) -> bool:
    x0, y0, x1, y1 = box
    if search.origin_y + y1 < 80:
        return True
    if _cursor_distance(box, search.cursor_x, search.cursor_y) > 420:
        return True
    return False


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


def _cursor_in_box(box: tuple[int, int, int, int], cursor_x: int, cursor_y: int) -> bool:
    x0, y0, x1, y1 = box
    return x0 <= cursor_x <= x1 and y0 <= cursor_y <= y1


def _find_dark_panel_near_cursor(
    rgb: np.ndarray,
    rel_cursor_x: int,
    rel_cursor_y: int,
) -> tuple[tuple[int, int, int, int] | None, tuple[int, int, int, int] | None]:
    dark = _dark_mask(rgb)
    h, w = dark.shape
    best_panel: tuple[int, int, int, int] | None = None
    best_score = -10**12

    y_min = max(0, rel_cursor_y - 260)
    y_max = min(h - 90, rel_cursor_y + 120)
    x_min = max(0, rel_cursor_x - 480)
    x_max = min(w - 200, rel_cursor_x + 120)

    for ty in range(y_min, y_max, 8):
        for tx in range(x_min, x_max, 8):
            if dark[ty : ty + 8, tx : tx + 24].mean() < 0.45:
                continue

            rx = tx
            for x in range(tx + 100, min(w, tx + 620, rel_cursor_x + 560), 6):
                col = dark[ty : min(h, ty + 44), max(tx, x - 10) : min(w, x + 10)].mean()
                if col < 0.38:
                    break
                rx = x
            bw = rx - tx
            if bw < 180:
                continue

            by = ty
            for y in range(ty + 56, min(h, ty + 420, ty + rel_cursor_y + 280), 8):
                row = dark[y, tx : rx + 1].mean()
                if row < 0.4:
                    by = y
                    break
                by = y
            bh = by - ty
            if bh < 72:
                continue

            panel = (tx, ty, rx, by)
            title_band = rgb[ty : min(h, ty + 52), tx : rx + 1]
            title_pixels = int(_title_only_mask(title_band).sum())
            if title_pixels < 30:
                continue

            dist = _cursor_distance(panel, rel_cursor_x, rel_cursor_y)
            if dist > 380 and not _cursor_in_box(panel, rel_cursor_x, rel_cursor_y):
                continue

            score = 4000 - dist * 12 + title_pixels * 8 + min(bw, 520)
            if _cursor_in_box(panel, rel_cursor_x, rel_cursor_y):
                score += 900
            if bh > h * 0.75:
                score -= 4000
            if score > best_score:
                best_score = score
                best_panel = panel

    if best_panel is None:
        return None, None
    title = _title_box_from_panel(best_panel, w, h)
    return best_panel, title


def _title_box_from_panel(panel: tuple[int, int, int, int], w: int, h: int) -> tuple[int, int, int, int] | None:
    tx, ty, rx, by = panel
    title_h = min(60, max(44, (by - ty) // 5))
    return _clamp_box(tx + 8, ty + 4, rx - 8, ty + title_h, w, h)


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


def _find_title_row_boxes_near_cursor(
    rgb: np.ndarray,
    rel_cursor_x: int,
    rel_cursor_y: int,
) -> list[tuple[int, int, int, int]]:
    title = _title_only_mask(rgb)
    dark = _dark_mask(rgb)
    h, w = title.shape
    bands: list[tuple[float, tuple[int, int, int, int]]] = []

    y_lo = max(0, rel_cursor_y - 200)
    y_hi = min(h - 1, rel_cursor_y + 100)

    y = y_lo
    while y <= y_hi:
        clusters = _clusters_from_row(title[y], min_width=10)
        if not clusters:
            y += 1
            continue

        y0 = y
        merged: dict[tuple[int, int], int] = {c: 1 for c in clusters}
        y1 = y + 1
        while y1 <= y_hi:
            next_clusters = _clusters_from_row(title[y1], min_width=10)
            if not next_clusters:
                break
            hit = False
            for cluster in next_clusters:
                for key in list(merged.keys()):
                    if abs(cluster[0] - key[0]) <= 24 and abs(cluster[1] - key[1]) <= 36:
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
            if bw < 70 or bw > 620:
                continue
            top = max(0, y0 - 6)
            bottom = min(h, y1 + 8)
            bg = float(dark[top:bottom, x0 : x1 + 1].mean())
            if bg < 0.42:
                continue
            pixels = int(title[top:bottom, x0 : x1 + 1].sum())
            if pixels < 35:
                continue

            box = _clamp_box(max(0, x0 - 10), top, min(w, x1 + 12), max(top + 40, bottom), w, h)
            if not box:
                continue
            dist = _cursor_distance(box, rel_cursor_x, rel_cursor_y)
            if dist > 360:
                continue
            score = 3000 - dist * 10 + pixels + min(bw, 400)
            bands.append((score, box))
        y = max(y + 1, y1)

    bands.sort(key=lambda item: item[0], reverse=True)
    return [box for _, box in bands[:8]]


def find_title_regions_in_search(search: SearchArea) -> list[tuple[int, int, int, int]]:
    """Return local (L,T,R,B) title crops, sorted by proximity to cursor."""
    rgb = np.asarray(search.image.convert("RGB"))
    h, w = rgb.shape[:2]
    cx, cy = search.cursor_x, search.cursor_y
    boxes: list[tuple[int, int, int, int]] = []

    for dx, dy, rw, rh in _CURSOR_TITLE_BOXES:
        box = _clamp_box(cx + dx, cy + dy, cx + dx + rw, cy + dy + rh, w, h)
        if box and not _region_excluded(search, box):
            x0, y0, x1, y1 = box
            if _title_only_mask(rgb[y0:y1, x0:x1]).sum() >= 20:
                boxes.append(box)

    _panel, title = _find_dark_panel_near_cursor(rgb, cx, cy)
    if title and not _region_excluded(search, title):
        boxes.append(title)

    for box in _find_title_row_boxes_near_cursor(rgb, cx, cy):
        if not _region_excluded(search, box):
            boxes.append(box)

    deduped = _dedupe_boxes(boxes)
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
