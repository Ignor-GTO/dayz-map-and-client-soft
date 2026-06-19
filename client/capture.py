from __future__ import annotations

import sys
from dataclasses import dataclass

import mss
from PIL import Image

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", wintypes.DWORD),
            ("szDevice", wintypes.WCHAR * 32),
        ]

    MONITORINFOF_PRIMARY = 1

    def _enum_win_monitors() -> list[dict]:
        found: list[dict] = []

        def callback(hmonitor, _hdc, _rect, _ldata):
            info = MONITORINFOEXW()
            info.cbSize = ctypes.sizeof(MONITORINFOEXW)
            if not user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                return 1
            r = info.rcMonitor
            found.append(
                {
                    "left": int(r.left),
                    "top": int(r.top),
                    "width": int(r.right - r.left),
                    "height": int(r.bottom - r.top),
                    "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
                }
            )
            return 1

        proc = ctypes.WINFUNCTYPE(
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.POINTER(RECT),
            ctypes.c_longlong,
        )(callback)
        user32.EnumDisplayMonitors(None, None, proc, 0)
        return found

else:

    def _enum_win_monitors() -> list[dict]:
        return []


@dataclass
class MonitorInfo:
    index: int
    label: str
    left: int
    top: int
    width: int
    height: int
    primary: bool = False


def _sort_monitors(raw: list[dict]) -> list[dict]:
    """Primary first, then left-to-right, top-to-bottom (Windows display order)."""
    return sorted(raw, key=lambda m: (not m["primary"], m["left"], m["top"]))


def _list_from_mss() -> list[dict]:
    with mss.mss() as sct:
        return [
            {
                "left": int(mon["left"]),
                "top": int(mon["top"]),
                "width": int(mon["width"]),
                "height": int(mon["height"]),
                "primary": mon["left"] == 0 and mon["top"] == 0,
            }
            for mon in sct.monitors[1:]
        ]


def list_monitors() -> list[MonitorInfo]:
    raw = _enum_win_monitors()
    if not raw:
        raw = _list_from_mss()
    raw = _sort_monitors(raw)

    items: list[MonitorInfo] = []
    for i, mon in enumerate(raw, start=1):
        primary_tag = " · основной" if mon["primary"] else ""
        items.append(
            MonitorInfo(
                index=i,
                label=f"Монитор {i}{primary_tag} ({mon['width']}x{mon['height']})",
                left=mon["left"],
                top=mon["top"],
                width=mon["width"],
                height=mon["height"],
                primary=mon["primary"],
            )
        )
    return items


def resolve_monitor(monitor_index: int) -> MonitorInfo | None:
    monitors = list_monitors()
    if not monitors:
        return None
    if monitor_index < 1 or monitor_index > len(monitors):
        return monitors[0]
    return monitors[monitor_index - 1]


def grab_monitor(monitor_index: int) -> Image.Image:
    mon = resolve_monitor(monitor_index)
    if not mon:
        raise RuntimeError("No monitors found")
    with mss.mss() as sct:
        shot = sct.grab(
            {
                "left": mon.left,
                "top": mon.top,
                "width": mon.width,
                "height": mon.height,
            }
        )
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def grab_region(monitor_index: int, region: tuple[int, int, int, int]) -> Image.Image:
    mon = resolve_monitor(monitor_index)
    if not mon:
        raise RuntimeError("No monitors found")
    left, top, right, bottom = region
    with mss.mss() as sct:
        bbox = {
            "left": mon.left + left,
            "top": mon.top + top,
            "width": max(1, right - left),
            "height": max(1, bottom - top),
        }
        shot = sct.grab(bbox)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
