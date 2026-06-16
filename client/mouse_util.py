"""Move mouse to reveal iZurvive coordinates before OCR (Windows)."""

from __future__ import annotations

import sys
import time
from typing import Callable, Literal

NudgeSide = Literal["left", "right"]

if sys.platform == "win32":
    import ctypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)

    class _POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    def get_cursor_pos() -> tuple[int, int]:
        pt = _POINT()
        if not user32.GetCursorPos(ctypes.byref(pt)):
            return 0, 0
        return int(pt.x), int(pt.y)

    def set_cursor_pos(x: int, y: int) -> None:
        user32.SetCursorPos(int(x), int(y))

else:

    def get_cursor_pos() -> tuple[int, int]:
        return 0, 0

    def set_cursor_pos(x: int, y: int) -> None:
        return None


def nudge_mouse_for_coordinates(
    monitor_index: int,
    ocr_region: tuple[int, int, int, int],
    *,
    side: NudgeSide = "right",
) -> tuple[int, int] | None:
    """Move cursor to the map area so iZurvive keeps coordinates visible."""
    from capture import resolve_monitor

    mon = resolve_monitor(monitor_index)
    if not mon:
        return None

    _left, top, _right, bottom = ocr_region
    margin = max(80, min(220, mon.width // 8))
    if side == "right":
        x = mon.left + mon.width - margin
    else:
        x = mon.left + margin
    y = mon.top + max(0, (top + bottom) // 2)
    set_cursor_pos(x, y)
    return x, y


def with_mouse_nudge(
    monitor_index: int,
    ocr_region: tuple[int, int, int, int],
    action: Callable[[], None],
    *,
    enabled: bool = True,
    side: NudgeSide = "right",
    delay_ms: int = 350,
    restore: bool = True,
    on_nudged: Callable[[tuple[int, int]], None] | None = None,
) -> None:
    """Run action after optionally moving the mouse away from the sidebar."""
    if not enabled or sys.platform != "win32":
        action()
        return

    saved = get_cursor_pos()
    try:
        target = nudge_mouse_for_coordinates(monitor_index, ocr_region, side=side)
        if target and on_nudged:
            on_nudged(target)
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)
        action()
    finally:
        if restore:
            time.sleep(0.05)
            set_cursor_pos(*saved)
