"""Win32 input: SendInput, admin check, global RegisterHotKey listener."""

from __future__ import annotations

import ctypes
import os
import sys
import threading
from ctypes import wintypes
from typing import Callable

ULONG_PTR = ctypes.c_size_t

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32

user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wintypes.BOOL


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_C = 0x43
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
HWND_MESSAGE = wintypes.HWND(-3)

# SendInput expects this size; wrong sizeof is a common cause of return 0.
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT

VK_BY_NAME: dict[str, int] = {
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
    "page up": 0x21,
    "pageup": 0x21,
    "pgup": 0x21,
    "page down": 0x22,
    "pagedown": 0x22,
    "pgdn": 0x22,
    "end": 0x23,
    "home": 0x24,
    "insert": 0x2D,
    "delete": 0x2E,
    "m": 0x4D,
    "num lock": 0x90,
    "numlock": 0x90,
}


def _key(vk: int, flags: int = 0) -> INPUT:
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.union.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)
    return inp


def _send_input(seq: ctypes.Array) -> int:
    n = len(seq)
    sent = int(user32.SendInput(n, seq, ctypes.sizeof(INPUT)))
    return sent


def _keybd_event_ctrl_c() -> None:
    """Fallback when SendInput fails (legacy API, still works for many games)."""
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_C, 0, 0, 0)
    user32.keybd_event(VK_C, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def send_ctrl_c() -> None:
    """Send Ctrl+C via SendInput, then always also keybd_event (some games ignore one API)."""
    seq = (INPUT * 4)(
        _key(VK_CONTROL),
        _key(VK_C),
        _key(VK_C, KEYEVENTF_KEYUP),
        _key(VK_CONTROL, KEYEVENTF_KEYUP),
    )
    try:
        _send_input(seq)
    except Exception:
        pass
    # Small gap so the game sees a clean second attempt
    import time

    time.sleep(0.03)
    _keybd_event_ctrl_c()


def send_key(vk: int) -> None:
    seq = (INPUT * 2)(_key(vk), _key(vk, KEYEVENTF_KEYUP))
    sent = _send_input(seq)
    if sent == 2:
        return
    err = int(kernel32.GetLastError())
    try:
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
    except Exception as exc:
        raise OSError(f"SendInput key={sent} lastError={err}; keybd_event failed: {exc}") from exc

def find_window_hwnd(*title_parts: str) -> int:
    """Find first visible top-level window whose title contains any of title_parts."""
    parts = [p.lower() for p in title_parts if p]
    found = ctypes.c_void_p()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        title = (buf.value or "").lower()
        if not title:
            return True
        if any(p in title for p in parts):
            found.value = hwnd
            return False
        return True

    user32.EnumWindows(enum_proc, 0)
    return int(found.value or 0)


def focus_scum_window() -> tuple[bool, str]:
    """Bring SCUM to foreground so Ctrl+C goes to the game. Returns (ok, detail).

    Does NOT use AttachThreadInput — that can deadlock the UI against the game thread.
    """
    hwnd = find_window_hwnd("scum")
    if not hwnd:
        return False, "окно SCUM не найдено"
    fg = user32.GetForegroundWindow()
    if fg == hwnd:
        return True, "SCUM уже в фокусе"
    try:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        # Allow SetForegroundWindow without attaching threads (Alt tap trick)
        VK_MENU = 0x12
        KEYEVENTF_KEYUP = 0x0002
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        ok = bool(user32.SetForegroundWindow(hwnd))
        user32.BringWindowToTop(hwnd)
        now_fg = user32.GetForegroundWindow() == hwnd
        return (ok or now_fg), f"hwnd={hwnd} setfg={ok} now={now_fg}"
    except Exception as exc:
        return False, f"exception: {exc}"


def foreground_title() -> str:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value or ""


def resolve_vk(name: str) -> int | None:
    key = (name or "").strip().lower()
    if not key:
        return None
    if key in VK_BY_NAME:
        return VK_BY_NAME[key]
    if len(key) == 1 and key.isalpha():
        return ord(key.upper())
    if len(key) == 1 and key.isdigit():
        return ord(key)
    return None


def is_key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def is_our_process_foreground() -> bool:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value) == os.getpid()


