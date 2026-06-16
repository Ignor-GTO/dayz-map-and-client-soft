"""Fullscreen overlay highlighting the configured OCR capture region."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from capture import list_monitors

BORDER = "#ff3366"
TRANS = "#010101"
DURATION_MS = 6000


def show_ocr_region_overlay(
    monitor_index: int,
    region: tuple[int, int, int, int],
    root: tk.Tk,
    on_close: Callable[[], None] | None = None,
) -> None:
    monitors = list_monitors()
    mon = next((m for m in monitors if m.index == monitor_index), monitors[0] if monitors else None)
    if not mon:
        return

    left, top, right, bottom = region
    w = max(8, right - left)
    h = max(8, bottom - top)
    x = mon.left + left
    y = mon.top + top

    windows: list[tk.Toplevel] = []

    def close() -> None:
        for win in windows:
            try:
                win.destroy()
            except tk.TclError:
                pass
        windows.clear()
        if on_close:
            on_close()

    root.withdraw()

    frame = tk.Toplevel(root)
    frame.overrideredirect(True)
    frame.attributes("-topmost", True)
    try:
        frame.attributes("-transparentcolor", TRANS)
    except tk.TclError:
        pass
    frame.geometry(f"{w}x{h}+{x}+{y}")
    windows.append(frame)

    canvas = tk.Canvas(frame, width=w, height=h, bg=TRANS, highlightthickness=0, bd=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_rectangle(1, 1, w - 1, h - 1, outline=BORDER, width=4)
    canvas.create_rectangle(5, 5, w - 5, h - 5, outline="#ffffff", width=1)
    try:
        canvas.create_rectangle(4, 4, w - 4, h - 4, fill=BORDER, stipple="gray25", outline="")
    except tk.TclError:
        pass

    tag = tk.Toplevel(root)
    tag.overrideredirect(True)
    tag.attributes("-topmost", True)
    tag.configure(bg=BORDER)
    tag.geometry(f"240x26+{x}+{max(mon.top, y - 28)}")
    windows.append(tag)
    tk.Label(
        tag,
        text="OCR область — клик чтобы закрыть",
        bg=BORDER,
        fg="white",
        font=("Segoe UI", 9, "bold"),
        padx=8,
    ).pack(fill="both", expand=True)

    for win in windows:
        win.bind("<Button-1>", lambda _e: close())
        win.bind("<Escape>", lambda _e: close())

    root.after(DURATION_MS, close)
