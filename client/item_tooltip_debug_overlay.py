"""On-screen debug frames for inventory tooltip OCR capture."""

from __future__ import annotations

import sys
import tkinter as tk
from typing import Callable

from capture import list_monitors

_SEARCH_COLOR = "#00e5ff"
_PRIMARY_COLOR = "#00ff55"
_CANDIDATE_COLOR = "#ffdd00"
_SHADOW_COLOR = "#000000"


def _force_topmost(win: tk.Toplevel) -> None:
    try:
        win.attributes("-topmost", False)
        win.attributes("-topmost", True)
        win.lift()
    except tk.TclError:
        return
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        if not hwnd:
            hwnd = win.winfo_id()
        HWND_TOPMOST = -1
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_SHOWWINDOW = 0x0040
        SWP_NOACTIVATE = 0x0010
        ctypes.windll.user32.SetWindowPos(
            hwnd,
            HWND_TOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW | SWP_NOACTIVATE,
        )
    except Exception:
        pass


class TooltipDebugOverlay:
    def __init__(self, root: tk.Tk, monitor_index_getter: Callable[[], int]) -> None:
        self.root = root
        self.monitor_index_getter = monitor_index_getter
        self._win: tk.Toplevel | None = None
        self._canvas: tk.Canvas | None = None
        self._monitor_key: tuple[int, int, int, int] | None = None
        self._last_search: tuple[int, int, int, int] | None = None
        self._last_regions: list[tuple[int, int, int, int]] = []

    def _monitor(self):
        idx = self.monitor_index_getter()
        monitors = list_monitors()
        return next((m for m in monitors if m.index == idx), monitors[0] if monitors else None)

    def _destroy_window(self) -> None:
        if self._win is not None:
            try:
                self._win.destroy()
            except tk.TclError:
                pass
        self._win = None
        self._canvas = None
        self._monitor_key = None

    def _ensure(self) -> None:
        mon = self._monitor()
        if not mon:
            return
        key = (mon.index, mon.left, mon.top, mon.width, mon.height)
        if self._win and self._win.winfo_exists() and self._monitor_key == key:
            return
        self._destroy_window()
        self._monitor_key = key
        self._win = tk.Toplevel(self.root)
        self._win.overrideredirect(True)
        self._win.geometry(f"{mon.width}x{mon.height}+{mon.left}+{mon.top}")
        self._win.configure(bg=_SHADOW_COLOR)
        try:
            self._win.attributes("-transparentcolor", _SHADOW_COLOR)
        except tk.TclError:
            pass
        self._win.attributes("-topmost", True)

        self._canvas = tk.Canvas(
            self._win,
            width=mon.width,
            height=mon.height,
            bg=_SHADOW_COLOR,
            highlightthickness=0,
            bd=0,
        )
        self._canvas.pack(fill="both", expand=True)

    def _draw_outlined_rect(
        self,
        l: int,
        t: int,
        r: int,
        b: int,
        *,
        color: str,
        width: int,
        dash: tuple[int, ...] | None = None,
        fill: str = "",
        label: str = "",
    ) -> None:
        if not self._canvas:
            return
        shadow = width + 6
        kw = {"dash": dash} if dash else {}
        if fill:
            self._canvas.create_rectangle(
                l,
                t,
                r,
                b,
                outline="",
                fill=fill,
                stipple="gray25",
            )
        self._canvas.create_rectangle(
            l,
            t,
            r,
            b,
            outline=_SHADOW_COLOR,
            width=shadow,
            **kw,
        )
        self._canvas.create_rectangle(
            l,
            t,
            r,
            b,
            outline=color,
            width=width,
            **kw,
        )
        if label:
            tx = l + 6
            ty = max(0, t - 24)
            self._canvas.create_rectangle(tx - 4, ty - 2, tx + 8 + len(label) * 9, ty + 18, fill=_SHADOW_COLOR, outline="")
            self._canvas.create_text(
                tx,
                ty + 8,
                text=label,
                fill=color,
                anchor="w",
                font=("Segoe UI", 11, "bold"),
            )

    def show(
        self,
        search: tuple[int, int, int, int] | None,
        regions: list[tuple[int, int, int, int]],
    ) -> None:
        if search is not None:
            self._last_search = search
        if regions:
            self._last_regions = list(regions[:6])

        search = search if search is not None else self._last_search
        regions = regions if regions else self._last_regions
        if search is None and not regions:
            return

        self._ensure()
        if not self._canvas or not self._win:
            return

        self._canvas.delete("all")

        if search is not None:
            l, t, r, b = search
            self._draw_outlined_rect(
                l,
                t,
                r,
                b,
                color=_SEARCH_COLOR,
                width=5,
                dash=(10, 8),
                label="ПОИСК",
            )

        for idx, box in enumerate(regions[:6]):
            l, t, r, b = box
            if idx == 0:
                self._draw_outlined_rect(
                    l,
                    t,
                    r,
                    b,
                    color=_PRIMARY_COLOR,
                    width=10,
                    fill=_PRIMARY_COLOR,
                    label="ЗАХВАТ",
                )
            else:
                self._draw_outlined_rect(
                    l,
                    t,
                    r,
                    b,
                    color=_CANDIDATE_COLOR,
                    width=6,
                    label=f"#{idx + 1}",
                )

        try:
            self._win.deiconify()
        except tk.TclError:
            pass
        self._win.update_idletasks()
        _force_topmost(self._win)

    def raise_topmost(self) -> None:
        if self._win and self._win.winfo_exists():
            _force_topmost(self._win)

    def hide(self) -> None:
        self._last_search = None
        self._last_regions = []
        if self._win is not None:
            try:
                self._win.withdraw()
            except tk.TclError:
                pass
        if self._canvas is not None:
            self._canvas.delete("all")

    def destroy(self) -> None:
        self._last_search = None
        self._last_regions = []
        self._destroy_window()
