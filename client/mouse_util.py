"""Move mouse to reveal iZurvive coordinates before OCR (Windows)."""

from __future__ import annotations

import sys
import time
from typing import Callable

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


def nudge_mouse_for_coordinates(monitor_index: int, ocr_region: tuple[int, int, int, int]) -> None:
    """Move cursor to the left side of the selected monitor (near the OCR strip)."""
    from capture import resolve_monitor

    mon = resolve_monitor(monitor_index)
    if not mon:
        return

    left, top, _right, bottom = ocr_region
    x = mon.left + max(24, min(100, mon.width // 16))
    y = mon.top + max(0, (top + bottom) // 2)
    set_cursor_pos(x, y)


def with_mouse_nudge(
    monitor_index: int,
    ocr_region: tuple[int, int, int, int],
    action: Callable[[], None],
    *,
    enabled: bool = True,
    delay_ms: int = 200,
    restore: bool = True,
) -> None:
    """Run action after optionally moving the mouse away from the map overlay."""
    if not enabled or sys.platform != "win32":
        action()
        return

    saved = get_cursor_pos()
    try:
        nudge_mouse_for_coordinates(monitor_index, ocr_region)
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)
        action()
    finally:
        if restore:
            set_cursor_pos(*saved)
