"""On-screen debug frames for inventory tooltip OCR capture."""

from __future__ import annotations

import sys
import tkinter as tk
from typing import Callable

from capture import list_monitors

_SEARCH_COLOR = "#00e5ff"
_PRIMARY_COLOR = "#00ff55"
_CANDIDATE_COLOR = "#ffdd00"
_CURSOR_COLOR = "#ff00ff"
_SHADOW_COLOR = "#000001"
_LABEL_BG = "#101820"


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
        self._last_cursor: tuple[int, int] | None = None

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
        shadow = width + 8
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
        self._canvas.create_rectangle(l, t, r, b, outline="#000000", width=shadow, **kw)
        self._canvas.create_rectangle(l, t, r, b, outline=color, width=width, **kw)
        if label:
            tx = l + 8
            ty = max(4, t - 28)
            tw = max(72, 8 + len(label) * 11)
            self._canvas.create_rectangle(tx - 6, ty - 4, tx + tw, ty + 22, fill=_LABEL_BG, outline=color, width=2)
            self._canvas.create_text(
                tx,
                ty + 9,
                text=label,
                fill=color,
                anchor="w",
                font=("Segoe UI", 12, "bold"),
            )

    def _draw_cursor(self, x: int, y: int) -> None:
        if not self._canvas:
            return
        size = 18
        w = 3
        self._canvas.create_line(x - size, y, x + size, y, fill="#000000", width=w + 4)
        self._canvas.create_line(x, y - size, x, y + size, fill="#000000", width=w + 4)
        self._canvas.create_line(x - size, y, x + size, y, fill=_CURSOR_COLOR, width=w)
        self._canvas.create_line(x, y - size, x, y + size, fill=_CURSOR_COLOR, width=w)
        self._canvas.create_oval(x - 5, y - 5, x + 5, y + 5, outline=_CURSOR_COLOR, width=2)

    def show(
        self,
        search: tuple[int, int, int, int] | None,
        regions: list[tuple[int, int, int, int]],
        cursor: tuple[int, int] | None = None,
    ) -> None:
        if search is not None:
            self._last_search = search
        if regions:
            self._last_regions = list(regions[:6])
        elif search is not None:
            self._last_regions = []
        if cursor is not None:
            self._last_cursor = cursor

        search = search if search is not None else self._last_search
        regions = regions if regions else self._last_regions
        cursor = cursor if cursor is not None else self._last_cursor
        if search is None and not regions and cursor is None:
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
                width=6,
                dash=(12, 8),
                label="ПОИСК",
            )

        if cursor is not None:
            self._draw_cursor(cursor[0], cursor[1])

        if not regions and search is not None:
            cx = (search[0] + search[2]) // 2
            cy = (search[1] + search[3]) // 2
            self._canvas.create_text(
                cx,
                cy,
                text="ЗОН НЕ НАЙДЕНО",
                fill="#ff4444",
                font=("Segoe UI", 16, "bold"),
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
                    width=12,
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
                    width=8,
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
        self._last_cursor = None
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
        self._last_cursor = None
        self._destroy_window()
