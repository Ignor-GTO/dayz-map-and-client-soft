"""Locate DayZ inventory tooltip by green hover circle on full screen."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from capture import grab_monitor, resolve_monitor
from mouse_util import get_cursor_pos


@dataclass
class GreenIndicator:
    cx: int
    cy: int
    area: int
    score: float


def _green_mask(rgb: np.ndarray) -> np.ndarray:
    red = rgb[..., 0].astype(np.int16)
    green = rgb[..., 1].astype(np.int16)
    blue = rgb[..., 2].astype(np.int16)
    # Lime/green hover ring in DayZ inventory (Expansion / vanilla).
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
        # Roughly round blob (not a long UI line).
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


def find_tooltip_region(cfg: dict) -> tuple[tuple[int, int, int, int] | None, bool]:
    """
    Search full monitor for green hover circle, return tooltip crop (L,T,R,B).
    Second value: True if found via green indicator, False if fallback.
    """
    monitor_index = int(cfg.get("monitor_index", 1))
    mon = resolve_monitor(monitor_index)
    if not mon:
        return None, False

    screen = grab_monitor(monitor_index)
    cx, cy = get_cursor_pos()
    cursor_x = cx - mon.left
    cursor_y = cy - mon.top

    capture_cfg = cfg.get("item_tooltip_capture") or {}
    from_ind = cfg.get("item_tooltip_from_indicator") or {}
    dx = int(from_ind.get("dx", capture_cfg.get("dx", 24)))
    dy = int(from_ind.get("dy", capture_cfg.get("dy", -100)))
    width = int(from_ind.get("w", capture_cfg.get("w", 440)))
    height = int(from_ind.get("h", capture_cfg.get("h", 120)))
    max_dist = int(from_ind.get("max_cursor_dist", 320))

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
            return region, True

    # Fallback: fixed offset from cursor (legacy).
    left = max(0, cursor_x + dx)
    top = max(0, cursor_y + dy)
    right = min(mon.width, left + width)
    bottom = min(mon.height, top + height)
    if right <= left + 8 or bottom <= top + 8:
        return None, False
    return (left, top, right, bottom), False
