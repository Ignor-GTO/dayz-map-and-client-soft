"""SCUM Map Client — tabs, M + auto 30s position, zoom/focus, auto-update."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import httpx

from api_client import MapClient
from clipboard_util import (
    clipboard_sequence_number,
    grab_clipboard_text,
    read_clipboard_text,
)
from config import load_config, normalize_hotkey_list, save_config
from scum_coords import looks_like_client_log, parse_scum_clipboard
from version import __version__
from win_input import (
    GlobalHotkeyListener,
    is_admin,
    is_our_process_foreground,
    relaunch_as_admin,
    resolve_vk,
)

GITHUB_RELEASES_LATEST = (
    "https://api.github.com/repos/Ignor-GTO/dayz-map-and-client-soft/releases/latest"
)
UPDATE_ASSET = "ScumMapClient.exe"
AUTO_INTERVAL_DEFAULT = 30


class ScumMapApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"SCUM Map Client v{__version__}")
        self.geometry("640x620")
        self.minsize(580, 560)

        self.settings = load_config()
        self.map_client: MapClient | None = None
        self._hotkeys_on = False
        self._stop_workers = threading.Event()
        self._last_sent: tuple[float, float] | None = None
        self._send_lock = threading.Lock()
        self._clipboard_digest: str | None = None
        self._clipboard_coords_at = 0.0
        self._fresh_clipboard_coords: tuple[float, float] | None = None
        self._copy_lock = threading.Lock()
        self._last_copy_trigger_at = 0.0
        self._hotkeys = GlobalHotkeyListener()
        self.current_page = 0
        self._auto_warned_empty = False
        self._warned_log_clip = False

        self._cleanup_old_exe()
        self._build_ui()
        self._load_fields()
        self._maybe_init_client()
        self.log_line(f"[Клиент] SCUM v{__version__}")
        if is_admin():
            self.log_line("Права: администратор — OK для перехвата F1 в игре.")
        else:
            self.log_line("Права: ОБЫЧНЫЕ. Если SCUM от админа — F1 не увидим. Нажмите «От админа».")
        self.log_line("Вставьте ключ → Настройки → Сохранить → на Главной нажмите «Запустить».")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(2000, lambda: self.check_for_updates(manual=False))

    # ------------------------------------------------------------------ UI
    def _cleanup_old_exe(self) -> None:
        try:
            exe_path = sys.executable
            if exe_path.endswith(".exe"):
                old_exe = exe_path + ".old"
                if os.path.exists(old_exe):
                    try:
                        os.remove(old_exe)
                    except Exception:
                        subprocess.Popen(
                            ["cmd", "/c", f'timeout /t 2 /nobreak >nul & del /f /q "{old_exe}"'],
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
        except Exception:
            pass

    def _build_ui(self) -> None:
        self.bg_color = "#121820"
        self.fg_color = "#e2e8f0"
        self.accent_color = "#3b82f6"
        self.card_bg = "#1e293b"
        self.border_color = "#334155"
        self.text_muted = "#94a3b8"
        self.configure(bg=self.bg_color)

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=self.bg_color)
        style.configure("Card.TFrame", background=self.card_bg)
        style.configure(
            "TLabelframe",
            background=self.card_bg,
            bordercolor=self.border_color,
            lightcolor=self.border_color,
            darkcolor=self.border_color,
            borderwidth=1,
            relief="solid",
            padding=10,
        )
        style.configure(
            "TLabelframe.Label",
            background=self.card_bg,
            foreground=self.accent_color,
            font=("Segoe UI", 10, "bold"),
        )
        style.configure("TLabel", background=self.bg_color, foreground=self.fg_color, font=("Segoe UI", 10))
        style.configure("Card.TLabel", background=self.card_bg, foreground=self.fg_color, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=self.bg_color, foreground=self.text_muted, font=("Segoe UI", 9))
        style.configure(
            "CardMuted.TLabel",
            background=self.card_bg,
            foreground=self.text_muted,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Header.TLabel",
            background=self.bg_color,
            foreground=self.fg_color,
            font=("Segoe UI", 13, "bold"),
        )
        style.configure(
            "Status.TLabel",
            background=self.card_bg,
            foreground=self.accent_color,
            font=("Segoe UI", 10, "bold"),
        )
        style.configure(
            "TButton",
            background=self.accent_color,
            foreground="#ffffff",
            bordercolor=self.accent_color,
            font=("Segoe UI", 9, "bold"),
            padding=[10, 5],
        )
        style.map("TButton", background=[("active", "#2563eb")])
        style.configure(
            "Nav.TButton",
            background=self.card_bg,
            foreground=self.fg_color,
            bordercolor=self.border_color,
            font=("Segoe UI", 9),
            padding=[8, 4],
        )
        style.map("Nav.TButton", background=[("active", self.border_color)])
        style.configure(
            "NavActive.TButton",
            background=self.accent_color,
            foreground="#ffffff",
            bordercolor=self.accent_color,
            font=("Segoe UI", 9, "bold"),
            padding=[8, 4],
        )
        style.configure("TEntry", fieldbackground="#0f172a", foreground=self.fg_color)
        style.configure("TCheckbutton", background=self.card_bg, foreground=self.fg_color)

        header = ttk.Frame(self)
        header.pack(fill="x", padx=10, pady=(10, 0))
        ttk.Label(header, text="SCUM Map Client", style="Header.TLabel").pack(side="left")
        ttk.Label(header, text=f"v{__version__}", style="Muted.TLabel").pack(side="left", padx=8)

        nav = ttk.Frame(self)
        nav.pack(fill="x", padx=10, pady=8)
        self.nav_btn_main = ttk.Button(nav, text="Главная", command=lambda: self._show_page(0), style="NavActive.TButton", width=10)
        self.nav_btn_main.pack(side="left", padx=(0, 4))
        self.nav_btn_settings = ttk.Button(nav, text="Настройки", command=lambda: self._show_page(1), style="Nav.TButton", width=10)
        self.nav_btn_settings.pack(side="left", padx=4)
        self.nav_btn_about = ttk.Button(nav, text="О программе", command=lambda: self._show_page(2), style="Nav.TButton", width=12)
        self.nav_btn_about.pack(side="left", padx=4)

        self.pages_container = ttk.Frame(self)
        self.pages_container.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.main_page = ttk.Frame(self.pages_container)
        self.settings_page = ttk.Frame(self.pages_container)
        self.about_page = ttk.Frame(self.pages_container)

        self._build_main_page()
        self._build_settings_page()
        self._build_about_page()
        self._show_page(0)
        self._bind_clipboard_shortcuts()

    def _bind_clipboard_shortcuts(self) -> None:
        """Tk on Windows often needs explicit paste; also keep Ctrl+C for the log."""
        self.bind_all("<Control-v>", self._on_paste_shortcut, add="+")
        self.bind_all("<Control-V>", self._on_paste_shortcut, add="+")
        self.bind_all("<<Paste>>", self._on_paste_shortcut, add="+")
        self.bind_all("<Shift-Insert>", self._on_paste_shortcut, add="+")
        self.bind_all("<Control-c>", self._on_copy_shortcut, add="+")
        self.bind_all("<Control-C>", self._on_copy_shortcut, add="+")

    def _clipboard_get_text(self) -> str:
        # Win32 only — Tk clipboard_get() can hang forever while our poller holds the clipboard.
        return read_clipboard_text(0.4, allow_powershell=True)

    def _on_paste_shortcut(self, event=None):
        widget = self.focus_get()
        if widget is None:
            return None
        # Only for entry-like widgets
        cls = widget.winfo_class()
        if cls not in {"Entry", "TEntry", "Text"}:
            return None
        text = self._clipboard_get_text()
        if not text:
            return "break"
        try:
            if cls == "Text":
                try:
                    widget.delete("sel.first", "sel.last")
                except Exception:
                    pass
                widget.insert("insert", text)
            else:
                try:
                    if widget.selection_present():
                        widget.delete("sel.first", "sel.last")
                except Exception:
                    pass
                widget.insert("insert", text)
        except Exception:
            return None
        return "break"

    def _on_copy_shortcut(self, event=None):
        widget = self.focus_get()
        if widget is None:
            return None
        try:
            if widget.winfo_class() == "Text":
                try:
                    data = widget.get("sel.first", "sel.last")
                except Exception:
                    return None
                if data:
                    self.clipboard_clear()
                    self.clipboard_append(data)
                    return "break"
            if widget.winfo_class() in {"Entry", "TEntry"}:
                try:
                    if widget.selection_present():
                        data = widget.selection_get()
                        self.clipboard_clear()
                        self.clipboard_append(data)
                        return "break"
                except Exception:
                    pass
        except Exception:
            pass
        return None

    def _build_main_page(self) -> None:
        card = ttk.LabelFrame(self.main_page, text="Статус", padding=12)
        card.pack(fill="x", pady=(0, 8))
        self.status_var = tk.StringVar(value="Остановлено — нажмите «Запустить»")
        ttk.Label(card, textvariable=self.status_var, style="Status.TLabel").pack(anchor="w")
        ttk.Label(
            card,
            text=(
                "Главное: в SCUM нажмите Ctrl+C — клиент сам заберёт {X=… Y=…} из буфера.\n"
                "F1 / «Из буфера»: отправить то, что уже в буфере. Авто — повтор последней позиции.\n"
                "Не копируйте лог клиента в буфер — иначе вместо координат окажется текст лога."
            ),
            style="CardMuted.TLabel",
            wraplength=580,
        ).pack(anchor="w", pady=(6, 0))

        btns = ttk.Frame(self.main_page)
        btns.pack(fill="x", pady=6)
        self.toggle_btn = ttk.Button(btns, text="Запустить", command=self._toggle_hotkeys)
        self.toggle_btn.pack(side="left")
        ttk.Button(btns, text="Отправить позицию", command=self._manual_copy_send).pack(side="left", padx=6)
        ttk.Button(btns, text="Из буфера", command=self._send_clipboard_now).pack(side="left", padx=6)
        ttk.Button(btns, text="Копировать лог", command=self._copy_log).pack(side="left", padx=6)
        if not is_admin():
            ttk.Button(btns, text="От админа", command=self._relaunch_admin).pack(side="left", padx=6)

        paste_row = ttk.Frame(self.main_page)
        paste_row.pack(fill="x", pady=(4, 0))
        ttk.Label(paste_row, text="Или вставьте {X=… Y=…}:", style="Muted.TLabel").pack(side="left")
        self.paste_coords_var = tk.StringVar()
        ttk.Entry(paste_row, textvariable=self.paste_coords_var).pack(
            side="left", fill="x", expand=True, padx=6
        )
        ttk.Button(paste_row, text="Отправить", command=self._send_pasted_coords).pack(side="left")

        ttk.Label(self.main_page, text="Лог", style="Muted.TLabel").pack(anchor="w", pady=(8, 2))
        self.log = tk.Text(
            self.main_page,
            height=18,
            wrap="word",
            bg="#0f172a",
            fg=self.fg_color,
            insertbackground=self.fg_color,
            relief="flat",
            font=("Consolas", 9),
            exportselection=True,
        )
        self.log.pack(fill="both", expand=True)

    def _build_settings_page(self) -> None:
        bottom = ttk.Frame(self.settings_page)
        bottom.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Button(bottom, text="Сохранить настройки", command=self._save).pack(side="right")

        canvas = tk.Canvas(self.settings_page, highlightthickness=0, bg=self.bg_color)
        scroll = ttk.Scrollbar(self.settings_page, orient="vertical", command=canvas.yview)
        body = ttk.Frame(canvas)
        body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        conn = ttk.LabelFrame(body, text="Подключение", padding=10)
        conn.pack(fill="x", pady=6)
        ttk.Label(conn, text="Server URL", style="Card.TLabel").pack(anchor="w")
        self.server_var = tk.StringVar()
        ttk.Entry(conn, textvariable=self.server_var, width=64).pack(fill="x", pady=(0, 6))
        ttk.Label(conn, text="Client key", style="Card.TLabel").pack(anchor="w")
        key_row = ttk.Frame(conn, style="Card.TFrame")
        key_row.pack(fill="x")
        self.key_var = tk.StringVar()
        self.key_entry = ttk.Entry(key_row, textvariable=self.key_var, show="•", width=48)
        self.key_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(key_row, text="Вставить", command=self._paste_client_key).pack(side="left", padx=(8, 0))
        ttk.Button(key_row, text="Показать", command=self._toggle_key_visibility).pack(side="left", padx=(6, 0))
        self._key_entry_shown = False

        auto = ttk.LabelFrame(body, text="Автоотправка позиции", padding=10)
        auto.pack(fill="x", pady=6)
        row = ttk.Frame(auto, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="Интервал (сек)", style="Card.TLabel").pack(side="left")
        self.auto_interval_var = tk.IntVar(value=AUTO_INTERVAL_DEFAULT)
        ttk.Entry(row, textvariable=self.auto_interval_var, width=8).pack(side="left", padx=8)
        ttk.Label(
            auto,
            text=(
                "0 = выкл. При 30: каждые 30 с повторно шлёт последнюю известную позицию "
                "(после вашего Ctrl+C). Карту открывать не нужно."
            ),
            style="CardMuted.TLabel",
            wraplength=560,
        ).pack(anchor="w", pady=(6, 0))

        hk = ttk.LabelFrame(body, text="Горячие клавиши (веб-карта)", padding=10)
        hk.pack(fill="x", pady=6)
        ttk.Label(
            hk,
            text="Как в DayZ-клиенте: Page Up / Page Down / End управляют веб-картой в браузере.",
            style="CardMuted.TLabel",
            wraplength=560,
        ).pack(anchor="w", pady=(0, 8))
        self.hotkey_zoom_in_var = tk.StringVar()
        self.hotkey_zoom_out_var = tk.StringVar()
        self.hotkey_focus_me_var = tk.StringVar()
        self.hotkey_send_pos_var = tk.StringVar()
        for label, var in (
            ("Приблизить (zoom in)", self.hotkey_zoom_in_var),
            ("Отдалить (zoom out)", self.hotkey_zoom_out_var),
            ("Найти себя (focus me)", self.hotkey_focus_me_var),
            ("F1 → отправить позицию", self.hotkey_send_pos_var),
        ):
            r = ttk.Frame(hk, style="Card.TFrame")
            r.pack(fill="x", pady=3)
            ttk.Label(r, text=label, style="Card.TLabel", width=28).pack(side="left")
            ttk.Entry(r, textvariable=var, width=28).pack(side="left", padx=4)

        diag = ttk.LabelFrame(body, text="Диагностика", padding=10)
        diag.pack(fill="x", pady=6)
        ttk.Button(diag, text="Проверить обновления", command=lambda: self.check_for_updates(manual=True)).pack(
            side="left"
        )

    def _build_about_page(self) -> None:
        card = ttk.LabelFrame(self.about_page, text="О программе", padding=12)
        card.pack(fill="both", expand=True)
        ttk.Label(card, text=f"SCUM Map Client v{__version__}", style="Card.TLabel", font=("Segoe UI", 12, "bold")).pack(
            anchor="w"
        )
        ttk.Label(
            card,
            text=(
                "По F1 симулирует Ctrl+C (SCUM копирует {X=… Y=…}) и шлёт позицию на веб-карту.\n"
                "Автораз в N секунд делает то же · Page Up/Down/End — зум и фокус на сайте."
            ),
            style="CardMuted.TLabel",
            wraplength=560,
            justify="left",
        ).pack(anchor="w", pady=10)
        ttk.Button(card, text="Проверить обновление", command=lambda: self.check_for_updates(manual=True)).pack(
            anchor="w"
        )

    def _show_page(self, page_index: int) -> None:
        self.current_page = page_index
        self.main_page.pack_forget()
        self.settings_page.pack_forget()
        self.about_page.pack_forget()
        self.nav_btn_main.configure(style="Nav.TButton")
        self.nav_btn_settings.configure(style="Nav.TButton")
        self.nav_btn_about.configure(style="Nav.TButton")
        if page_index == 0:
            self.main_page.pack(fill="both", expand=True)
            self.nav_btn_main.configure(style="NavActive.TButton")
        elif page_index == 1:
            self.settings_page.pack(fill="both", expand=True)
            self.nav_btn_settings.configure(style="NavActive.TButton")
        else:
            self.about_page.pack(fill="both", expand=True)
            self.nav_btn_about.configure(style="NavActive.TButton")

    def _load_fields(self) -> None:
        self.server_var.set(self.settings.get("server_url", ""))
        self.key_var.set(self.settings.get("client_key", ""))
        self.auto_interval_var.set(int(self.settings.get("scum_auto_interval_sec", AUTO_INTERVAL_DEFAULT) or 0))
        self.hotkey_zoom_in_var.set(", ".join(self.settings.get("hotkey_zoom_in", ["page up"])))
        self.hotkey_zoom_out_var.set(", ".join(self.settings.get("hotkey_zoom_out", ["page down"])))
        self.hotkey_focus_me_var.set(", ".join(self.settings.get("hotkey_focus_me", ["end"])))
        pos_keys = self.settings.get("scum_hotkey_send_pos", ["f1"])
        # Old builds defaulted to M; F1 is the intended copy trigger.
        if pos_keys == ["m"]:
            pos_keys = ["f1"]
            self.settings["scum_hotkey_send_pos"] = pos_keys
        self.hotkey_send_pos_var.set(", ".join(pos_keys))

    def _maybe_init_client(self) -> None:
        server = (self.settings.get("server_url") or "").strip()
        key = (self.settings.get("client_key") or "").strip()
        if server and key:
            self.map_client = MapClient(server, key)

    def log_line(self, text: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self.log.insert("end", f"[{ts}] {text}\n")
        self.log.see("end")

    def _parse_hotkeys(self, raw: str, fallback: list[str]) -> list[str]:
        parts = [p.strip() for p in (raw or "").split(",") if p.strip()]
        return normalize_hotkey_list(parts) or list(fallback)

    def _auto_interval(self) -> int:
        try:
            return max(0, int(self.auto_interval_var.get()))
        except Exception:
            return AUTO_INTERVAL_DEFAULT

    # ------------------------------------------------------------------ save / run
    def _save(self) -> None:
        server = self.server_var.get().strip()
        key = self.key_var.get().strip()
        if not server or not key:
            messagebox.showerror("Ошибка", "Укажите server URL и client key")
            return
        self.settings["server_url"] = server
        self.settings["client_key"] = key
        self.settings["map_slug"] = "scum"
        self.settings["scum_auto_interval_sec"] = self._auto_interval()
        self.settings["hotkey_zoom_in"] = self._parse_hotkeys(self.hotkey_zoom_in_var.get(), ["page up"])
        self.settings["hotkey_zoom_out"] = self._parse_hotkeys(self.hotkey_zoom_out_var.get(), ["page down"])
        self.settings["hotkey_focus_me"] = self._parse_hotkeys(self.hotkey_focus_me_var.get(), ["end"])
        self.settings["scum_hotkey_send_pos"] = self._parse_hotkeys(self.hotkey_send_pos_var.get(), ["f1"])
        save_config(self.settings)
        self.map_client = MapClient(server, key)
        self.log_line("Настройки сохранены")
        if not self._hotkeys_on:
            self.status_var.set("Готов — нажмите «Запустить»")
        messagebox.showinfo("Сохранено", "Настройки сохранены.")

    def _toggle_hotkeys(self) -> None:
        if self._hotkeys_on:
            self._stop_hotkeys()
        else:
            self._start_hotkeys()

    def _start_hotkeys(self) -> None:
        if not self.map_client:
            self._save()
            if not self.map_client:
                return
        try:
            self.settings["scum_auto_interval_sec"] = self._auto_interval()
            self.settings["hotkey_zoom_in"] = self._parse_hotkeys(self.hotkey_zoom_in_var.get(), ["page up"])
            self.settings["hotkey_zoom_out"] = self._parse_hotkeys(self.hotkey_zoom_out_var.get(), ["page down"])
            self.settings["hotkey_focus_me"] = self._parse_hotkeys(self.hotkey_focus_me_var.get(), ["end"])
            self.settings["scum_hotkey_send_pos"] = self._parse_hotkeys(self.hotkey_send_pos_var.get(), ["f1"])
            save_config(self.settings)
        except Exception:
            pass

        self._stop_workers.clear()
        self._hotkeys_on = True
        self.toggle_btn.configure(text="Остановить")
        interval = self._auto_interval()
        self.status_var.set(
            f"Работает — ждём ваш Ctrl+C"
            + (f" / авто {interval} с" if interval > 0 else "")
            + " / F1=повтор"
        )

        bindings: list[tuple[str, int, str]] = []
        for hk in self.settings.get("scum_hotkey_send_pos", ["f1"]):
            vk = resolve_vk(hk)
            if vk is None:
                self.log_line(f"Неизвестная клавиша позиции: {hk}")
                continue
            bindings.append(("copy", vk, hk))
        for hk in self.settings.get("hotkey_zoom_in", ["page up"]):
            vk = resolve_vk(hk)
            if vk is not None:
                bindings.append(("zoom_in", vk, hk))
        for hk in self.settings.get("hotkey_zoom_out", ["page down"]):
            vk = resolve_vk(hk)
            if vk is not None:
                bindings.append(("zoom_out", vk, hk))
        for hk in self.settings.get("hotkey_focus_me", ["end"]):
            vk = resolve_vk(hk)
            if vk is not None:
                bindings.append(("focus_me", vk, hk))

        if not bindings:
            self.log_line("Нет валидных хоткеев — проверьте Настройки")
            self._stop_hotkeys()
            return

        err = self._hotkeys.start(bindings, self._on_global_hotkey)
        if err:
            self.log_line(f"Глобальные хоткеи: {err}")
            messagebox.showerror(
                "Хоткеи",
                f"{err}\n\nЗапустите клиент через «От админа» и закройте другие программы, "
                "которые перехватывают F1.",
            )
            self._stop_hotkeys()
            return

        self._clipboard_digest = None
        self._fresh_clipboard_coords = None
        self._auto_warned_empty = False
        threading.Thread(target=self._clipboard_loop, daemon=True).start()
        if interval > 0:
            threading.Thread(target=self._auto_loop, args=(interval,), daemon=True).start()

        names = [f"{a}:{n}" for a, _vk, n in bindings]
        self.log_line(f"Запущено: {', '.join(names)}")
        self.log_line("В SCUM нажмите Ctrl+C — координаты уйдут на карту автоматически (карту открывать не нужно).")
        self.log_line("F1: отправить из буфера / повторить последнюю позицию.")

        # If coords already in clipboard at start — send now (off UI thread)
        def check_existing() -> None:
            existing = read_clipboard_text(0.5, allow_powershell=True)
            coords = parse_scum_clipboard(existing)

            def apply() -> None:
                if coords:
                    self._clipboard_digest = existing
                    self.log_line("[старт] в буфере уже есть координаты — отправляю")
                    self._send_coords(coords, source="старт/буфер")
                elif existing:
                    self._clipboard_digest = existing
                    preview = existing[:50] + ("…" if len(existing) > 50 else "")
                    self.log_line(f"[старт] буфер без координат ({preview!r})")
                else:
                    self.log_line("[старт] буфер пуст — нажмите Ctrl+C в SCUM")

            self.after(0, apply)

        threading.Thread(target=check_existing, daemon=True).start()
        if not is_admin():
            self.log_line("⚠ Не админ: для хоткеев лучше «От админа».")

    def _on_global_hotkey(self, action: str, name: str) -> None:
        """Called from hotkey thread."""
        if not self._hotkeys_on:
            return
        if action == "copy":
            self.after(0, self._handle_copy_hotkey)
            return
        if is_our_process_foreground():
            return
        if action == "zoom_in":
            self.after(0, self._handle_zoom_in)
        elif action == "zoom_out":
            self.after(0, self._handle_zoom_out)
        elif action == "focus_me":
            self.after(0, self._handle_focus_me)

    def _stop_hotkeys(self) -> None:
        self._hotkeys_on = False
        self._stop_workers.set()
        self._copy_busy = False
        try:
            self._hotkeys.stop()
        except Exception:
            pass
        self.toggle_btn.configure(text="Запустить")
        self.status_var.set("Остановлено — нажмите «Запустить»")
        self.log_line("Остановлено")

    def _relaunch_admin(self) -> None:
        if is_admin():
            messagebox.showinfo("Админ", "Уже запущено от администратора.")
            return
        if messagebox.askyesno("Админ", "Перезапустить ScumMapClient от имени администратора?"):
            if relaunch_as_admin():
                self._on_close()
            else:
                messagebox.showerror("Админ", "Не удалось запросить повышение прав.")

    def _auto_loop(self, interval: int) -> None:
        while not self._stop_workers.wait(interval):
            self.after(0, self._auto_resend)

    def _read_clipboard_any(self) -> str:
        """Win32 (+ PowerShell fallback). Never use Tk clipboard_get — it deadlocks with the poller."""
        return read_clipboard_text(0.45, allow_powershell=True)

    def _clipboard_hint(self, text: str) -> str:
        if looks_like_client_log(text):
            return (
                "в буфере сейчас ЛОГ клиента (не координаты). "
                "В SCUM нажмите Ctrl+C ещё раз — не копируйте лог."
            )
        if not (text or "").strip():
            return "буфер пуст или не удалось прочитать"
        preview = (text or "").replace("\n", " ")[:100]
        return f"в буфере нет {{X=… Y=…}}. Сейчас: {preview!r}"

    def _auto_resend(self) -> None:
        """Every N seconds: resend last known position (no synthetic Ctrl+C)."""
        if not self._hotkeys_on or not self.map_client:
            return
        if self._last_sent:
            self._send_coords(self._last_sent, source="auto/last")
            return
        if self._fresh_clipboard_coords:
            self._send_coords(self._fresh_clipboard_coords, source="auto/clipboard")
            return

        def work() -> None:
            text = read_clipboard_text(0.4, allow_powershell=True)
            clip = parse_scum_clipboard(text)

            def apply() -> None:
                if not self._hotkeys_on:
                    return
                if clip:
                    self._fresh_clipboard_coords = clip
                    self._send_coords(clip, source="auto/clipboard")
                    return
                if not getattr(self, "_auto_warned_empty", False):
                    self._auto_warned_empty = True
                    self.log_line(f"[auto] нет позиции — {self._clipboard_hint(text)}")

            self.after(0, apply)

        threading.Thread(target=work, daemon=True).start()

    def _clipboard_loop(self) -> None:
        last_seq = -1
        while not self._stop_workers.is_set():
            try:
                seq = clipboard_sequence_number()
                # Keep OpenClipboard windows short so F1/UI never stall
                text = (grab_clipboard_text(0.2) or "").strip()
                if not text and seq != last_seq:
                    text = read_clipboard_text(0.3, allow_powershell=True)
            except Exception:
                text = ""
                seq = last_seq
            if not text:
                time.sleep(0.35)
                continue
            if text == self._clipboard_digest and seq == last_seq:
                time.sleep(0.35)
                continue
            last_seq = seq
            self._clipboard_digest = text
            coords = parse_scum_clipboard(text)
            if coords:
                self._fresh_clipboard_coords = coords
                self._clipboard_coords_at = time.time()
                self._auto_warned_empty = False
                preview = text.replace("\n", " ")[:70]
                self.after(
                    0,
                    lambda p=preview: self.log_line(f"[буфер] координаты: {p!r}"),
                )
                self.after(0, lambda c=coords: self._send_coords(c, source="Ctrl+C"))
            elif looks_like_client_log(text) and not getattr(self, "_warned_log_clip", False):
                self._warned_log_clip = True
                self.after(
                    0,
                    lambda: self.log_line(
                        "[буфер] обнаружен лог клиента вместо координат — "
                        "в SCUM нажмите Ctrl+C (не копируйте лог)."
                    ),
                )
            time.sleep(0.35)

    def _manual_copy_send(self) -> None:
        if not self.map_client:
            self._save()
            if not self.map_client:
                return
        self.log_line("[кнопка] читаю буфер…")

        def work() -> None:
            text = read_clipboard_text(0.6, allow_powershell=True)
            clip = parse_scum_clipboard(text)

            def apply() -> None:
                if clip:
                    self._send_coords(clip, source="кнопка/буфер")
                    return
                if self._last_sent:
                    self._send_coords(self._last_sent, source="кнопка/last")
                    return
                hint = self._clipboard_hint(text)
                self.log_line(f"[кнопка] {hint}")
                messagebox.showinfo(
                    "Нет координат",
                    "В буфере нет строки вида {X=… Y=…}.\n\n"
                    "В SCUM нажмите Ctrl+C, затем снова «Из буфера».\n"
                    "Или вставьте строку координат в поле ниже и нажмите «Вставить → отправить».",
                )

            self.after(0, apply)

        threading.Thread(target=work, daemon=True).start()

    def _handle_copy_hotkey(self, force_log: bool = False) -> None:
        if not self._hotkeys_on:
            return
        now = time.time()
        if now - self._last_copy_trigger_at < 0.8:
            return
        self._last_copy_trigger_at = now
        self.log_line("[F1] пойман — читаю буфер…")

        def work() -> None:
            try:
                text = read_clipboard_text(0.6, allow_powershell=True)
            except Exception as exc:
                self.after(0, lambda: self.log_line(f"[F1] ошибка чтения буфера: {exc}"))
                return
            self.after(0, lambda t=text: self._on_f1_clipboard(t))

        threading.Thread(target=work, daemon=True).start()

    def _on_f1_clipboard(self, text: str) -> None:
        clip = parse_scum_clipboard(text)
        if clip:
            self.log_line("[F1] координаты из буфера — отправляю")
            self._clipboard_digest = text
            self._fresh_clipboard_coords = clip
            self._send_coords(clip, source="F1/буфер")
            return

        preview = (text or "").replace("\n", " ")[:80]
        self.log_line(f"[F1] прочитал буфер ({len(text or '')} симв.): {preview!r}")
        if self._last_sent:
            self.log_line("[F1] координат нет — шлю последнюю позицию")
            self._send_coords(self._last_sent, source="F1/last")
            return

        self.log_line(f"[F1] {self._clipboard_hint(text)}")
        self.log_line("[F1] нажмите Ctrl+C в SCUM — клиент подхватит сам")

    def _send_pasted_coords(self) -> None:
        raw = (self.paste_coords_var.get() or "").strip()
        coords = parse_scum_clipboard(raw)
        if not coords:
            messagebox.showinfo(
                "Координаты",
                "Вставьте строку вида\n{X=… Y=… Z=…|P=…}",
            )
            return
        if not self.map_client:
            self._save()
            if not self.map_client:
                return
        self._send_coords(coords, source="вставка")

    def _paste_client_key(self) -> None:
        text = (self._clipboard_get_text() or "").strip()
        if not text:
            messagebox.showinfo("Буфер", "Буфер пуст — скопируйте ключ на сайте.")
            return
        if "\n" in text:
            text = text.splitlines()[0].strip()
        self.key_var.set(text)
        self.log_line(f"Ключ вставлен из буфера ({len(text)} символов)")

    def _toggle_key_visibility(self) -> None:
        self._key_entry_shown = not getattr(self, "_key_entry_shown", False)
        show = "" if self._key_entry_shown else "•"
        try:
            self.key_entry.configure(show=show)
        except Exception:
            pass

    def _copy_log(self) -> None:
        data = self.log.get("1.0", "end-1c")
        if not data.strip():
            messagebox.showinfo("Лог", "Лог пуст")
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(data)
            self.update_idletasks()
            self.log_line("Лог скопирован в буфер (координаты SCUM при этом стёрты)")
        except Exception as exc:
            messagebox.showerror("Лог", f"Не удалось скопировать: {exc}")

    # ------------------------------------------------------------------ capture
    def _send_clipboard_now(self) -> None:
        if not self.map_client:
            self._save()
            if not self.map_client:
                return
        self.log_line("[буфер] читаю…")

        def work() -> None:
            text = read_clipboard_text(0.6, allow_powershell=True)
            coords = parse_scum_clipboard(text)

            def apply() -> None:
                if coords:
                    self._clipboard_digest = text
                    self._fresh_clipboard_coords = coords
                    self._send_coords(coords, source="буфер-кнопка")
                    return
                hint = self._clipboard_hint(text or "")
                self.log_line(f"[буфер] {hint}")
                messagebox.showinfo(
                    "Буфер",
                    "В буфере нет координат вида {X=… Y=…}.\n"
                    "В SCUM нажмите Ctrl+C (карту открывать не нужно).\n"
                    "Или вставьте строку в поле «Или вставьте {X=… Y=…}» ниже.",
                )

            self.after(0, apply)

        threading.Thread(target=work, daemon=True).start()

    def _send_coords(self, coords: tuple[float, float], source: str) -> None:
        if not self.map_client:
            self.log_line("Сначала сохраните настройки (вкладка Настройки)")
            self._show_page(1)
            return
        x, y = coords
        self.log_line(f"[{source}] отправка {x:.1f} / {y:.1f} …")

        def work() -> None:
            try:
                ok, err = self.map_client.send_position(x, y)
            except Exception as exc:
                self.after(0, lambda: self.log_line(f"[{source}] исключение: {exc}"))
                return
            if ok:
                self._last_sent = (x, y)
                self.after(0, lambda: self.log_line(f"[{source}] OK → {x:.1f} / {y:.1f}"))
                self.after(0, lambda: self.status_var.set(f"Позиция {x:.0f} / {y:.0f}"))
            else:
                self.after(0, lambda: self.log_line(f"[{source}] Ошибка API: {err}"))
                if "401" in err or "403" in err:
                    self.after(
                        0,
                        lambda: self.log_line(
                            "Проверьте client key: SCUM-карта → Приложение → скопировать ключ."
                        ),
                    )

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ map commands
    def _handle_zoom_in(self) -> None:
        self._run_command("zoom_in", "приблизить")

    def _handle_zoom_out(self) -> None:
        self._run_command("zoom_out", "отдалить")

    def _handle_focus_me(self) -> None:
        self._run_command("focus_me", "на себя")

    def _run_command(self, action: str, label: str) -> None:
        if not self._hotkeys_on or not self.map_client:
            return

        def work() -> None:
            ok, err = self.map_client.send_command(action)
            self.after(
                0,
                lambda: self.log_line(f"[{label}] OK" if ok else f"[{label}] ошибка: {err}"),
            )

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ updates
    def check_for_updates(self, manual: bool = False) -> None:
        def worker() -> None:
            try:
                r = httpx.get(
                    GITHUB_RELEASES_LATEST,
                    headers={"User-Agent": "ScumMapClient"},
                    timeout=10,
                )
                if r.status_code != 200:
                    if manual:
                        self.after(
                            0,
                            lambda: messagebox.showerror(
                                "Обновление", f"Не удалось проверить: HTTP {r.status_code}"
                            ),
                        )
                    return
                data = r.json()
                tag_name = data.get("tag_name", "")
                version_match = re.search(r"v?(\d+\.\d+\.\d+)", tag_name)
                if not version_match:
                    version_match = re.search(r"v?(\d+\.\d+\.\d+)", data.get("name", ""))
                if not version_match:
                    if manual:
                        self.after(0, lambda: messagebox.showinfo("Обновление", "Версия релиза не распознана"))
                    return
                latest_ver_str = version_match.group(1)
                latest_ver = tuple(int(x) for x in latest_ver_str.split("."))
                curr_ver = tuple(int(x) for x in __version__.lstrip("v").split(".") if x.isdigit())
                if latest_ver > curr_ver:
                    download_url = None
                    for asset in data.get("assets", []):
                        if asset.get("name") == UPDATE_ASSET:
                            download_url = asset.get("browser_download_url")
                            break
                    if not download_url:
                        download_url = (
                            f"https://github.com/Ignor-GTO/dayz-map-and-client-soft/releases/download/"
                            f"{tag_name}/{UPDATE_ASSET}"
                        )
                    self.after(0, lambda: self.prompt_update(f"v{latest_ver_str}", download_url))
                elif manual:
                    self.after(
                        0,
                        lambda: messagebox.showinfo(
                            "Обновление", f"У вас последняя версия ({__version__})"
                        ),
                    )
            except Exception as e:
                if manual:
                    self.after(0, lambda: messagebox.showerror("Обновление", f"Ошибка: {e}"))

        threading.Thread(target=worker, daemon=True).start()

    def prompt_update(self, version: str, download_url: str) -> None:
        if messagebox.askyesno(
            "Доступно обновление",
            f"Доступна новая версия {version}.\nСкачать и установить сейчас?",
        ):
            self.start_downloading_update(download_url)

    def start_downloading_update(self, download_url: str) -> None:
        progress_win = tk.Toplevel(self)
        progress_win.title("Обновление...")
        progress_win.geometry("320x120")
        progress_win.resizable(False, False)
        progress_win.transient(self)
        progress_win.grab_set()
        progress_win.geometry(f"+{self.winfo_x() + 120}+{self.winfo_y() + 180}")
        lbl = ttk.Label(progress_win, text="Скачивание обновления...", font=("Segoe UI", 10))
        lbl.pack(pady=10)
        progress = ttk.Progressbar(progress_win, orient="horizontal", length=260, mode="determinate")
        progress.pack(pady=5)

        def download_worker() -> None:
            try:
                exe_path = sys.executable
                if not getattr(sys, "frozen", False) or not exe_path.endswith(".exe"):
                    time.sleep(1)
                    self.after(0, progress_win.destroy)
                    self.after(0, lambda: messagebox.showinfo("Обновление", "В режиме разработки обновление имитировано."))
                    return
                new_exe = exe_path + ".new"
                old_exe = exe_path + ".old"
                with httpx.stream("GET", download_url, follow_redirects=True, timeout=60) as response:
                    if response.status_code != 200:
                        raise Exception(f"HTTP {response.status_code}")
                    total_bytes = int(response.headers.get("content-length", 0))
                    downloaded = 0
                    with open(new_exe, "wb") as f:
                        for chunk in response.iter_bytes(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                if total_bytes > 0:
                                    percent = int((downloaded / total_bytes) * 100)
                                    self.after(0, lambda p=percent: progress.configure(value=p))
                                    self.after(0, lambda p=percent: lbl.configure(text=f"Скачивание: {p}%"))
                self.after(0, lambda: lbl.configure(text="Установка обновления..."))
                time.sleep(0.4)
                if os.path.exists(old_exe):
                    try:
                        os.remove(old_exe)
                    except Exception:
                        pass
                os.rename(exe_path, old_exe)
                os.rename(new_exe, exe_path)
                env = os.environ.copy()
                for key in list(env.keys()):
                    if "MEIPASS" in key or key.startswith("_PYI_"):
                        env.pop(key, None)
                env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
                creationflags = 0
                if sys.platform == "win32":
                    creationflags = (
                        getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                    )
                subprocess.Popen([exe_path], env=env, close_fds=True, creationflags=creationflags)
                self.after(0, self._on_close)
            except Exception as e:
                self.after(0, progress_win.destroy)
                self.after(0, lambda err=e: messagebox.showerror("Ошибка обновления", f"Не удалось обновить: {err}"))

        threading.Thread(target=download_worker, daemon=True).start()

    def _on_close(self) -> None:
        self._stop_hotkeys()
        self.destroy()


def run_scum_gui() -> None:
    app = ScumMapApp()
    app.mainloop()


if __name__ == "__main__":
    run_scum_gui()
