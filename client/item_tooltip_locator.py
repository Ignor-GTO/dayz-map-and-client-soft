"""Locate DayZ inventory tooltip panel and title strip near the cursor."""

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


# Typical tooltip title offsets in DayZ / STALKER inventory UI.
_CANDIDATE_TITLE_BOXES = (
    (18, -96, 520, 56),
    (28, -82, 540, 54),
    (10, -112, 500, 58),
    (36, -68, 520, 52),
    (-110, 24, 540, 56),
    (-140, -36, 520, 54),
    (-40, 48, 520, 56),
    (60, -88, 480, 50),
)


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
    mode = str(search_cfg.get("mode", "center")).strip().lower()

    if mode == "center":
        # Inventory tooltip in DayZ/STALKER mods often opens in screen center,
        # far from the hovered grid cell — grab a large central band.
        mx = int(search_cfg.get("margin_x", max(48, int(mon.width * 0.12))))
        my = int(search_cfg.get("margin_y", max(36, int(mon.height * 0.06))))
        left = mx
        top = my
        right = mon.width - mx
        bottom = mon.height - my
    else:
        pad_left = int(search_cfg.get("left", 420))
        pad_right = int(search_cfg.get("right", 220))
        pad_up = int(search_cfg.get("up", 280))
        pad_down = int(search_cfg.get("down", 220))
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
        x0, y0, x1, y1 = box
        duplicate = False
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


def _find_dark_panel_bbox(
    rgb: np.ndarray,
    rel_cursor_x: int,
    rel_cursor_y: int,
) -> tuple[int, int, int, int] | None:
    dark = _dark_mask(rgb)
    h, w = dark.shape
    best: tuple[int, int, int, int] | None = None
    best_score = -10**12

    for ty in range(0, max(8, h - 90), 8):
        for tx in range(0, max(8, w - 200), 8):
            if dark[ty : ty + 8, tx : tx + 24].mean() < 0.45:
                continue

            rx = tx
            for x in range(tx + 100, min(w, tx + 680), 6):
                col = dark[ty : min(h, ty + 44), max(tx, x - 10) : min(w, x + 10)].mean()
                if col < 0.38:
                    break
                rx = x
            bw = rx - tx
            if bw < 220:
                continue

            by = ty
            for y in range(ty + 56, min(h, ty + 460), 8):
                row = dark[y, tx : rx + 1].mean()
                if row < 0.4:
                    by = y
                    break
                by = y
            bh = by - ty
            if bh < 90:
                continue
            if ty < 36:
                continue

            title_band = rgb[ty : min(h, ty + 52), tx : rx + 1]
            title_pixels = int(_title_only_mask(title_band).sum())
            if title_pixels < 35:
                continue

            bx = (tx + rx) // 2
            by_mid = ty + bh // 2
            dist = abs(bx - rel_cursor_x) * 0.2 + abs(by_mid - rel_cursor_y) * 0.15
            score = title_pixels * 28 + bw * min(bh, 280) - dist * 4
            if ty >= 60:
                score += 500
            if 140 <= bw <= 620:
                score += 350
            if bh > h * 0.72:
                score -= 60000
            if score > best_score:
                best_score = score
                best = (tx, ty, rx, by)

    return best


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


def _find_title_row_boxes(rgb: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Find tooltip title bands by white/orange text clusters on dark background."""
    title = _title_only_mask(rgb)
    dark = _dark_mask(rgb)
    h, w = title.shape
    bands: list[tuple[float, tuple[int, int, int, int]]] = []

    y = 0
    while y < h:
        clusters = _clusters_from_row(title[y], min_width=10)
        if not clusters:
            y += 1
            continue

        y0 = y
        merged: dict[tuple[int, int], int] = {c: 1 for c in clusters}
        y1 = y + 1
        while y1 < h:
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
            if row_span < 1:
                continue
            bw = x1 - x0 + 1
            if bw < 70 or bw > 680:
                continue
            top = max(0, y0 - 6)
            bottom = min(h, y1 + 8)
            bg = float(dark[top:bottom, x0 : x1 + 1].mean())
            if bg < 0.42:
                continue
            pixels = int(title[top:bottom, x0 : x1 + 1].sum())
            if pixels < 40:
                continue

            score = pixels + bw + bg * 100.0 + row_span * 20.0 - top * 2.5
            if top < 72:
                score -= 220
            if bw > w * 0.75:
                score -= 350
            if 100 <= bw <= 620:
                score += 160
            if top >= 100:
                score += 80

            box = _clamp_box(max(0, x0 - 10), top, min(w, x1 + 12), max(top + 40, bottom), w, h)
            if box:
                bands.append((score, box))
        y = y1

    bands.sort(key=lambda item: item[0], reverse=True)
    return [box for _, box in bands[:8]]


def find_title_regions_in_search(search: SearchArea) -> list[tuple[int, int, int, int]]:
    """Return local (L,T,R,B) title crops inside search.image, best first."""
    rgb = np.asarray(search.image.convert("RGB"))
    h, w = rgb.shape[:2]
    boxes: list[tuple[int, int, int, int]] = []

    panel = _find_dark_panel_bbox(rgb, search.cursor_x, search.cursor_y)
    if panel and panel[1] >= 80:
        title = _title_box_from_panel(panel, w, h)
        if title:
            boxes.append(title)

    for box in _find_title_row_boxes(rgb):
        boxes.append(box)

    for dx, dy, rw, rh in _CANDIDATE_TITLE_BOXES:
        x0 = search.cursor_x + dx
        y0 = search.cursor_y + dy
        box = _clamp_box(x0, y0, x0 + rw, y0 + rh, w, h)
        if box:
            x0, y0, x1, y1 = box
            band = rgb[y0:y1, x0:x1]
            if _title_only_mask(band).sum() >= 24:
                boxes.append(box)

    return _dedupe_boxes(boxes)


def find_tooltip_region(cfg: dict) -> tuple[tuple[int, int, int, int] | None, str]:
    """Legacy single-region API; prefers dark tooltip panel title strip."""
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
    ), "panel"
