"""Move mouse to iZurvive left panel so player coordinates are shown (not map hover)."""

from __future__ import annotations

import sys
import time
from typing import Callable, Literal

NudgeSide = Literal["left", "right"]

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)

    SM_XVIRTUALSCREEN = 76
    SM_YVIRTUALSCREEN = 77
    SM_CXVIRTUALSCREEN = 78
    SM_CYVIRTUALSCREEN = 79
    INPUT_MOUSE = 0
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_ABSOLUTE = 0x8000

    class _POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class _INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("mi", _MOUSEINPUT)]

        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    def get_cursor_pos() -> tuple[int, int]:
        pt = _POINT()
        if not user32.GetCursorPos(ctypes.byref(pt)):
            return 0, 0
        return int(pt.x), int(pt.y)

    def _virtual_screen() -> tuple[int, int, int, int]:
        left = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
        top = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
        width = int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
        height = int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
        return left, top, width, height

    def set_cursor_pos(x: int, y: int) -> bool:
        """Move cursor using SendInput (more reliable than SetCursorPos alone)."""
        x, y = int(x), int(y)
        ok = bool(user32.SetCursorPos(x, y))

        vleft, vtop, vwidth, vheight = _virtual_screen()
        nx = int((x - vleft) * 65535 / max(1, vwidth - 1))
        ny = int((y - vtop) * 65535 / max(1, vheight - 1))

        inp = _INPUT(type=INPUT_MOUSE)
        inp.mi = _MOUSEINPUT(
            dx=nx,
            dy=ny,
            mouseData=0,
            dwFlags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE,
            time=0,
            dwExtraInfo=0,
        )
        sent = int(user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT)))
        ok = ok or sent == 1
        user32.SetCursorPos(x, y)
        return ok

else:

    def get_cursor_pos() -> tuple[int, int]:
        return 0, 0

    def set_cursor_pos(x: int, y: int) -> bool:
        return False


def nudge_mouse_for_coordinates(
    monitor_index: int,
    ocr_region: tuple[int, int, int, int],
    *,
    side: NudgeSide = "left",
    edge_offset: int = 8,
) -> tuple[int, int] | None:
    """Move cursor to the left edge of the selected monitor (iZurvive sidebar)."""
    from capture import resolve_monitor

    mon = resolve_monitor(monitor_index)
    if not mon:
        return None

    _left, top, _right, bottom = ocr_region
    y_center = mon.top + int(mon.height * 0.5)

    if side == "left":
        x = mon.left + max(4, edge_offset)
        y = y_center
    else:
        margin = max(80, min(220, mon.width // 8))
        x = mon.left + mon.width - margin
        y = mon.top + max(0, (top + bottom) // 2)

    set_cursor_pos(x, y)
    return x, y


def with_mouse_nudge(
    monitor_index: int,
    ocr_region: tuple[int, int, int, int],
    action: Callable[[], None],
    *,
    enabled: bool = True,
    side: NudgeSide = "left",
    delay_ms: int = 400,
    restore: bool = True,
    edge_offset: int = 8,
    on_nudged: Callable[[tuple[int, int], tuple[int, int], tuple[int, int]], None] | None = None,
    on_skipped: Callable[[str], None] | None = None,
) -> None:
    """Run OCR after moving the mouse off the map onto the left panel."""
    if not enabled:
        if on_skipped:
            on_skipped("сдвиг отключён в настройках")
        action()
        return

    if sys.platform != "win32":
        if on_skipped:
            on_skipped("только Windows")
        action()
        return

    saved = get_cursor_pos()
    try:
        target = nudge_mouse_for_coordinates(
            monitor_index, ocr_region, side=side, edge_offset=edge_offset
        )
        time.sleep(0.03)
        actual = get_cursor_pos()
        if target and on_nudged:
            on_nudged(target, saved, actual)
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)
        action()
    finally:
        if restore:
            time.sleep(0.08)
            set_cursor_pos(*saved)