def is_admin() -> bool:
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """Relaunch current process elevated. Returns True if ShellExecute was called."""
    try:
        if getattr(sys, "frozen", False):
            exe = sys.executable
            params = ""
        else:
            exe = sys.executable
            script = os.path.abspath(sys.argv[0])
            params = f'"{script}"'
        rc = shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        return int(rc) > 32
    except Exception:
        return False


class GlobalHotkeyListener:
    """
    System-wide hotkeys via RegisterHotKey + message-only HWND.
    Works when another window (the game) is focused.
    """

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self._error: str | None = None
        self._bindings: list[tuple[int, str, int]] = []  # id, action, vk
        self._callback: Callable[[str, str], None] | None = None
        self._stop = threading.Event()

    def start(
        self,
        bindings: list[tuple[str, int, str]],
        callback: Callable[[str, str], None],
    ) -> str | None:
        """
        bindings: list of (action, vk, name)
        callback(action, name) called from listener thread — marshal to UI yourself.
        Returns error string or None on success.
        """
        self.stop()
        self._bindings = [(i + 1, action, vk) for i, (action, vk, _name) in enumerate(bindings)]
        self._names = {i + 1: name for i, (_a, _v, name) in enumerate(bindings)}
        self._actions = {i + 1: action for i, (action, _v, _n) in enumerate(bindings)}
        self._callback = callback
        self._stop.clear()
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, daemon=True, name="GlobalHotkeys")
        self._thread.start()
        if not self._ready.wait(timeout=3.0):
            return self._error or "Таймаут запуска глобальных хоткеев"
        return self._error

    def stop(self) -> None:
        self._stop.set()
        tid = self._thread_id
        if tid:
            try:
                user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
            except Exception:
                pass
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=2.0)
        self._thread = None
        self._thread_id = None

    def _run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        # Message-only window
        hwnd = user32.CreateWindowExW(
            0,
            "STATIC",
            "ScumMapHotkeys",
            0,
            0,
            0,
            0,
            0,
            HWND_MESSAGE,
            None,
            None,
            None,
        )
        if not hwnd:
            self._error = f"CreateWindowEx failed ({kernel32.GetLastError()})"
            self._ready.set()
            return

        registered: list[int] = []
        try:
            for hot_id, _action, vk in self._bindings:
                ok = user32.RegisterHotKey(hwnd, hot_id, 0, vk)
                if not ok:
                    err = kernel32.GetLastError()
                    self._error = (
                        f"RegisterHotKey VK=0x{vk:02X} failed (err={err}). "
                        "Клавиша занята другим приложением или нужны права администратора."
                    )
                    self._ready.set()
                    return
                registered.append(hot_id)

            self._ready.set()
            msg = MSG()
            while not self._stop.is_set():
                # Wake periodically so stop() works even without PostThreadMessage
                got = user32.MsgWaitForMultipleObjects(0, None, False, 200, 0x04FF)
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    if msg.message == WM_QUIT:
                        self._stop.set()
                        break
                    if msg.message == WM_HOTKEY:
                        hot_id = int(msg.wParam)
                        action = self._actions.get(hot_id)
                        name = self._names.get(hot_id, "?")
                        if action and self._callback:
                            try:
                                self._callback(action, name)
                            except Exception:
                                pass
                    else:
                        user32.TranslateMessage(ctypes.byref(msg))
                        user32.DispatchMessageW(ctypes.byref(msg))
                if got == 0xFFFFFFFF:
                    break
        finally:
            for hot_id in registered:
                try:
                    user32.UnregisterHotKey(hwnd, hot_id)
                except Exception:
                    pass
            try:
                user32.DestroyWindow(hwnd)
            except Exception:
                pass
