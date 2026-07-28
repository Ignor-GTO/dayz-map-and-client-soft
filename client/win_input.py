"""Send Ctrl+C via Win32 SendInput (avoids keyboard-library deadlock with hooks)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes


ULONG_PTR = ctypes.c_size_t


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


def _key(vk: int, flags: int = 0) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki = KEYBDINPUT(vk, 0, flags, 0, 0)
    return inp


def send_ctrl_c() -> None:
    """Inject Ctrl+C into the foreground window."""
    user32 = ctypes.windll.user32
    seq = (INPUT * 4)(
        _key(VK_CONTROL),
        _key(VK_C),
        _key(VK_C, KEYEVENTF_KEYUP),
        _key(VK_CONTROL, KEYEVENTF_KEYUP),
    )
    sent = user32.SendInput(4, ctypes.byref(seq), ctypes.sizeof(INPUT))
    if sent != 4:
        raise OSError(f"SendInput returned {sent}, expected 4")
