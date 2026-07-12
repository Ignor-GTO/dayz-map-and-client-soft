"""On-screen debug frames for inventory tooltip OCR capture."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from capture import list_monitors

_SEARCH_COLOR = "#00d4ff"
_PRIMARY_COLOR = "#00ff66"
_CANDIDATE_COLOR = "#ffcc00"


class TooltipDebugOverlay:
    def __init__(self, root: tk.Tk, monitor_index_getter: Callable[[], int]) -> None:
        self.root = root
        self.monitor_index_getter = monitor_index_getter
        self._win: tk.Toplevel | None = None
        self._canvas: tk.Canvas | None = None

    def _monitor(self):
        idx = self.monitor_index_getter()
        monitors = list_monitors()
        return next((m for m in monitors if m.index == idx), monitors[0] if monitors else None)

    def _ensure(self) -> None:
        if self._win and self._win.winfo_exists():
            return
        mon = self._monitor()
        if not mon:
            return
        self._win = tk.Toplevel(self.root)
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        self._win.geometry(f"{mon.width}x{mon.height}+{mon.left}+{mon.top}")
        self._win.configure(bg="#000000")
        try:
            self._win.attributes("-alpha", 0.35)
        except tk.TclError:
            pass
        try:
            self._win.attributes("-transparentcolor", "#000000")
        except tk.TclError:
            pass

        self._canvas = tk.Canvas(
            self._win,
            width=mon.width,
            height=mon.height,
            bg="#000000",
            highlightthickness=0,
            bd=0,
        )
        self._canvas.pack(fill="both", expand=True)

    def show(
        self,
        search: tuple[int, int, int, int] | None,
        regions: list[tuple[int, int, int, int]],
    ) -> None:
        if not regions and search is None:
            self.hide()
            return
        self._ensure()
        if not self._canvas or not self._win:
            return
        try:
            self._win.deiconify()
        except tk.TclError:
            pass
        self._canvas.delete("all")

        if search is not None:
            l, t, r, b = search
            self._canvas.create_rectangle(
                l,
                t,
                r,
                b,
                outline=_SEARCH_COLOR,
                width=2,
                dash=(8, 6),
            )

        for idx, box in enumerate(regions[:6]):
            l, t, r, b = box
            color = _PRIMARY_COLOR if idx == 0 else _CANDIDATE_COLOR
            width = 3 if idx == 0 else 2
            self._canvas.create_rectangle(l, t, r, b, outline=color, width=width)

    def hide(self) -> None:
        if self._win is not None:
            try:
                self._win.withdraw()
            except tk.TclError:
                pass
        if self._canvas is not None:
            self._canvas.delete("all")

    def destroy(self) -> None:
        if self._win is not None:
            try:
                self._win.destroy()
            except tk.TclError:
                pass
        self._win = None
        self._canvas = None
