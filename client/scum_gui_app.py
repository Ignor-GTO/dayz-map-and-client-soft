"""SCUM Map Client — send position from Ctrl+C clipboard coords (no OCR)."""

from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from api_client import MapClient
from clipboard_util import grab_clipboard_text
from config import load_config, save_config
from scum_coords import parse_scum_clipboard

try:
    import keyboard
except Exception:  # pragma: no cover
    keyboard = None


class ScumMapApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("SCUM Map Client")
        self.geometry("520x420")
        self.minsize(480, 380)

        self.settings = load_config()
        self.map_client: MapClient | None = None
        self._hotkeys_on = False
        self._stop_watch = threading.Event()
        self._last_digest: str | None = None
        self._last_sent: tuple[float, float] | None = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 6}
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="SCUM Map Client", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(
            frm,
            text="В игре: F1 → show position → Ctrl+C. Клиент отправит координаты на карту.",
            wraplength=480,
        ).pack(anchor="w", **pad)

        row = ttk.Frame(frm)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="Server URL").pack(anchor="w")
        self.server_var = tk.StringVar(value=self.settings.get("server_url", ""))
        ttk.Entry(row, textvariable=self.server_var).pack(fill="x")

        row2 = ttk.Frame(frm)
        row2.pack(fill="x", **pad)
        ttk.Label(row2, text="Client key").pack(anchor="w")
        self.key_var = tk.StringVar(value=self.settings.get("client_key", ""))
        ttk.Entry(row2, textvariable=self.key_var, show="•").pack(fill="x")

        btns = ttk.Frame(frm)
        btns.pack(fill="x", **pad)
        ttk.Button(btns, text="Сохранить", command=self._save).pack(side="left")
        self.toggle_btn = ttk.Button(btns, text="Запустить hotkeys", command=self._toggle_hotkeys)
        self.toggle_btn.pack(side="left", padx=8)

        self.status_var = tk.StringVar(value="Остановлено")
        ttk.Label(frm, textvariable=self.status_var).pack(anchor="w", **pad)

        ttk.Label(frm, text="Лог").pack(anchor="w")
        self.log = tk.Text(frm, height=12, wrap="word")
        self.log.pack(fill="both", expand=True)

        tip = (
            "Hotkeys: Ctrl+C (авто из буфера) · Ctrl+Shift+V — отправить сейчас из буфера.\n"
            "Войдите на веб-карту SCUM Island, возьмите client key из комнаты."
        )
        ttk.Label(frm, text=tip, wraplength=480, foreground="#555").pack(anchor="w", pady=(8, 0))

    def log_line(self, text: str) -> None:
        self.log.insert("end", text + "\n")
        self.log.see("end")

    def _save(self) -> None:
        server = self.server_var.get().strip()
        key = self.key_var.get().strip()
        if not server or not key:
            messagebox.showerror("Ошибка", "Укажите server URL и client key")
            return
        self.settings["server_url"] = server
        self.settings["client_key"] = key
        self.settings["map_slug"] = "scum"
        save_config(self.settings)
        self.map_client = MapClient(server, key)
        self.log_line("Настройки сохранены")
        self.status_var.set("Готов")

    def _toggle_hotkeys(self) -> None:
        if self._hotkeys_on:
            self._stop_hotkeys()
        else:
            self._start_hotkeys()

    def _start_hotkeys(self) -> None:
        if keyboard is None:
            messagebox.showerror("Ошибка", "Модуль keyboard недоступен")
            return
        if not self.map_client:
            self._save()
            if not self.map_client:
                return
        self._stop_watch.clear()
        self._hotkeys_on = True
        self.toggle_btn.configure(text="Остановить hotkeys")
        self.status_var.set("Слушаю буфер (Ctrl+C)")
        try:
            keyboard.add_hotkey("ctrl+shift+v", lambda: self.after(0, self._send_from_clipboard_now))
        except Exception as e:
            self.log_line(f"Hotkey warn: {e}")
        threading.Thread(target=self._clipboard_loop, daemon=True).start()
        self.log_line("Hotkeys запущены")

    def _stop_hotkeys(self) -> None:
        self._hotkeys_on = False
        self._stop_watch.set()
        self.toggle_btn.configure(text="Запустить hotkeys")
        self.status_var.set("Остановлено")
        try:
            if keyboard:
                keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        self.log_line("Hotkeys остановлены")

    def _clipboard_loop(self) -> None:
        while not self._stop_watch.is_set():
            text = grab_clipboard_text()
            if text:
                digest = text.strip()
                if digest and digest != self._last_digest:
                    coords = parse_scum_clipboard(digest)
                    if coords:
                        self._last_digest = digest
                        self.after(0, lambda c=coords: self._send_coords(c, source="Ctrl+C"))
            time.sleep(0.35)

    def _send_from_clipboard_now(self) -> None:
        text = grab_clipboard_text()
        coords = parse_scum_clipboard(text)
        if not coords:
            self.log_line("В буфере нет SCUM-координат {X=… Y=…}")
            return
        self._send_coords(coords, source="Ctrl+Shift+V")

    def _send_coords(self, coords: tuple[float, float], source: str) -> None:
        if not self.map_client:
            self.log_line("Сначала сохраните настройки")
            return
        x, y = coords
        if self._last_sent and abs(self._last_sent[0] - x) < 0.5 and abs(self._last_sent[1] - y) < 0.5:
            return
        ok, err = self.map_client.send_position(x, y)
        if ok:
            self._last_sent = (x, y)
            self.log_line(f"[{source}] OK → {x:.1f} / {y:.1f}")
            self.status_var.set(f"Позиция {x:.0f} / {y:.0f}")
        else:
            self.log_line(f"[{source}] Ошибка: {err}")

    def _on_close(self) -> None:
        self._stop_hotkeys()
        self.destroy()


def run_scum_gui() -> None:
    app = ScumMapApp()
    app.mainloop()


if __name__ == "__main__":
    run_scum_gui()
