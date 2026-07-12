"""Top-right overlay for trader item prices."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from capture import list_monitors
from trader_lookup import fmt_price

_BG = "#101820"
_FG = "#e8f0ff"
_TITLE = "#ffb347"
_MUTED = "#9fb0c8"
_NOT_FOUND = "#ffa502"
_BORDER = "#2a3848"


class ItemPriceOverlay:
    def __init__(self, root: tk.Tk, monitor_index_getter: Callable[[], int]) -> None:
        self.root = root
        self.monitor_index_getter = monitor_index_getter
        self._win: tk.Toplevel | None = None
        self._title: tk.Label | None = None
        self._prices: tk.Label | None = None
        self._trader: tk.Label | None = None

    def _monitor(self):
        idx = self.monitor_index_getter()
        monitors = list_monitors()
        return next((m for m in monitors if m.index == idx), monitors[0] if monitors else None)

    def _ensure(self) -> None:
        if self._win and self._win.winfo_exists():
            return
        self._win = tk.Toplevel(self.root)
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        self._win.configure(bg=_BORDER)
        try:
            self._win.attributes("-alpha", 0.94)
        except tk.TclError:
            pass

        outer = tk.Frame(self._win, bg=_BORDER, padx=1, pady=1)
        outer.pack()
        inner = tk.Frame(outer, bg=_BG, padx=12, pady=10)
        inner.pack()

        self._title = tk.Label(
            inner,
            text="",
            font=("Segoe UI", 11, "bold"),
            bg=_BG,
            fg=_TITLE,
            anchor="w",
            justify="left",
        )
        self._title.pack(anchor="w")

        self._prices = tk.Label(
            inner,
            text="",
            font=("Segoe UI", 10),
            bg=_BG,
            fg=_FG,
            anchor="w",
            justify="left",
        )
        self._prices.pack(anchor="w", pady=(4, 0))

        self._trader = tk.Label(
            inner,
            text="",
            font=("Segoe UI", 9),
            bg=_BG,
            fg=_MUTED,
            anchor="w",
            justify="left",
        )
        self._trader.pack(anchor="w", pady=(3, 0))

    def _place(self) -> None:
        if not self._win:
            return
        mon = self._monitor()
        if not mon:
            return
        self._win.update_idletasks()
        w = max(self._win.winfo_reqwidth(), 280)
        h = max(self._win.winfo_reqheight(), 72)
        x = mon.left + mon.width - w - 16
        y = mon.top + 16
        self._win.geometry(f"{w}x{h}+{x}+{y}")

    def show_price(self, name: str, buy_price: int, sell_price: int, trader: str) -> None:
        self._ensure()
        if self._title:
            self._title.configure(text=name, fg=_TITLE)
        if self._prices:
            self._prices.configure(
                text=f"Куп: {fmt_price(buy_price)}  ·  Прод: {fmt_price(sell_price)}",
                fg=_FG,
            )
        if self._trader:
            self._trader.configure(text=trader or "", fg=_MUTED)
        self._place()
        self._win.deiconify()
        self._win.lift()

    def show_not_found(self, name: str) -> None:
        self._ensure()
        if self._title:
            self._title.configure(text=name, fg=_TITLE)
        if self._prices:
            self._prices.configure(text="Цена не найдена", fg=_NOT_FOUND)
        if self._trader:
            self._trader.configure(text="")
        self._place()
        self._win.deiconify()
        self._win.lift()

    def hide(self) -> None:
        if self._win and self._win.winfo_exists():
            self._win.withdraw()

    def destroy(self) -> None:
        if self._win and self._win.winfo_exists():
            self._win.destroy()
        self._win = None
