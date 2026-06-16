"""Map session: first M sends player position, double-click sends marker, second M closes."""

from __future__ import annotations

import sys
import threading
import time
from typing import Callable

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    WH_MOUSE_LL = 14
    WM_LBUTTONDOWN = 0x0201

    class _POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class _MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("pt", _POINT),
            ("mouseData", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    _LRESULT = ctypes.c_long
    _HOOKPROC = ctypes.CFUNCTYPE(_LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

    class DoubleClickListener:
        """Low-level mouse hook: fires callback on left double-click."""

        def __init__(self) -> None:
            self._callback: Callable[[], None] | None = None
            self._hook: ctypes.c_void_p | None = None
            self._proc: _HOOKPROC | None = None
            self._thread: threading.Thread | None = None
            self._stop = threading.Event()
            self._last_down = 0.0
            self._last_pos = (0, 0)

        def start(self, callback: Callable[[], None]) -> None:
            if self._thread and self._thread.is_alive():
                self._callback = callback
                return
            self._callback = callback
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="dblclick-hook", daemon=True)
            self._thread.start()

        def stop(self) -> None:
            self._stop.set()
            if self._hook:
                user32.UnhookWindowsHookEx(self._hook)
                self._hook = None

        def _on_lbutton_down(self, x: int, y: int) -> None:
            now = time.monotonic()
            lx, ly = self._last_pos
            if now - self._last_down < 0.45 and abs(x - lx) < 12 and abs(y - ly) < 12:
                self._last_down = 0.0
                cb = self._callback
                if cb:
                    cb()
                return
            self._last_down = now
            self._last_pos = (x, y)

        def _run(self) -> None:
            listener = self

            @_HOOKPROC
            def hook_proc(n_code: int, w_param: int, l_param: int) -> int:
                if n_code >= 0 and w_param == WM_LBUTTONDOWN and not listener._stop.is_set():
                    info = ctypes.cast(l_param, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
                    listener._on_lbutton_down(int(info.pt.x), int(info.pt.y))
                hook = listener._hook or 0
                return user32.CallNextHookEx(hook, n_code, w_param, l_param)

            self._proc = hook_proc
            self._hook = user32.SetWindowsHookExW(
                WH_MOUSE_LL,
                self._proc,
                kernel32.GetModuleHandleW(None),
                0,
            )
            if not self._hook:
                return

            msg = wintypes.MSG()
            while not self._stop.is_set():
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                time.sleep(0.02)

            if self._hook:
                user32.UnhookWindowsHookEx(self._hook)
                self._hook = None

else:

    class DoubleClickListener:
        def start(self, callback: Callable[[], None]) -> None:
            return None

        def stop(self) -> None:
            return None
