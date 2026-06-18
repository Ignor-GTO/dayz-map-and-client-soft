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
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

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
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class _INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("mi", _MOUSEINPUT)]

        _anonymous_ = ("u",)
        _fields_ = [("type", ctypes.c_ulong), ("u", _U)]

    _EXTRA = ctypes.c_ulong(0)

    def get_cursor_pos() -> tuple[int, int]:
        pt = _POINT()
        if not user32.GetCursorPos(ctypes.byref(pt)):
            return 0, 0
        return int(pt.x), int(pt.y)

    def _virtual_screen() -> tuple[int, int, int, int]:
        return (
            int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN)),
            int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN)),
            int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)),
            int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)),
        )

    def _sendinput_absolute(x: int, y: int) -> None:
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
            dwExtraInfo=ctypes.pointer(_EXTRA),
        )
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))

    def _move_steps(cx: int, cy: int, tx: int, ty: int, steps: int = 40) -> None:
        for i in range(1, steps + 1):
            t = i / steps
            nx = int(cx + (tx - cx) * t)
            ny = int(cy + (ty - cy) * t)
            user32.SetCursorPos(nx, ny)
            time.sleep(0.003)

    def move_cursor_to(x: int, y: int, tolerance: int = 10) -> tuple[int, int]:
        """Try several strategies — games/fullscreen often block instant warp."""
        user32.ClipCursor(None)
        tx, ty = int(x), int(y)

        if hasattr(user32, "SetPhysicalCursorPos"):
            try:
                user32.SetPhysicalCursorPos(tx, ty)
                time.sleep(0.02)
                ax, ay = get_cursor_pos()
                if abs(ax - tx) <= tolerance and abs(ay - ty) <= tolerance:
                    return ax, ay
            except Exception:
                pass

        for _ in range(4):
            cx, cy = get_cursor_pos()
            if abs(cx - tx) <= tolerance and abs(cy - ty) <= tolerance:
                return cx, cy

            _move_steps(cx, cy, tx, ty)
            time.sleep(0.02)
            cx, cy = get_cursor_pos()
            if abs(cx - tx) <= tolerance and abs(cy - ty) <= tolerance:
                return cx, cy

            rdx, rdy = tx - cx, ty - cy
            user32.mouse_event(MOUSEEVENTF_MOVE, rdx, rdy, 0, 0)
            time.sleep(0.02)
            cx, cy = get_cursor_pos()
            if abs(cx - tx) <= tolerance and abs(cy - ty) <= tolerance:
                return cx, cy

            _sendinput_absolute(tx, ty)
            user32.SetCursorPos(tx, ty)
            time.sleep(0.02)

        return get_cursor_pos()

    def inject_mouse_hover(screen_x: int, screen_y: int) -> None:
        """Send WM_MOUSEMOVE to the window under the point (works when game traps cursor)."""
        WM_MOUSEMOVE = 0x0200
        pt = _POINT(screen_x, screen_y)
        hwnd = user32.WindowFromPoint(pt)
        if not hwnd:
            return
        seen: set[int] = set()
        for _ in range(12):
            if hwnd in seen:
                break
            seen.add(hwnd)
            client = _POINT(screen_x, screen_y)
            if user32.ScreenToClient(hwnd, ctypes.byref(client)):
                lparam = (client.y << 16) | (client.x & 0xFFFF)
                user32.SendMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
            child = user32.ChildWindowFromPoint(hwnd, pt)
            if not child or child == hwnd:
                break
            hwnd = child

    def set_cursor_pos(x: int, y: int) -> bool:
        ax, ay = move_cursor_to(x, y)
        return abs(ax - int(x)) <= 15 and abs(ay - int(y)) <= 15

else:

    def get_cursor_pos() -> tuple[int, int]:
        return 0, 0

    def move_cursor_to(x: int, y: int, tolerance: int = 10) -> tuple[int, int]:
        return 0, 0

    def inject_mouse_hover(screen_x: int, screen_y: int) -> None:
        return None

    def set_cursor_pos(x: int, y: int) -> bool:
        return False


def nudge_mouse_for_coordinates(
    monitor_index: int,
    ocr_region: tuple[int, int, int, int],
    *,
    side: NudgeSide = "left",
    edge_offset: int = 8,
) -> tuple[tuple[int, int], tuple[int, int]]:
    """Move cursor to the left edge of the selected monitor. Returns (target, actual)."""
    from capture import resolve_monitor

    mon = resolve_monitor(monitor_index)
    if not mon:
        return (0, 0), get_cursor_pos()

    _left, top, _right, bottom = ocr_region
    y_center = mon.top + int(mon.height * 0.5)

    if side == "left":
        tx = mon.left + max(4, edge_offset)
        ty = y_center
    else:
        margin = max(80, min(220, mon.width // 8))
        tx = mon.left + mon.width - margin
        ty = mon.top + max(0, (top + bottom) // 2)

    actual = move_cursor_to(tx, ty)
    inject_mouse_hover(tx, ty)
    time.sleep(0.05)
    return (tx, ty), actual


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
    check_cancel: Callable[[], bool] | None = None,
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
        if check_cancel and check_cancel():
            return

        target, actual = nudge_mouse_for_coordinates(
            monitor_index, ocr_region, side=side, edge_offset=edge_offset
        )
        if on_nudged:
            on_nudged(target, saved, actual)

        if check_cancel and check_cancel():
            return

        if delay_ms > 0:
            # Sleep in 40ms chunks to respond to cancellation quickly
            chunk = 0.04
            slept = 0.0
            total = delay_ms / 1000.0
            while slept < total:
                if check_cancel and check_cancel():
                    return
                time.sleep(min(chunk, total - slept))
                slept += chunk

        if check_cancel and check_cancel():
            return

        action()
    finally:
        if restore:
            time.sleep(0.05)
            move_cursor_to(saved[0], saved[1])
