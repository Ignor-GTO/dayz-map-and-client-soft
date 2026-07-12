"""Locate DayZ inventory tooltip title strip near the cursor."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from capture import grab_monitor, grab_region, resolve_monitor
from mouse_util import get_cursor_pos


@dataclass
class GreenIndicator:
    cx: int
    cy: int
    area: int
    score: float


def _orange_mask(rgb: np.ndarray) -> np.ndarray:
    red = rgb[..., 0].astype(np.int16)
    green = rgb[..., 1].astype(np.int16)
    blue = rgb[..., 2].astype(np.int16)
    orange = (
        (red >= 105)
        & (green >= 55)
        & (blue <= 145)
        & (red >= blue)
        & ((red - blue) >= 12)
    )
    yellow = (red >= 170) & (green >= 145) & (blue <= 175) & (red >= green)
    return orange | yellow


def _green_mask(rgb: np.ndarray) -> np.ndarray:
    red = rgb[..., 0].astype(np.int16)
    green = rgb[..., 1].astype(np.int16)
    blue = rgb[..., 2].astype(np.int16)
    return (
        (green >= 95)
        & (green >= red * 108 // 100)
        & (green >= blue * 112 // 100)
        & (red < 230)
        & (blue < 210)
        & ((green - red) >= 18)
    )


def _cluster_mask(mask: np.ndarray, cell: int = 12) -> list[GreenIndicator]:
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return []

    buckets: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for x, y in zip(xs.tolist(), ys.tolist()):
        key = (x // cell, y // cell)
        buckets.setdefault(key, []).append((x, y))

    found: list[GreenIndicator] = []
    for points in buckets.values():
        if len(points) < 8:
            continue
        px = np.array([p[0] for p in points], dtype=np.float32)
        py = np.array([p[1] for p in points], dtype=np.float32)
        cx = float(px.mean())
        cy = float(py.mean())
        dist = np.hypot(px - cx, py - cy)
        area = len(points)
        if area > 6000:
            continue
        if dist.size and dist.max() > 0 and (dist.mean() / max(dist.max(), 1.0)) > 0.42:
            continue
        score = float(area) / (1.0 + dist.std())
        found.append(GreenIndicator(int(round(cx)), int(round(cy)), area, score))

    found.sort(key=lambda item: item.score, reverse=True)
    return found


def find_green_indicators(image: Image.Image, *, scale: float = 0.5) -> list[GreenIndicator]:
    if scale != 1.0:
        w, h = image.size
        small = image.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.BILINEAR)
        inv = 1.0 / scale
    else:
        small = image
        inv = 1.0

    rgb = np.array(small.convert("RGB"))
    indicators = _cluster_mask(_green_mask(rgb))
    if inv != 1.0:
        for item in indicators:
            item.cx = int(round(item.cx * inv))
            item.cy = int(round(item.cy * inv))
    return indicators


def pick_best_indicator(
    indicators: list[GreenIndicator],
    *,
    cursor_x: int | None,
    cursor_y: int | None,
    max_cursor_dist: int = 320,
) -> GreenIndicator | None:
    if not indicators:
        return None
    if cursor_x is None or cursor_y is None:
        return indicators[0]

    best: GreenIndicator | None = None
    best_key = -1.0
    for item in indicators:
        dist = ((item.cx - cursor_x) ** 2 + (item.cy - cursor_y) ** 2) ** 0.5
        if dist > max_cursor_dist:
            continue
        key = item.score * 1000.0 - dist
        if key > best_key:
            best_key = key
            best = item
    return best or indicators[0]


def region_from_indicator(
    indicator: GreenIndicator,
    monitor_width: int,
    monitor_height: int,
    *,
    dx: int,
    dy: int,
    width: int,
    height: int,
) -> tuple[int, int, int, int]:
    left = max(0, indicator.cx + dx)
    top = max(0, indicator.cy + dy)
    right = min(monitor_width, left + max(40, width))
    bottom = min(monitor_height, top + max(24, height))
    if right <= left + 8 or bottom <= top + 8:
        return (0, 0, 0, 0)
    return (left, top, right, bottom)


def _find_orange_title_in_image(
    image: Image.Image,
    *,
    rel_cursor_x: int,
    rel_cursor_y: int,
    min_orange: int = 28,
) -> tuple[int, int, int, int] | None:
    rgb = np.asarray(image.convert("RGB"))
    mask = _orange_mask(rgb)
    h, w = mask.shape
    if h < 12 or w < 40:
        return None

    near = mask[
        max(0, rel_cursor_y - 120) : min(h, rel_cursor_y + 40),
        max(0, rel_cursor_x - 30) : min(w, rel_cursor_x + 360),
    ]
    if int(near.sum()) < min_orange:
        return None

    best_row = -1
    best_score = -10**9
    y_min = max(0, rel_cursor_y - 120)
    y_max = min(h - 8, rel_cursor_y + 35)
    for y in range(y_min, y_max):
        row = mask[y]
        count = int(row.sum())
        if count < min_orange:
            continue
        band = mask[max(0, y - 4) : min(h, y + 22)]
        col_hits = band.sum(axis=0)
        xs = np.where(col_hits >= 2)[0]
        if xs.size == 0:
            continue
        cx_band = (int(xs[0]) + int(xs[-1])) / 2.0
        dist_x = abs(cx_band - rel_cursor_x)
        if dist_x > 260:
            continue
        dist_y = abs(y - rel_cursor_y)
        score = int(band.sum()) - dist_y * 10 - dist_x * 4
        if int(xs[0]) < 12 and rel_cursor_x > 90:
            score -= 250
        if score > best_score:
            best_score = score
            best_row = y

    if best_row < 0:
        return None

    band = mask[max(0, best_row - 5) : min(h, best_row + 24)]
    col_hits = band.sum(axis=0)
    xs = np.where(col_hits >= 3)[0]
    if xs.size == 0:
        return None

    x0 = max(0, int(xs[0]) - 6)
    x1 = min(w, int(xs[-1]) + 8)
    y0 = max(0, best_row - 8)
    y1 = min(h, best_row + 30)
    if x1 - x0 < 24 or y1 - y0 < 12:
        return None
    return (x0, y0, x1, y1)


def find_orange_title_near_cursor(
    monitor_index: int,
    cursor_x: int,
    cursor_y: int,
    mon_width: int,
    mon_height: int,
    *,
    pad_left: int = 40,
    pad_right: int = 560,
    pad_up: int = 120,
    pad_down: int = 80,
) -> tuple[tuple[int, int, int, int] | None, bool]:
    left = max(0, cursor_x - pad_left)
    top = max(0, cursor_y - pad_up)
    right = min(mon_width, cursor_x + pad_right)
    bottom = min(mon_height, cursor_y + pad_down)
    if right <= left + 40 or bottom <= top + 24:
        return None, False

    image = grab_region(monitor_index, (left, top, right, bottom))
    if image is None:
        return None, False

    rel = _find_orange_title_in_image(
        image,
        rel_cursor_x=cursor_x - left,
        rel_cursor_y=cursor_y - top,
    )
    if rel is None:
        return None, False

    x0, y0, x1, y1 = rel
    return (left + x0, top + y0, left + x1, top + y1), True


def find_tooltip_region(cfg: dict) -> tuple[tuple[int, int, int, int] | None, str]:
    """
    Return tooltip title crop (L,T,R,B) and detection method:
    orange | green | cursor
    """
    monitor_index = int(cfg.get("monitor_index", 1))
    mon = resolve_monitor(monitor_index)
    if not mon:
        return None, "none"

    cx, cy = get_cursor_pos()
    cursor_x = cx - mon.left
    cursor_y = cy - mon.top

    capture_cfg = cfg.get("item_tooltip_capture") or {}
    from_ind = cfg.get("item_tooltip_from_indicator") or {}
    dx = int(from_ind.get("dx", capture_cfg.get("dx", 24)))
    dy = int(from_ind.get("dy", capture_cfg.get("dy", -88)))
    width = int(from_ind.get("w", capture_cfg.get("w", 480)))
    height = int(from_ind.get("h", capture_cfg.get("h", 56)))
    max_dist = int(from_ind.get("max_cursor_dist", 320))

    region, ok = find_orange_title_near_cursor(
        monitor_index,
        cursor_x,
        cursor_y,
        mon.width,
        mon.height,
    )
    if ok and region and region[2] > region[0] and region[3] > region[1]:
        return region, "orange"

    screen = grab_monitor(monitor_index)
    indicators = find_green_indicators(screen)
    picked = pick_best_indicator(
        indicators,
        cursor_x=cursor_x,
        cursor_y=cursor_y,
        max_cursor_dist=max_dist,
    )
    if picked:
        region = region_from_indicator(
            picked,
            mon.width,
            mon.height,
            dx=dx,
            dy=dy,
            width=width,
            height=height,
        )
        if region[2] > region[0] and region[3] > region[1]:
            return region, "green"

    left = max(0, cursor_x + dx)
    top = max(0, cursor_y + dy)
    right = min(mon.width, left + width)
    bottom = min(mon.height, top + height)
    if right <= left + 8 or bottom <= top + 8:
        return None, "none"
    return (left, top, right, bottom), "cursor"
