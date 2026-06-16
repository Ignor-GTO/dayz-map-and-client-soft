"""Map session: first M sends player position, double-click sends marker, second M closes."""

from __future__ import annotations

import logging
import sys
import threading
from typing import Callable

logger = logging.getLogger(__name__)

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    WH_MOUSE_LL = 14
    WM_LBUTTONDOWN = 0x0201
    WM_LBUTTONDBLCLK = 0x0203

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

    def _hook_module_handle() -> int:
        if getattr(sys, "frozen", False):
            return kernel32.GetModuleHandleW(None)
        return 0

    class DoubleClickListener:
        """Low-level mouse hook: fires callback on left double-click."""

        def __init__(self) -> None:
            self._callback: Callable[[], None] | None = None
            self._hook: ctypes.c_void_p | None = None
            self._proc: _HOOKPROC | None = None
            self._thread: threading.Thread | None = None
            self._stop = threading.Event()
            self._ready = threading.Event()
            self._hook_ok = False

        @property
        def active(self) -> bool:
            return bool(self._thread and self._thread.is_alive() and self._hook_ok)

        def start(self, callback: Callable[[], None]) -> bool:
            self._callback = callback
            if self._thread and self._thread.is_alive():
                return self._hook_ok
            self._stop.clear()
            self._ready.clear()
            self._hook_ok = False
            self._thread = threading.Thread(target=self._run, name="dblclick-hook", daemon=True)
            self._thread.start()
            self._ready.wait(timeout=2.0)
            return self._hook_ok

        def stop(self) -> None:
            self._stop.set()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=1.5)
            self._thread = None
            self._hook = None
            self._hook_ok = False

        def _on_double_click(self) -> None:
            cb = self._callback
            if cb:
                cb()

        def _run(self) -> None:
            listener = self

            @listener._HOOKPROC
            def hook_proc(n_code: int, w_param: int, l_param: int) -> int:
                if listener._stop.is_set():
                    return 0
                if n_code >= 0 and w_param == WM_LBUTTONDBLCLK:
                    listener._on_double_click()
                hook = listener._hook or 0
                return user32.CallNextHookEx(hook, n_code, w_param, l_param)

            self._proc = hook_proc
            self._hook = user32.SetWindowsHookExW(
                WH_MOUSE_LL,
                self._proc,
                _hook_module_handle(),
                0,
            )
            if not self._hook:
                err = ctypes.get_last_error()
                logger.warning("SetWindowsHookEx failed: %s", err)
                self._ready.set()
                return

            self._hook_ok = True
            self._ready.set()

            msg = wintypes.MSG()
            while not self._stop.is_set():
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result <= 0 or self._stop.is_set():
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            if self._hook:
                user32.UnhookWindowsHookEx(self._hook)
                self._hook = None
            self._hook_ok = False

else:

    class DoubleClickListener:
        def start(self, callback: Callable[[], None]) -> bool:
            return False

        def stop(self) -> None:
            return None

        @property
        def active(self) -> bool:
            return False
