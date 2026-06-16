"""Interactive on-screen OCR region editor with live preview."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from capture import list_monitors

BORDER = "#ff3366"
FILL = BORDER
HANDLE = 8
MIN_SIZE = 24


class OcrRegionEditor:
    def __init__(
        self,
        root: tk.Tk,
        monitor_index_getter: Callable[[], int],
        region_vars: list[tk.IntVar],
    ) -> None:
        self.root = root
        self.monitor_index_getter = monitor_index_getter
        self.region_vars = region_vars
        self.active = False
        self._win: tk.Toplevel | None = None
        self._canvas: tk.Canvas | None = None
        self._traces: list[tuple[tk.Variable, str]] = []
        self._mutating = False
        self._drag_mode: str | None = None
        self._drag_origin: tuple[int, int, int, int, int, int] | None = None

    def toggle(self) -> bool:
        if self.active:
            self.stop()
            return False
        self.start()
        return True

    def start(self) -> None:
        if self.active:
            return
        mon = self._monitor()
        if not mon:
            return
        self.active = True
        self._win = tk.Toplevel(self.root)
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        self._win.geometry(f"{mon.width}x{mon.height}+{mon.left}+{mon.top}")
        self._win.configure(bg="#000000")
        try:
            self._win.attributes("-alpha", 0.25)
        except tk.TclError:
            pass

        self._canvas = tk.Canvas(
            self._win,
            width=mon.width,
            height=mon.height,
            bg="#000000",
            highlightthickness=0,
            bd=0,
            cursor="crosshair",
        )
        self._canvas.pack(fill="both", expand=True)
        self._canvas.bind("<Button-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._win.bind("<Escape>", lambda _e: self.stop())

        for var in self.region_vars:
            tid = var.trace_add("write", self._on_vars_changed)
            self._traces.append((var, tid))

        self._redraw()

    def stop(self) -> None:
        self.active = False
        for var, tid in self._traces:
            try:
                var.trace_remove("write", tid)
            except tk.TclError:
                pass
        self._traces.clear()
        if self._win is not None:
            try:
                self._win.destroy()
            except tk.TclError:
                pass
        self._win = None
        self._canvas = None

    def _monitor(self):
        monitors = list_monitors()
        idx = self.monitor_index_getter()
        return next((m for m in monitors if m.index == idx), monitors[0] if monitors else None)

    def _region(self) -> tuple[int, int, int, int]:
        return tuple(int(v.get()) for v in self.region_vars)

    def _set_region(self, left: int, top: int, right: int, bottom: int) -> None:
        mon = self._monitor()
        if not mon:
            return
        left = max(0, min(mon.width - MIN_SIZE, left))
        top = max(0, min(mon.height - MIN_SIZE, top))
        right = max(left + MIN_SIZE, min(mon.width, right))
        bottom = max(top + MIN_SIZE, min(mon.height, bottom))
        self._mutating = True
        self.region_vars[0].set(left)
        self.region_vars[1].set(top)
        self.region_vars[2].set(right)
        self.region_vars[3].set(bottom)
        self._mutating = False
        self._redraw()

    def _on_vars_changed(self, *_args) -> None:
        if self._mutating or not self.active:
            return
        self._redraw()

    def _redraw(self) -> None:
        if not self._canvas:
            return
        left, top, right, bottom = self._region()
        if right <= left or bottom <= top:
            return
        c = self._canvas
        c.delete("all")
        c.create_rectangle(left, top, right, bottom, outline=BORDER, width=3)
        try:
            c.create_rectangle(left + 2, top + 2, right - 2, bottom - 2, fill=FILL, stipple="gray25", outline="")
        except tk.TclError:
            pass
        c.create_rectangle(left, top, right, bottom, outline="#ffffff", width=1)
        for hx, hy in self._handles(left, top, right, bottom):
            c.create_rectangle(
                hx - HANDLE // 2,
                hy - HANDLE // 2,
                hx + HANDLE // 2,
                hy + HANDLE // 2,
                fill="#ffffff",
                outline=BORDER,
                width=2,
            )
        c.create_text(
            left + 6,
            max(0, top - 18),
            text=f"L{left} T{top}  R{right} B{bottom}",
            fill="#ffffff",
            anchor="nw",
            font=("Segoe UI", 10, "bold"),
        )

    @staticmethod
    def _handles(left: int, top: int, right: int, bottom: int) -> list[tuple[int, int]]:
        mx = (left + right) // 2
        my = (top + bottom) // 2
        return [
            (left, top),
            (mx, top),
            (right, top),
            (right, my),
            (right, bottom),
            (mx, bottom),
            (left, bottom),
            (left, my),
        ]

    def _hit_test(self, x: int, y: int) -> str:
        left, top, right, bottom = self._region()
        hs = HANDLE + 4
        modes = ["nw", "n", "ne", "e", "se", "s", "sw", "w"]
        for (hx, hy), mode in zip(self._handles(left, top, right, bottom), modes):
            if abs(x - hx) <= hs and abs(y - hy) <= hs:
                return mode
        if left <= x <= right and top <= y <= bottom:
            return "move"
        return ""

    def _on_press(self, event: tk.Event) -> None:
        mode = self._hit_test(event.x, event.y)
        if not mode:
            return
        self._drag_mode = mode
        l, t, r, b = self._region()
        self._drag_origin = (event.x, event.y, l, t, r, b)

    def _on_drag(self, event: tk.Event) -> None:
        if not self._drag_mode or not self._drag_origin:
            return
        ox, oy, l, t, r, b = self._drag_origin
        dx = event.x - ox
        dy = event.y - oy
        mode = self._drag_mode

        if mode == "move":
            w, h = r - l, b - t
            self._set_region(l + dx, t + dy, l + dx + w, t + dy + h)
            return

        nl, nt, nr, nb = l, t, r, b
        if "w" in mode:
            nl = l + dx
        if "e" in mode:
            nr = r + dx
        if "n" in mode:
            nt = t + dy
        if "s" in mode:
            nb = b + dy
        self._set_region(nl, nt, nr, nb)

    def _on_release(self, _event: tk.Event) -> None:
        self._drag_mode = None
        self._drag_origin = None
