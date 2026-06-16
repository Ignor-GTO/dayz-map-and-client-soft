"""Small always-on-top HUD over the game (map session / OCR status)."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from capture import list_monitors

_BG = "#101820"
_FG = "#e8f0ff"
_OK = "#2ed573"
_WARN = "#ffa502"
_BUSY = "#3d9ee5"
_ERR = "#ff4757"
_ACCENT = "#3d9ee5"


class GameHudOverlay:
    def __init__(self, root: tk.Tk, monitor_index_getter: Callable[[], int]) -> None:
        self.root = root
        self.monitor_index_getter = monitor_index_getter
        self._win: tk.Toplevel | None = None
        self._icon: tk.Label | None = None
        self._text: tk.Label | None = None
        self._hide_job: str | None = None

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
        self._win.configure(bg=_BG)
        try:
            self._win.attributes("-alpha", 0.92)
        except tk.TclError:
            pass

        frame = tk.Frame(self._win, bg=_BG, padx=10, pady=7)
        frame.pack()
        self._icon = tk.Label(frame, text="◎", font=("Segoe UI", 14, "bold"), bg=_BG, fg=_ACCENT)
        self._icon.pack(side="left", padx=(0, 8))
        self._text = tk.Label(frame, text="", font=("Segoe UI", 10), bg=_BG, fg=_FG, justify="left")
        self._text.pack(side="left")

    def _place(self) -> None:
        if not self._win:
            return
        mon = self._monitor()
        if not mon:
            return
        self._win.update_idletasks()
        w = max(self._win.winfo_reqwidth(), 220)
        h = max(self._win.winfo_reqheight(), 40)
        x = mon.left + mon.width - w - 16
        y = mon.top + 16
        self._win.geometry(f"{w}x{h}+{x}+{y}")

    def _cancel_hide(self) -> None:
        if self._hide_job:
            try:
                self.root.after_cancel(self._hide_job)
            except Exception:
                pass
            self._hide_job = None

    def show(self, icon: str, text: str, color: str = _FG, *, auto_hide_ms: int | None = None) -> None:
        self._ensure()
        self._cancel_hide()
        if self._icon:
            self._icon.configure(text=icon, fg=color)
        if self._text:
            self._text.configure(text=text, fg=_FG)
        self._place()
        self._win.deiconify()
        self._win.lift()
        if auto_hide_ms:
            self._hide_job = self.root.after(auto_hide_ms, self.hide)

    def show_busy(self, text: str = "Читаю координаты…") -> None:
        self.show("⟳", text, _BUSY)

    def show_ok(self, x: float, y: float, *, marker: bool = False) -> None:
        kind = "Метка" if marker else "Позиция"
        self.show("✓", f"{kind}: {x:.0f} / {y:.0f}", _OK, auto_hide_ms=2800)

    def show_error(self, text: str) -> None:
        self.show("!", text, _ERR, auto_hide_ms=3500)

    def show_map_session(self) -> None:
        self.show("🗺", "Карта · двойной клик или Ctrl+Shift+D", _WARN)

    def hide(self) -> None:
        self._cancel_hide()
        if self._win and self._win.winfo_exists():
            self._win.withdraw()

    def destroy(self) -> None:
        self._cancel_hide()
        if self._win and self._win.winfo_exists():
            self._win.destroy()
        self._win = None
