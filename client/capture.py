from __future__ import annotations

from dataclasses import dataclass

import mss
from PIL import Image


@dataclass
class MonitorInfo:
    index: int
    label: str
    left: int
    top: int
    width: int
    height: int


def list_monitors() -> list[MonitorInfo]:
    items: list[MonitorInfo] = []
    with mss.mss() as sct:
        for i, mon in enumerate(sct.monitors[1:], start=1):
            items.append(
                MonitorInfo(
                    index=i,
                    label=f"Монитор {i} ({mon['width']}x{mon['height']})",
                    left=mon["left"],
                    top=mon["top"],
                    width=mon["width"],
                    height=mon["height"],
                )
            )
    return items


def grab_monitor(monitor_index: int) -> Image.Image:
    with mss.mss() as sct:
        if monitor_index < 1 or monitor_index >= len(sct.monitors):
            monitor_index = 1
        shot = sct.grab(sct.monitors[monitor_index])
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def grab_region(monitor_index: int, region: tuple[int, int, int, int]) -> Image.Image:
    left, top, right, bottom = region
    with mss.mss() as sct:
        if monitor_index < 1 or monitor_index >= len(sct.monitors):
            monitor_index = 1
        mon = sct.monitors[monitor_index]
        bbox = {
            "left": mon["left"] + left,
            "top": mon["top"] + top,
            "width": max(1, right - left),
            "height": max(1, bottom - top),
        }
        shot = sct.grab(bbox)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
