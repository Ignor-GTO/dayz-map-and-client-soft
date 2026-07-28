"""Win32 keyboard helpers: SendInput + GetAsyncKeyState (no keyboard-lib hooks)."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

ULONG_PTR = ctypes.c_size_t

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    _anonymous_ = ("_input",)
    _fields_ = [("type", wintypes.DWORD), ("_input", _INPUT)]


INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_C = 0x43

# Common VK codes for SCUM client hotkeys
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
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki = KEYBDINPUT(vk, 0, flags, 0, 0)
    return inp


def send_ctrl_c() -> None:
    """Inject Ctrl+C into the foreground window."""
    seq = (INPUT * 4)(
        _key(VK_CONTROL),
        _key(VK_C),
        _key(VK_C, KEYEVENTF_KEYUP),
        _key(VK_CONTROL, KEYEVENTF_KEYUP),
    )
    sent = user32.SendInput(4, ctypes.byref(seq), ctypes.sizeof(INPUT))
    if sent != 4:
        raise OSError(f"SendInput returned {sent}, expected 4")


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
    # High bit set => currently pressed
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def is_our_process_foreground() -> bool:
    """True if the foreground window belongs to this process (our Tk UI)."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value) == os.getpid()
