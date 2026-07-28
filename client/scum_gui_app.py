"""SCUM Map Client — M hotkey + auto position every 30s (OCR / clipboard)."""

from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from api_client import MapClient
from clipboard_util import grab_clipboard_text
from config import load_config, save_config
from scum_capture import DEFAULT_SCUM_OCR_REGION, normalize_region, ocr_scum_coords
from scum_coords import parse_scum_clipboard

try:
    import keyboard
except Exception:  # pragma: no cover
    keyboard = None

AUTO_INTERVAL_SEC = 30


class ScumMapApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("SCUM Map Client")
        self.geometry("560x520")
        self.minsize(520, 460)

        self.settings = load_config()
        self.map_client: MapClient | None = None
        self._hotkeys_on = False
        self._stop_workers = threading.Event()
        self._last_sent: tuple[float, float] | None = None
        self._send_lock = threading.Lock()

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 6}
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="SCUM Map Client", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(
            frm,
            text=(
                "В игре: F1 → show position (оставьте включённым).\n"
                "Клиент читает координаты с экрана по M и каждые 30 секунд автоматически."
            ),
            wraplength=520,
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

        region = normalize_region(self.settings.get("scum_ocr_region") or DEFAULT_SCUM_OCR_REGION)
        reg_frm = ttk.LabelFrame(frm, text="Область OCR show position (L T R B)", padding=8)
        reg_frm.pack(fill="x", **pad)
        self.region_vars = [tk.IntVar(value=v) for v in region]
        for i, label in enumerate(("L", "T", "R", "B")):
            cell = ttk.Frame(reg_frm)
            cell.pack(side="left", padx=4)
            ttk.Label(cell, text=label).pack(side="left")
            ttk.Entry(cell, textvariable=self.region_vars[i], width=7).pack(side="left", padx=2)

        btns = ttk.Frame(frm)
        btns.pack(fill="x", **pad)
        ttk.Button(btns, text="Сохранить", command=self._save).pack(side="left")
        self.toggle_btn = ttk.Button(btns, text="Запустить", command=self._toggle_hotkeys)
        self.toggle_btn.pack(side="left", padx=8)
        ttk.Button(btns, text="Тест OCR", command=self._test_ocr).pack(side="left")

        self.status_var = tk.StringVar(value="Остановлено")
        ttk.Label(frm, textvariable=self.status_var).pack(anchor="w", **pad)

        ttk.Label(frm, text="Лог").pack(anchor="w")
        self.log = tk.Text(frm, height=12, wrap="word")
        self.log.pack(fill="both", expand=True)

        tip = (
            "M — отправить позицию сейчас · авто каждые 30 с · Ctrl+C в буфер тоже подхватится.\n"
            "Войдите на веб-карту SCUM Island и вставьте client key."
        )
        ttk.Label(frm, text=tip, wraplength=520, foreground="#555").pack(anchor="w", pady=(8, 0))

    def log_line(self, text: str) -> None:
        self.log.insert("end", text + "\n")
        self.log.see("end")

    def _current_region(self) -> tuple[int, int, int, int]:
        return normalize_region([v.get() for v in self.region_vars])

    def _save(self) -> None:
        server = self.server_var.get().strip()
        key = self.key_var.get().strip()
        if not server or not key:
            messagebox.showerror("Ошибка", "Укажите server URL и client key")
            return
        self.settings["server_url"] = server
        self.settings["client_key"] = key
        self.settings["map_slug"] = "scum"
        self.settings["scum_ocr_region"] = list(self._current_region())
        self.settings["scum_auto_interval_sec"] = AUTO_INTERVAL_SEC
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
        self._stop_workers.clear()
        self._hotkeys_on = True
        self.toggle_btn.configure(text="Остановить")
        self.status_var.set(f"M + авто каждые {AUTO_INTERVAL_SEC} с")
        try:
            keyboard.add_hotkey("m", lambda: self.after(0, lambda: self._capture_and_send("M")))
        except Exception as e:
            self.log_line(f"Hotkey M warn: {e}")
        threading.Thread(target=self._auto_loop, daemon=True).start()
        threading.Thread(target=self._clipboard_loop, daemon=True).start()
        self.log_line(f"Запущено: M и автораз в {AUTO_INTERVAL_SEC} с")

    def _stop_hotkeys(self) -> None:
        self._hotkeys_on = False
        self._stop_workers.set()
        self.toggle_btn.configure(text="Запустить")
        self.status_var.set("Остановлено")
        try:
            if keyboard:
                keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        self.log_line("Остановлено")

    def _auto_loop(self) -> None:
        # First tick after interval; M covers immediate send.
        while not self._stop_workers.wait(AUTO_INTERVAL_SEC):
            self.after(0, lambda: self._capture_and_send("auto-30s"))

    def _clipboard_loop(self) -> None:
        last = None
        while not self._stop_workers.is_set():
            text = grab_clipboard_text()
            digest = (text or "").strip()
            if digest and digest != last:
                coords = parse_scum_clipboard(digest)
                if coords:
                    last = digest
                    self.after(0, lambda c=coords: self._send_coords(c, source="Ctrl+C"))
            time.sleep(0.4)

    def _test_ocr(self) -> None:
        self.log_line("Тест OCR…")
        threading.Thread(target=self._test_ocr_worker, daemon=True).start()

    def _test_ocr_worker(self) -> None:
        try:
            coords, raw = ocr_scum_coords(self._current_region())
        except Exception as exc:
            self.after(0, lambda: self.log_line(f"OCR ошибка: {exc}"))
            return
        preview = (raw or "").replace("\n", " ")[:160]
        if coords:
            self.after(
                0,
                lambda: self.log_line(f"OCR OK → {coords[0]:.1f} / {coords[1]:.1f} | {preview!r}"),
            )
        else:
            self.after(0, lambda: self.log_line(f"OCR: координаты не найдены | {preview!r}"))

    def _capture_and_send(self, source: str) -> None:
        threading.Thread(target=self._capture_worker, args=(source,), daemon=True).start()

    def _capture_worker(self, source: str) -> None:
        coords = None
        detail = ""
        # Prefer clipboard if it already has fresh SCUM coords
        clip = parse_scum_clipboard(grab_clipboard_text())
        if clip:
            coords = clip
            detail = "clipboard"
        else:
            try:
                coords, raw = ocr_scum_coords(self._current_region())
                detail = (raw or "").replace("\n", " ")[:80]
            except Exception as exc:
                self.after(0, lambda: self.log_line(f"[{source}] OCR ошибка: {exc}"))
                return
        if not coords:
            self.after(0, lambda: self.log_line(f"[{source}] нет координат ({detail!r})"))
            return
        self.after(0, lambda c=coords: self._send_coords(c, source=source))

    def _send_coords(self, coords: tuple[float, float], source: str) -> None:
        if not self.map_client:
            self.log_line("Сначала сохраните настройки")
            return
        with self._send_lock:
            x, y = coords
            # Dedup only for auto spam; M always tries (unless identical within 0.5)
            if (
                source.startswith("auto")
                and self._last_sent
                and abs(self._last_sent[0] - x) < 0.5
                and abs(self._last_sent[1] - y) < 0.5
            ):
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
