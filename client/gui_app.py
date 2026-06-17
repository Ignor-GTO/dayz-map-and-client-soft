import io
import json
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import keyboard

from api_client import MapClient
from capture import grab_region, list_monitors
from clipboard_util import grab_clipboard_image, grab_clipboard_text, prepare_coord_image
from config import load_config, save_config
from ocr import extract_coordinates, extract_coordinates_with_text, parse_coordinates
from region_overlay import OcrRegionEditor
from status_overlay import GameHudOverlay
from ocr_preprocess import IZURVIVE_OCR_REGION
from version import __version__


class ClientApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"DayZ Map Client v{__version__} — GTO Team")
        self.geometry("620x680")
        self.resizable(False, False)

        self.cfg = load_config()
        self.map_client: MapClient | None = None
        self.hotkeys_active = False
        self._map_session_active = False
        self._session_player_coords: tuple[float, float] | None = None
        self._clipboard_hash: str | None = None
        self._stop_clipboard = threading.Event()
        self._snip_watch_active = False
        self._snip_check_attempt = 0
        self._clipboard_pending_at = 0.0
        self._clipboard_watch_digest: str | None = None
        self._region_editor: OcrRegionEditor | None = None
        self._hud: GameHudOverlay | None = None

        self._build_ui()
        self._load_fields()
        self.log_line(f"[Клиент] v{__version__}")
        self.after(400, self._startup_ocr_check)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind_all("<Control-Key>", self._handle_global_shortcuts)

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 4}
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Сервер").grid(row=0, column=0, sticky="w", **pad)
        self.server_var = tk.StringVar()
        self.server_entry = ttk.Entry(frm, textvariable=self.server_var, width=52)
        self.server_entry.grid(row=0, column=1, **pad)

        ttk.Label(frm, text="Ключ клиента").grid(row=1, column=0, sticky="w", **pad)
        self.key_var = tk.StringVar()
        self.key_entry = ttk.Entry(frm, textvariable=self.key_var, width=52, show="*")
        self.key_entry.grid(row=1, column=1, **pad)

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
        self.region_vars = [tk.IntVar(value=v) for v in self.cfg.get("ocr_region", IZURVIVE_OCR_REGION)]
        for i, var in enumerate(self.region_vars):
            entry = ttk.Entry(region_frm, textvariable=var, width=8)
            entry.pack(side="left", padx=2)
            entry.bind("<Button-3>", self._show_entry_menu)
        self.region_btn = ttk.Button(region_frm, text="Редактор области", command=self.toggle_ocr_region)
        self.region_btn.pack(side="left", padx=6)
        ttk.Button(region_frm, text="iZurvive", command=self._apply_izurvive_preset).pack(side="left", padx=2)
        self.monitor_combo.bind("<<ComboboxSelected>>", self._on_monitor_changed)

        btn_frm = ttk.Frame(frm)
        btn_frm.grid(row=4, column=0, columnspan=2, pady=10)
        ttk.Button(btn_frm, text="Сохранить", command=self.save_settings).pack(side="left", padx=5)
        self.start_btn = ttk.Button(btn_frm, text="Запустить hotkeys", command=self.toggle_hotkeys)
        self.start_btn.pack(side="left", padx=5)
        ttk.Button(btn_frm, text="Тест OCR (M)", command=self.test_ocr).pack(side="left", padx=5)
        ttk.Button(btn_frm, text="Проверка OCR", command=self.check_ocr).pack(side="left", padx=5)
        ttk.Button(btn_frm, text="Установить Windows OCR", command=self.install_windows_ocr).pack(
            side="left", padx=5
        )

        ttk.Label(frm, text="M — позиция · повтор M — закрыть · Ctrl+Shift+D — метка").grid(
            row=5, column=0, columnspan=2, **pad
        )
        ttk.Label(
            frm,
            text="Win+Shift+S или Ctrl+Shift+S — снимок координат · Ctrl+Shift+D — метка",
            wraplength=580,
        ).grid(row=6, column=0, columnspan=2, **pad)

        nudge_frm = ttk.Frame(frm)
        nudge_frm.grid(row=7, column=0, columnspan=2, sticky="w", padx=10, pady=2)
        self.mouse_nudge_var = tk.BooleanVar(value=self.cfg.get("mouse_nudge_before_ocr", True))
        ttk.Checkbutton(
            nudge_frm,
            text="Перед M сдвигать мышь к левому краю (координаты игрока iZurvive)",
            variable=self.mouse_nudge_var,
        ).pack(side="left")

        self.status_var = tk.StringVar(value="Остановлено")
        ttk.Label(frm, textvariable=self.status_var).grid(row=8, column=0, columnspan=2, **pad)

        self.log = scrolledtext.ScrolledText(
            frm,
            height=17,
            width=64,
            state="disabled",
            selectbackground="#0078d7",
            selectforeground="white",
            inactiveselectbackground="#a0a0a0"
        )
        self.log.grid(row=9, column=0, columnspan=2, pady=8)

        # Allow focusing the widget on click to enable selection and copy shortcuts
        self.log.bind("<Button-1>", lambda e: self.log.focus_set(), add="+")

        # Explicit copy and select all shortcuts because default class bindings
        # for these keys are disabled when state="disabled"
        self.log.bind("<Control-c>", self._copy_log)
        self.log.bind("<Control-C>", self._copy_log)
        self.log.bind("<Control-a>", self._select_all_log)
        self.log.bind("<Control-A>", self._select_all_log)

        # Context menu for log widget
        self.log_menu = tk.Menu(self.log, tearoff=0)
        self.log_menu.add_command(label="Копировать", command=self._copy_log)
        self.log_menu.add_command(label="Выделить всё", command=self._select_all_log)
        self.log.bind("<Button-3>", self._show_log_menu)

        # Context menu for entry fields (Server, Client Key, etc.)
        self.entry_menu = tk.Menu(self, tearoff=0)
        self.entry_menu.add_command(
            label="Вырезать",
            command=lambda: self.focus_get().event_generate("<<Cut>>") if self.focus_get() else None
        )
        self.entry_menu.add_command(
            label="Копировать",
            command=lambda: self.focus_get().event_generate("<<Copy>>") if self.focus_get() else None
        )
        self.entry_menu.add_command(
            label="Вставить",
            command=lambda: self.focus_get().event_generate("<<Paste>>") if self.focus_get() else None
        )
        self.entry_menu.add_command(
            label="Выделить всё",
            command=self._select_all_entry
        )
        self.server_entry.bind("<Button-3>", self._show_entry_menu)
        self.key_entry.bind("<Button-3>", self._show_entry_menu)

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

    def _copy_log(self, event=None) -> str:
        try:
            selected_text = self.log.get("sel.first", "sel.last")
            self.clipboard_clear()
            self.clipboard_append(selected_text)
        except tk.TclError:
            pass
        return "break"

    def _select_all_log(self, event=None) -> str:
        self.log.tag_add("sel", "1.0", "end")
        return "break"

    def _show_log_menu(self, event) -> None:
        try:
            self.log.get("sel.first", "sel.last")
            self.log_menu.entryconfigure("Копировать", state="normal")
        except tk.TclError:
            self.log_menu.entryconfigure("Копировать", state="disabled")
        self.log_menu.post(event.x_root, event.y_root)

    def _select_all_entry(self) -> None:
        widget = self.focus_get()
        if isinstance(widget, (tk.Entry, ttk.Entry)):
            widget.select_range(0, tk.END)
            widget.icursor(tk.END)

    def _show_entry_menu(self, event) -> None:
        widget = event.widget
        widget.focus_set()
        try:
            is_writable = widget.cget("state") == "normal"
        except (tk.TclError, AttributeError):
            is_writable = True
        try:
            widget.selection_get()
            has_selection = True
        except tk.TclError:
            has_selection = False
        self.entry_menu.entryconfigure("Вырезать", state="normal" if (has_selection and is_writable) else "disabled")
        self.entry_menu.entryconfigure("Копировать", state="normal" if has_selection else "disabled")
        try:
            clipboard_text = self.clipboard_get()
            has_clipboard = bool(clipboard_text)
        except tk.TclError:
            has_clipboard = False
        self.entry_menu.entryconfigure("Вставить", state="normal" if (has_clipboard and is_writable) else "disabled")
        self.entry_menu.post(event.x_root, event.y_root)

    def _handle_global_shortcuts(self, event) -> str | None:
        ctrl = (event.state & 0x0004) != 0
        if not ctrl:
            return None
        widget = event.widget
        if not isinstance(widget, (tk.Entry, ttk.Entry, tk.Text, scrolledtext.ScrolledText)):
            return None
        if event.keycode == 86:  # Ctrl+V
            try:
                state = widget.cget("state")
            except (tk.TclError, AttributeError):
                state = "normal"
            if state == "normal":
                widget.event_generate("<<Paste>>")
            return "break"
        elif event.keycode == 67:  # Ctrl+C
            widget.event_generate("<<Copy>>")
            return "break"
        elif event.keycode == 88:  # Ctrl+X
            try:
                state = widget.cget("state")
            except (tk.TclError, AttributeError):
                state = "normal"
            if state == "normal":
                widget.event_generate("<<Cut>>")
            return "break"
        elif event.keycode == 65:  # Ctrl+A
            if isinstance(widget, (tk.Entry, ttk.Entry)):
                widget.select_range(0, tk.END)
                widget.icursor(tk.END)
            else:
                widget.tag_add("sel", "1.0", "end")
            return "break"
        return None

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
                "mouse_nudge_before_ocr": self.mouse_nudge_var.get(),
                "mouse_nudge_side": "left",
                "mouse_nudge_delay_ms": int(self.cfg.get("mouse_nudge_delay_ms", 400)),
                "mouse_nudge_edge_offset": int(self.cfg.get("mouse_nudge_edge_offset", 8)),
                "mouse_nudge_restore": self.cfg.get("mouse_nudge_restore", True),
            }
        )
        save_config(self.cfg)
        self.map_client = MapClient(self.cfg["server_url"], self.cfg["client_key"])
        self.log_line("[OK] Настройки сохранены")

    def _monitor_index(self) -> int:
        return self.monitor_combo.current() + 1 if self._monitors else self.cfg.get("monitor_index", 1)

    def _ocr_region(self) -> tuple[int, int, int, int]:
        return tuple(v.get() for v in self.region_vars)

    def _grab_ocr_image(self):
        left, top, right, bottom = self._ocr_region()
        pad_x, pad_y = 24, 12
        return grab_region(
            self._monitor_index(),
            (
                max(0, left - pad_x),
                max(0, top - pad_y),
                right + pad_x,
                bottom + pad_y,
            ),
        )

    def _ensure_hud(self) -> GameHudOverlay:
        if self._hud is None:
            self._hud = GameHudOverlay(self, self._monitor_index)
        return self._hud

    def _ensure_region_editor(self) -> OcrRegionEditor:
        if self._region_editor is None:
            self._region_editor = OcrRegionEditor(
                self,
                monitor_index_getter=self._monitor_index,
                region_vars=self.region_vars,
            )
        return self._region_editor

    def _apply_izurvive_preset(self) -> None:
        for var, value in zip(self.region_vars, IZURVIVE_OCR_REGION):
            var.set(value)
        self.log_line(
            "[OCR] Пресет iZurvive: область «15100 / 879» внизу слева. "
            "Подстройте рамкой на своём мониторе."
        )

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

    def _startup_ocr_check(self) -> None:
        from ocr_engine import ensure_ocr_backend, uses_windows_ocr
        from ocr_tesseract import is_available as tesseract_available

        backend = ensure_ocr_backend()
        self.log_line(f"[OCR] Движок: {backend}")
        if tesseract_available():
            self.log_line("[OCR] Tesseract — быстрый режим (только цифры)")
        elif not uses_windows_ocr():
            self.log_line(
                "[OCR] Для скорости установите Tesseract: "
                "https://github.com/UB-Mannheim/tesseract/wiki"
            )

    def install_windows_ocr(self) -> None:
        from ocr_setup import format_setup_message, install_ocr_packs_admin, open_ocr_language_settings
        from ocr_engine import get_diagnostics, uses_windows_ocr

        if uses_windows_ocr():
            messagebox.showinfo("Windows OCR", "Windows OCR уже установлен и используется.")
            return

        diag = get_diagnostics()
        choice = messagebox.askyesnocancel(
            "Установка Windows OCR",
            format_setup_message(diag)
            + "\n\n"
            "Да — открыть Параметры Windows\n"
            "Нет — установить автоматически (PowerShell, нужен админ)\n"
            "Отмена",
        )
        if choice is True:
            open_ocr_language_settings()
        elif choice is False:
            if install_ocr_packs_admin(diag):
                self.log_line("[OCR] Запущена установка OCR (окно PowerShell с правами админа)")
            else:
                messagebox.showerror("OCR", "Не удалось запустить установку (отменено или нет прав).")

    def _show_ocr_error(self, exc: Exception) -> None:
        msg = str(exc)
        self.log_line(f"[OCR] {msg}")
        messagebox.showerror("OCR", msg)

    def check_ocr(self) -> None:
        from ocr_engine import ensure_ocr_backend, list_ocr_languages, uses_windows_ocr

        try:
            backend = ensure_ocr_backend()
            langs = list_ocr_languages()
            self.log_line(f"[OCR OK] Движок: {backend}")
            if langs:
                self.log_line(f"[OCR OK] Windows OCR языки: {', '.join(langs)}")
            if uses_windows_ocr():
                messagebox.showinfo("OCR", f"OCR работает.\n{backend}")
            else:
                messagebox.showinfo(
                    "OCR",
                    f"OCR работает через встроенный движок.\n\n"
                    f"{backend}\n\n"
                    "Для ускорения можно установить Windows OCR — кнопка «Установить Windows OCR».",
                )
        except Exception as exc:
            self._show_ocr_error(exc)

    def _log_mouse_nudge(self, target: tuple[int, int], saved: tuple[int, int], actual: tuple[int, int]) -> None:
        self.log_line(f"[OCR] Мышь {saved[0]},{saved[1]} → {target[0]},{target[1]} (сейчас {actual[0]},{actual[1]})")
        if abs(actual[0] - target[0]) > 40 or abs(actual[1] - target[1]) > 40:
            self.log_line(
                "[OCR] Курсор не двигается — DayZ удерживает мышь в полном экране. "
                "Варианты: iZurvive на 2-м мониторе, DayZ в оконном режиме, "
                "Alt+Tab на браузер перед M. Отправлен hover в окно под курсором."
            )

    def _mouse_nudge_kwargs(self) -> dict:
        return {
            "enabled": self.mouse_nudge_var.get(),
            "side": "left",
            "delay_ms": int(self.cfg.get("mouse_nudge_delay_ms", 400)),
            "restore": self.cfg.get("mouse_nudge_restore", True),
            "edge_offset": int(self.cfg.get("mouse_nudge_edge_offset", 8)),
            "on_nudged": self._log_mouse_nudge,
            "on_skipped": lambda reason: self.log_line(f"[OCR] Сдвиг мыши пропущен: {reason}"),
        }

    def test_ocr(self) -> None:
        self.save_settings()
        monitor = self._monitor_index()
        region = self._ocr_region()
        result: dict = {}

        def capture() -> None:
            try:
                img = self._grab_ocr_image()
                coords, raw = extract_coordinates_with_text(img)
                result["coords"] = coords
                result["raw"] = raw
            except Exception as exc:
                result["error"] = exc

        from mouse_util import with_mouse_nudge

        with_mouse_nudge(monitor, region, capture, **self._mouse_nudge_kwargs())

        if err := result.get("error"):
            messagebox.showerror("OCR", str(err))
            return
        raw = result.get("raw")
        if raw:
            self.log_line(f"[Тест] OCR текст: {raw!r}")
        coords = result.get("coords")
        if coords:
            self.log_line(f"[Тест] OCR: {coords[0]:.0f} / {coords[1]:.0f}")
        else:
            self.log_line("[Тест] Координаты не распознаны — проверьте область (кнопка iZurvive)")

    def toggle_hotkeys(self) -> None:
        if self.hotkeys_active:
            self.stop_hotkeys()
        else:
            self.start_hotkeys()

    def start_hotkeys(self) -> None:
        self.save_settings()
        if not self.map_client:
            return
        from ocr_engine import ensure_ocr_backend

        try:
            backend = ensure_ocr_backend()
            self.log_line(f"[OCR] {backend}")
        except Exception as exc:
            self._show_ocr_error(exc)
            return
        self.hotkeys_active = True
        self._map_session_active = False
        self.status_var.set("Работает — M / Num Lock открыть карту")
        self.start_btn.configure(text="Остановить hotkeys")
        keyboard.add_hotkey("m", lambda: self.after(0, self._handle_m_hotkey))
        keyboard.add_hotkey("num lock", lambda: self.after(0, self._handle_m_hotkey))
        keyboard.add_hotkey(
            "ctrl+shift+d",
            lambda: self.after(0, self._handle_marker_hotkey),
            suppress=False,
        )
        keyboard.add_hotkey(
            "ctrl+shift+s",
            lambda: self.after(0, self._handle_snip_hotkey),
            suppress=False,
        )
        keyboard.add_hotkey(
            "ctrl+shift+c",
            lambda: self.after(0, self._handle_snip_hotkey),
            suppress=False,
        )
        keyboard.add_hotkey(
            "esc",
            lambda: self.after(0, self._handle_esc_hotkey),
            suppress=False,
        )
        self._stop_clipboard.clear()
        threading.Thread(target=self._clipboard_loop, daemon=True).start()
        self.log_line("[Запуск] Hotkeys: M / Num Lock, Esc (закрыть), Ctrl+Shift+D, Ctrl+Shift+S/C; Win+Shift+S — авто из буфера")

    def stop_hotkeys(self) -> None:
        self.hotkeys_active = False
        self._end_map_session(silent=True)
        self._stop_clipboard.set()
        keyboard.unhook_all_hotkeys()
        self.status_var.set("Остановлено")
        self.start_btn.configure(text="Запустить hotkeys")
        self.log_line("[Стоп] Hotkeys отключены")

    def _end_map_session(self, *, silent: bool = False) -> None:
        if not self._map_session_active:
            return
        self._map_session_active = False
        self._session_player_coords = None
        self._ensure_hud().hide()
        if not silent:
            self.log_line("[M] Карта закрыта — OCR отключён")
        self._update_session_status()

    def _start_map_session(self) -> None:
        self._map_session_active = True
        self._update_session_status()
        self._ensure_hud().show_map_session()
        self.log_line("[M] Сессия карты — Ctrl+Shift+D для метки")

    def _update_session_status(self) -> None:
        if not self.hotkeys_active:
            return
        if self._map_session_active:
            self.status_var.set("Карта открыта — M закрыть · Ctrl+Shift+D — метка")
        else:
            self.status_var.set("Работает — M открыть карту / позиция")

    def _capture_coords(self, *, nudge: bool) -> tuple[float, float] | None:
        monitor = self._monitor_index()
        region = self._ocr_region()
        result: dict = {}

        def capture() -> None:
            try:
                img = self._grab_ocr_image()
                coords, raw = extract_coordinates_with_text(img)
                result["coords"] = coords
                result["raw"] = raw
            except Exception as exc:
                result["error"] = exc

        if nudge:
            from mouse_util import with_mouse_nudge

            with_mouse_nudge(monitor, region, capture, **self._mouse_nudge_kwargs())
        else:
            capture()

        if err := result.get("error"):
            raise err
        raw = result.get("raw")
        if raw:
            self.after(0, lambda t=raw: self.log_line(f"[OCR] {t!r}"))
        coords = result.get("coords")
        if coords and self._session_player_coords:
            coords = self._reconcile_marker_coords(coords, self._session_player_coords)
        return coords

    def _reconcile_marker_coords(
        self,
        coords: tuple[float, float],
        reference: tuple[float, float],
    ) -> tuple[float, float]:
        """Fix hover/truncated OCR: prefer session player coords when marker read is clearly wrong."""
        x, y = coords
        ref_x, ref_y = reference
        if abs(x - ref_x) > 2500:
            return coords
        if y >= 500 or ref_y < 500:
            return coords
        # Typical failure: 16119/1753 -> 16058/177 (hover + truncated Y)
        if len(str(int(abs(y)))) < len(str(int(abs(ref_y)))):
            self.after(
                0,
                lambda: self.log_line(
                    f"[OCR] Y={y:.0f} похоже обрезан — используем позицию с M: {ref_x:.0f} / {ref_y:.0f}"
                ),
            )
            return ref_x, ref_y
        return coords

    def _handle_snip_hotkey(self) -> None:
        if not self.hotkeys_active:
            return

        def work() -> None:
            img = None
            for attempt in range(10):
                img = self._clipboard_image()
                if img is not None and img.size[0] >= 30:
                    break
                time.sleep(0.12)
            if img is None:
                self.after(
                    0,
                    lambda: self.log_line(
                        "[Ctrl+Shift+S/C] Буфер пуст — Win+Shift+S, выделите полоску координат, "
                        "затем Ctrl+Shift+S/C (или дождитесь авто-чтения)"
                    ),
                )
                return
            self.after(0, lambda: self.log_line("[Ctrl+Shift+S/C] Чтение из буфера…"))
            self._process_snip_marker(img, source="Ctrl+Shift+S/C")

        threading.Thread(target=work, daemon=True).start()

    def _handle_marker_hotkey(self) -> None:
        if not self.hotkeys_active:
            return
        if not self._map_session_active:
            self.log_line("[Метка] Ctrl+Shift+D — сначала M (открыть сессию карты)")
            self._ensure_hud().show_error("Нажмите M")
            return
        self._send_marker_from_screen(source="Ctrl+Shift+D")

    def _send_marker_from_screen(self, *, source: str) -> None:
        if not self._map_session_active or not self.map_client:
            return
        self.log_line(f"[Метка] {source} — считывание координат…")
        self._ensure_hud().show_busy("Метка…")

        def work() -> None:
            try:
                time.sleep(0.2)
                coords = self._capture_coords(nudge=False)
                if coords:
                    x, y = coords
                    self.after(0, lambda: self.log_line(f"[Метка] {x:.0f} / {y:.0f}"))
                    if self.map_client:
                        ok, err_msg = self.map_client.send_marker(x, y)
                        if ok:
                            self.after(0, lambda: self.log_line("[Метка] Отправлено на сервер"))
                            self.after(0, lambda: self._ensure_hud().show_ok(x, y, marker=True))
                        else:
                            self.after(0, lambda t=err_msg: self.log_line(f"[Метка] Ошибка отправки: {t}"))
                            self.after(0, lambda: self._ensure_hud().show_error("Ошибка отправки"))
                    self.after(0, lambda: self._ensure_hud().show_map_session())
                else:
                    self.after(0, lambda: self.log_line("[Метка] Координаты не распознаны"))
                    self.after(0, lambda: self._ensure_hud().show_error("Координаты не видны"))
                    self.after(0, lambda: self._ensure_hud().show_map_session())
            except Exception as exc:
                self.after(0, lambda: self.log_line(f"[Метка] Ошибка: {exc}"))
                self.after(0, lambda: self._ensure_hud().show_error(str(exc)[:40]))

        threading.Thread(target=work, daemon=True).start()

    def on_m_pressed(self) -> None:
        self.after(0, self._handle_m_hotkey)

    def _handle_m_hotkey(self) -> None:
        if not self.map_client:
            return

        if self._map_session_active:
            self._end_map_session()
            return

        self._start_map_session()
        self._ensure_hud().show_busy("Позиция игрока…")

        def work() -> None:
            try:
                coords = self._capture_coords(nudge=True)
                if coords:
                    x, y = coords
                    self._session_player_coords = (x, y)
                    self.after(0, lambda: self.log_line(f"[M] {x:.0f} / {y:.0f}"))
                    if self.map_client:
                        ok, err_msg = self.map_client.send_position(x, y)
                        if ok:
                            self.after(0, lambda: self.log_line("[M] Позиция отправлена"))
                            self.after(0, lambda: self._ensure_hud().show_ok(x, y))
                        else:
                            self.after(0, lambda t=err_msg: self.log_line(f"[M] Ошибка отправки: {t}"))
                            self.after(0, lambda: self._ensure_hud().show_error("Ошибка отправки"))
                    self.after(0, lambda: self._ensure_hud().show_map_session())
                else:
                    self.after(0, lambda: self.log_line("[M] Координаты не распознаны"))
                    self.after(0, lambda: self._ensure_hud().show_error("OCR не распознал"))
                    self.after(0, lambda: self._ensure_hud().show_map_session())
            except Exception as exc:
                self.after(0, lambda: self.log_line(f"[M] Ошибка: {exc}"))
                self.after(0, lambda: self._ensure_hud().show_error(str(exc)[:40]))

        threading.Thread(target=work, daemon=True).start()

    def _handle_esc_hotkey(self) -> None:
        if not self.hotkeys_active:
            return
        if self._map_session_active:
            self._end_map_session()

    def _clipboard_image(self):
        return grab_clipboard_image(retries=8, delay=0.1)

    def _image_hash(self, img) -> str:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return str(hash(buf.getvalue()))

    def _coords_from_clipboard(self, img) -> tuple[tuple[float, float] | None, str]:
        text = grab_clipboard_text()
        if text:
            coords = parse_coordinates(text)
            if coords:
                return coords, text

        from ocr import extract_coordinates_with_text

        prepared = prepare_coord_image(img, self._monitor_index(), self._ocr_region())
        return extract_coordinates_with_text(prepared)

    def _process_snip_marker(self, img, *, source: str = "Скриншот") -> None:
        if not self.map_client:
            self.log_line(f"[{source}] Клиент не настроен — сохраните ключ")
            return
        if source != "Скриншот" or self._map_session_active:
            pass  # hotkey / active session
        elif not self._map_session_active:
            self.log_line(f"[{source}] Подсказка: M — сессия карты, метка появится на веб-карте")

        def work() -> None:
            try:
                coords, raw = self._coords_from_clipboard(img)
                if raw:
                    self.after(0, lambda t=raw: self.log_line(f"[{source}] OCR: {t!r}"))
                if coords:
                    x, y = coords
                    self.after(0, lambda: self.log_line(f"[{source}] {x:.0f} / {y:.0f}"))
                    if self.map_client:
                        ok, err_msg = self.map_client.send_marker(x, y, marker_type="screenshot")
                        if ok:
                            self.after(0, lambda: self.log_line(f"[{source}] Метка отправлена"))
                            self.after(0, lambda: self._ensure_hud().show_ok(x, y, marker=True))
                        else:
                            self.after(0, lambda t=err_msg: self.log_line(f"[{source}] Ошибка отправки на сервер: {t}"))
                else:
                    self.after(
                        0,
                        lambda: self.log_line(
                            f"[{source}] Координаты не распознаны — выделите всю полоску «15100 - 879»"
                        ),
                    )
            except Exception as exc:
                self.after(0, lambda e=exc: self.log_line(f"[{source}] Ошибка: {e}"))

        threading.Thread(target=work, daemon=True).start()

    def _schedule_clipboard_process(self, source: str) -> None:
        self._clipboard_pending_at = time.monotonic()

        def run() -> None:
            if time.monotonic() - self._clipboard_pending_at < 0.35:
                self.after(80, run)
                return
            img = self._clipboard_image()
            if img is None:
                return
            h = self._image_hash(img)
            if h == self._clipboard_hash:
                return
            self._clipboard_hash = h
            self._clipboard_watch_digest = None
            self.after(0, lambda: self.log_line(f"[{source}] Новое изображение в буфере"))
            self._process_snip_marker(img, source=source)

        self.after(450, run)

    def _clipboard_loop(self) -> None:
        time.sleep(0.5)
        img = self._clipboard_image()
        if img is not None:
            self._clipboard_hash = self._image_hash(img)
        while not self._stop_clipboard.is_set():
            img = self._clipboard_image()
            if img is not None and self.map_client:
                w, h = img.size
                if w >= 30 and h >= 10:
                    digest = self._image_hash(img)
                    if digest != self._clipboard_hash and digest != self._clipboard_watch_digest:
                        self._clipboard_watch_digest = digest
                        self._schedule_clipboard_process(source="Win+Shift+S")
            time.sleep(0.2)

    def on_close(self) -> None:
        if self._region_editor and self._region_editor.active:
            self._region_editor.stop()
        if self._hud:
            self._hud.destroy()
        if self.hotkeys_active:
            self.stop_hotkeys()
        self.destroy()


def run_gui() -> None:
    app = ClientApp()
    app.mainloop()
