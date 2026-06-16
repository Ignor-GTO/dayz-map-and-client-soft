import io
import json
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import keyboard
from PIL import ImageGrab

from api_client import MapClient
from capture import grab_region, list_monitors
from config import load_config, save_config
from ocr import extract_coordinates
from region_overlay import OcrRegionEditor
from version import __version__


class ClientApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"DayZ Map Client v{__version__} — GTO Team")
        self.geometry("560x680")
        self.resizable(False, False)

        self.cfg = load_config()
        self.map_client: MapClient | None = None
        self.hotkeys_active = False
        self._clipboard_hash: str | None = None
        self._stop_clipboard = threading.Event()
        self._region_editor: OcrRegionEditor | None = None

        self._build_ui()
        self._load_fields()
        self.log_line(f"[Клиент] v{__version__}")
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 4}
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Сервер").grid(row=0, column=0, sticky="w", **pad)
        self.server_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.server_var, width=52).grid(row=0, column=1, **pad)

        ttk.Label(frm, text="Ключ клиента").grid(row=1, column=0, sticky="w", **pad)
        self.key_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.key_var, width=52, show="*").grid(row=1, column=1, **pad)

        ttk.Label(frm, text="Монитор").grid(row=2, column=0, sticky="w", **pad)
        self.monitor_var = tk.StringVar()
        self.monitor_combo = ttk.Combobox(frm, textvariable=self.monitor_var, state="readonly", width=49)
        self.monitor_combo.grid(row=2, column=1, **pad)
        ttk.Button(frm, text="↻", width=3, command=self._refresh_monitors).grid(
            row=2, column=2, sticky="w", padx=(0, 10)
        )
        self._refresh_monitors()

        ttk.Label(frm, text="OCR область (L,T,R,B)").grid(row=3, column=0, sticky="w", **pad)
        region_frm = ttk.Frame(frm)
        region_frm.grid(row=3, column=1, sticky="w", **pad)
        self.region_vars = [tk.IntVar(value=v) for v in self.cfg.get("ocr_region", [10, 900, 300, 1050])]
        for i, var in enumerate(self.region_vars):
            entry = ttk.Entry(region_frm, textvariable=var, width=8)
            entry.pack(side="left", padx=2)
        self.region_btn = ttk.Button(region_frm, text="Редактор области", command=self.toggle_ocr_region)
        self.region_btn.pack(side="left", padx=6)
        self.monitor_combo.bind("<<ComboboxSelected>>", self._on_monitor_changed)

        btn_frm = ttk.Frame(frm)
        btn_frm.grid(row=4, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frm, text="Сохранить", command=self.save_settings).pack(side="left", padx=5)
        self.start_btn = ttk.Button(btn_frm, text="Запустить hotkeys", command=self.toggle_hotkeys)
        self.start_btn.pack(side="left", padx=5)
        ttk.Button(btn_frm, text="Тест OCR (M)", command=self.test_ocr).pack(side="left", padx=5)
        ttk.Button(btn_frm, text="Проверка OCR", command=self.check_ocr).pack(side="left", padx=5)

        ttk.Label(frm, text="M — live позиция · Win+Shift+S — метка со скриншота").grid(
            row=5, column=0, columnspan=2, **pad
        )

        self.status_var = tk.StringVar(value="Остановлено")
        ttk.Label(frm, textvariable=self.status_var).grid(row=6, column=0, columnspan=2, **pad)

        self.log = scrolledtext.ScrolledText(frm, height=18, width=64, state="disabled")
        self.log.grid(row=7, column=0, columnspan=2, pady=8)

    def _refresh_monitors(self) -> None:
        prev_index = self.monitor_combo.current() if hasattr(self, "monitor_combo") else -1
        monitors = list_monitors()
        self._monitors = monitors
        labels = [m.label for m in monitors]
        self.monitor_combo["values"] = labels
        saved = self.cfg.get("monitor_index", 1)
        if prev_index >= 0 and prev_index < len(labels):
            self.monitor_combo.current(prev_index)
        elif labels:
            idx = min(max(0, saved - 1), len(labels) - 1)
            self.monitor_combo.current(idx)

    def _load_fields(self) -> None:
        self.server_var.set(self.cfg.get("server_url", ""))
        self.key_var.set(self.cfg.get("client_key", ""))

    def log_line(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def save_settings(self) -> None:
        if not self.key_var.get().strip():
            messagebox.showerror("Ошибка", "Укажите ключ клиента")
            return
        monitor_index = self.monitor_combo.current() + 1 if self._monitors else 1
        self.cfg.update(
            {
                "server_url": self.server_var.get().strip(),
                "client_key": self.key_var.get().strip(),
                "monitor_index": monitor_index,
                "ocr_region": [v.get() for v in self.region_vars],
            }
        )
        save_config(self.cfg)
        self.map_client = MapClient(self.cfg["server_url"], self.cfg["client_key"])
        self.log_line("[OK] Настройки сохранены")

    def _monitor_index(self) -> int:
        return self.monitor_combo.current() + 1 if self._monitors else self.cfg.get("monitor_index", 1)

    def _ocr_region(self) -> tuple[int, int, int, int]:
        return tuple(v.get() for v in self.region_vars)

    def _ensure_region_editor(self) -> OcrRegionEditor:
        if self._region_editor is None:
            self._region_editor = OcrRegionEditor(
                self,
                monitor_index_getter=self._monitor_index,
                region_vars=self.region_vars,
            )
        return self._region_editor

    def _on_monitor_changed(self, _event=None) -> None:
        editor = self._region_editor
        if editor and editor.active:
            editor.stop()
            editor.start()

    def toggle_ocr_region(self) -> None:
        try:
            region = self._ocr_region()
            if region[2] <= region[0] or region[3] <= region[1]:
                messagebox.showerror(
                    "Ошибка",
                    "Неверная область: R > L и B > T",
                )
                return
            editor = self._ensure_region_editor()
            opened = editor.toggle()
            self.region_btn.configure(
                text="Закрыть редактор" if opened else "Редактор области"
            )
            if opened:
                self.log_line(
                    "[Редактор] Тяните рамку мышью или меняйте L,T,R,B — Esc закрыть"
                )
        except Exception as exc:
            messagebox.showerror("Область OCR", str(exc))

    def show_ocr_region(self) -> None:
        if not (self._region_editor and self._region_editor.active):
            self.toggle_ocr_region()

    def _show_ocr_error(self, exc: Exception) -> None:
        msg = str(exc)
        self.log_line(f"[OCR] {msg}")
        if messagebox.askyesno("Windows OCR", msg + "\n\nОткрыть параметры языка?"):
            from ocr_engine import open_ocr_language_settings

            open_ocr_language_settings()

    def check_ocr(self) -> None:
        from ocr_engine import get_ocr_engine, list_ocr_languages

        try:
            engine = get_ocr_engine()
            lang = engine.recognizer_language.language_tag
            langs = list_ocr_languages()
            self.log_line(f"[OCR OK] Язык: {lang}")
            if langs:
                self.log_line(f"[OCR OK] Доступно: {', '.join(langs)}")
            messagebox.showinfo("Windows OCR", f"OCR работает.\nЯзык: {lang}")
        except Exception as exc:
            self._show_ocr_error(exc)

    def test_ocr(self) -> None:
        self.save_settings()
        try:
            img = grab_region(self._monitor_index(), self._ocr_region())
            coords = extract_coordinates(img)
            if coords:
                self.log_line(f"[Тест] OCR: {coords[0]:.0f} / {coords[1]:.0f}")
            else:
                self.log_line("[Тест] Координаты не распознаны")
        except Exception as exc:
            messagebox.showerror("OCR", str(exc))

    def toggle_hotkeys(self) -> None:
        if self.hotkeys_active:
            self.stop_hotkeys()
        else:
            self.start_hotkeys()

    def start_hotkeys(self) -> None:
        self.save_settings()
        if not self.map_client:
            return
        from ocr_engine import get_ocr_engine

        try:
            get_ocr_engine()
        except Exception as exc:
            self._show_ocr_error(exc)
            return
        self.hotkeys_active = True
        self.status_var.set("Работает — hotkeys активны")
        self.start_btn.configure(text="Остановить hotkeys")
        keyboard.add_hotkey("m", lambda: self.on_m_pressed())
        self._stop_clipboard.clear()
        threading.Thread(target=self._clipboard_loop, daemon=True).start()
        self.log_line("[Запуск] Hotkeys активны (Windows OCR, без Tesseract)")

    def stop_hotkeys(self) -> None:
        self.hotkeys_active = False
        self._stop_clipboard.set()
        keyboard.unhook_all_hotkeys()
        self.status_var.set("Остановлено")
        self.start_btn.configure(text="Запустить hotkeys")
        self.log_line("[Стоп] Hotkeys отключены")

    def on_m_pressed(self) -> None:
        if not self.map_client:
            return
        try:
            img = grab_region(self._monitor_index(), self._ocr_region())
            coords = extract_coordinates(img)
            if coords:
                x, y = coords
                self.log_line(f"[M] {x:.0f} / {y:.0f}")
                if self.map_client.send_position(x, y):
                    self.log_line("[M] Отправлено на сервер")
            else:
                self.log_line("[M] Координаты не распознаны")
        except Exception as exc:
            self.log_line(f"[M] Ошибка: {exc}")

    def _clipboard_image(self):
        try:
            img = ImageGrab.grabclipboard()
            if img is None:
                return None
            if isinstance(img, list):
                if not img:
                    return None
                from PIL import Image

                img = Image.open(img[0])
            return img
        except Exception:
            return None

    def _clipboard_loop(self) -> None:
        time.sleep(2)
        img = self._clipboard_image()
        if img is not None:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            self._clipboard_hash = str(hash(buf.getvalue()))
        while not self._stop_clipboard.is_set():
            img = self._clipboard_image()
            if img is not None and self.map_client:
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                h = str(hash(buf.getvalue()))
                if h != self._clipboard_hash:
                    self._clipboard_hash = h
                    try:
                        coords = extract_coordinates(img)
                        if coords:
                            x, y = coords
                            self.after(0, lambda: self.log_line(f"[Метка] {x:.0f} / {y:.0f}"))
                            self.map_client.send_marker(x, y)
                    except Exception as exc:
                        self.after(0, lambda: self.log_line(f"[Метка] Ошибка: {exc}"))
            time.sleep(0.5)

    def on_close(self) -> None:
        if self._region_editor and self._region_editor.active:
            self._region_editor.stop()
        if self.hotkeys_active:
            self.stop_hotkeys()
        self.destroy()


def run_gui() -> None:
    app = ClientApp()
    app.mainloop()
