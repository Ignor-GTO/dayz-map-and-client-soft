"""SCUM Map Client — map overlay (F1), zoom/focus hotkeys, SteamID sync, auto-update."""

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
from clipboard_util import read_clipboard_text
from config import load_config, normalize_hotkey_list, save_config
from map_overlay import ScumMapOverlay
from steam_id import detect_local_steam_id
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
        self._hotkeys = GlobalHotkeyListener()
        self._map_overlay = ScumMapOverlay()
        self.current_page = 0
        self._last_overlay_toggle_at = 0.0

        self._cleanup_old_exe()
        self._build_ui()
        self._load_fields()
        self._maybe_init_client()
        self.log_line(f"[Клиент] SCUM v{__version__}")
        if is_admin():
            self.log_line("Права: администратор — OK для перехвата F1 в игре.")
        else:
            self.log_line("Права: ОБЫЧНЫЕ. Если SCUM от админа — F1 не увидим. Нажмите «От админа».")
        self.log_line("Вставьте ключ → Настройки → Сохранить → «Запустить» → F1 = карта поверх игры.")
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
                "Позиция на карте приходит с игрового сервера (SteamID).\n"
                "F1 — открыть/закрыть веб-карту поверх SCUM (оверлей).\n"
                "Page Up / Page Down / End — зум и фокус на карте."
            ),
            style="CardMuted.TLabel",
            wraplength=580,
        ).pack(anchor="w", pady=(6, 0))

        btns = ttk.Frame(self.main_page)
        btns.pack(fill="x", pady=6)
        self.toggle_btn = ttk.Button(btns, text="Запустить", command=self._toggle_hotkeys)
        self.toggle_btn.pack(side="left")
        ttk.Button(btns, text="Карта (F1)", command=self._toggle_map_overlay).pack(side="left", padx=6)
        ttk.Button(btns, text="Копировать лог", command=self._copy_log).pack(side="left", padx=6)
        if not is_admin():
            ttk.Button(btns, text="От админа", command=self._relaunch_admin).pack(side="left", padx=6)

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

        ttk.Label(conn, text="SteamID64 (авто)", style="Card.TLabel").pack(anchor="w", pady=(8, 0))
        steam_row = ttk.Frame(conn, style="Card.TFrame")
        steam_row.pack(fill="x")
        self.steam_id_var = tk.StringVar()
        ttk.Entry(steam_row, textvariable=self.steam_id_var, width=40).pack(side="left", fill="x", expand=True)
        ttk.Button(steam_row, text="Определить", command=self._detect_steam_id).pack(side="left", padx=(8, 0))
        ttk.Label(
            conn,
            text="Берётся из активного аккаунта Steam на этом ПК. Нужен для позиций с сервера.",
            style="CardMuted.TLabel",
            wraplength=560,
        ).pack(anchor="w", pady=(4, 0))

        hk = ttk.LabelFrame(body, text="Горячие клавиши", padding=10)
        hk.pack(fill="x", pady=6)
        ttk.Label(
            hk,
            text="F1 — оверлей карты поверх SCUM. Page Up / Page Down / End — зум и фокус на карте.",
            style="CardMuted.TLabel",
            wraplength=560,
        ).pack(anchor="w", pady=(0, 8))
        self.hotkey_zoom_in_var = tk.StringVar()
        self.hotkey_zoom_out_var = tk.StringVar()
        self.hotkey_focus_me_var = tk.StringVar()
        self.hotkey_overlay_var = tk.StringVar()
        for label, var in (
            ("Оверлей карты (F1)", self.hotkey_overlay_var),
            ("Приблизить (zoom in)", self.hotkey_zoom_in_var),
            ("Отдалить (zoom out)", self.hotkey_zoom_out_var),
            ("Найти себя (focus me)", self.hotkey_focus_me_var),
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
                "Позиция игрока на карте — с игрового сервера (по SteamID).\n"
                "F1 — карта поверх игры (WebView2). Page Up/Down/End — зум и фокус."
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
        self.hotkey_zoom_in_var.set(", ".join(self.settings.get("hotkey_zoom_in", ["page up"])))
        self.hotkey_zoom_out_var.set(", ".join(self.settings.get("hotkey_zoom_out", ["page down"])))
        self.hotkey_focus_me_var.set(", ".join(self.settings.get("hotkey_focus_me", ["end"])))
        overlay_keys = self.settings.get("scum_hotkey_toggle_overlay")
        if not overlay_keys:
            overlay_keys = self.settings.get("scum_hotkey_send_pos", ["f1"])
        if overlay_keys == ["m"]:
            overlay_keys = ["f1"]
        self.settings["scum_hotkey_toggle_overlay"] = overlay_keys
        self.hotkey_overlay_var.set(", ".join(overlay_keys))
        stored = (self.settings.get("steam_id") or "").strip()
        if stored:
            self.steam_id_var.set(stored)
        else:
            self.after(300, self._detect_steam_id_silent)

    def _detect_steam_id_silent(self) -> None:
        sid, source = detect_local_steam_id()
        if not sid:
            self.log_line("[Steam] ID не найден — запустите Steam и нажмите «Определить» в Настройках")
            return
        self.steam_id_var.set(sid)
        self.settings["steam_id"] = sid
        try:
            save_config(self.settings)
        except Exception:
            pass
        self.log_line(f"[Steam] определён {sid} ({source})")
        self._sync_steam_id_to_server(sid, quiet=True)

    def _detect_steam_id(self) -> None:
        sid, source = detect_local_steam_id()
        if not sid:
            messagebox.showwarning(
                "SteamID",
                "Не удалось определить SteamID.\n"
                "Запустите клиент Steam под нужным аккаунтом и попробуйте снова.",
            )
            return
        self.steam_id_var.set(sid)
        self.settings["steam_id"] = sid
        self.log_line(f"[Steam] определён {sid} ({source})")
        if self.map_client or (self.server_var.get().strip() and self.key_var.get().strip()):
            self._sync_steam_id_to_server(sid, quiet=False)
        else:
            messagebox.showinfo("SteamID", f"Найден: {sid}\n\nСохраните client key, чтобы привязать к профилю на карте.")

    def _sync_steam_id_to_server(self, steam_id: str | None = None, *, quiet: bool = False) -> None:
        sid = (steam_id or self.steam_id_var.get() or self.settings.get("steam_id") or "").strip()
        if not sid:
            return
        client = self.map_client
        if not client:
            server = (self.server_var.get() or self.settings.get("server_url") or "").strip()
            key = (self.key_var.get() or self.settings.get("client_key") or "").strip()
            if server and key:
                client = MapClient(server, key)
            else:
                return

        def work() -> None:
            ok, err = client.set_steam_id(sid)

            def apply() -> None:
                if ok:
                    self.settings["steam_id"] = sid
                    try:
                        save_config(self.settings)
                    except Exception:
                        pass
                    self.log_line(f"[Steam] привязан к профилю карты: {sid}")
                    if not quiet:
                        messagebox.showinfo("SteamID", f"Привязан к профилю:\n{sid}")
                else:
                    self.log_line(f"[Steam] не удалось отправить на сервер: {err}")
                    if not quiet:
                        messagebox.showerror("SteamID", f"Не удалось сохранить на сервере:\n{err}")

            self.after(0, apply)

        threading.Thread(target=work, daemon=True).start()

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
        self.settings["hotkey_zoom_in"] = self._parse_hotkeys(self.hotkey_zoom_in_var.get(), ["page up"])
        self.settings["hotkey_zoom_out"] = self._parse_hotkeys(self.hotkey_zoom_out_var.get(), ["page down"])
        self.settings["hotkey_focus_me"] = self._parse_hotkeys(self.hotkey_focus_me_var.get(), ["end"])
        self.settings["scum_hotkey_toggle_overlay"] = self._parse_hotkeys(
            self.hotkey_overlay_var.get(), ["f1"]
        )
        sid = (self.steam_id_var.get() or "").strip()
        if sid:
            self.settings["steam_id"] = sid
        save_config(self.settings)
        self.map_client = MapClient(server, key)
        self.log_line("Настройки сохранены")
        if not self._hotkeys_on:
            self.status_var.set("Готов — нажмите «Запустить»")
        if sid:
            self._sync_steam_id_to_server(sid, quiet=True)
        elif not (self.steam_id_var.get() or "").strip():
            self._detect_steam_id_silent()
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
            self.settings["hotkey_zoom_in"] = self._parse_hotkeys(self.hotkey_zoom_in_var.get(), ["page up"])
            self.settings["hotkey_zoom_out"] = self._parse_hotkeys(self.hotkey_zoom_out_var.get(), ["page down"])
            self.settings["hotkey_focus_me"] = self._parse_hotkeys(self.hotkey_focus_me_var.get(), ["end"])
            self.settings["scum_hotkey_toggle_overlay"] = self._parse_hotkeys(
                self.hotkey_overlay_var.get(), ["f1"]
            )
            save_config(self.settings)
        except Exception:
            pass

        self._stop_workers.clear()
        self._hotkeys_on = True
        self.toggle_btn.configure(text="Остановить")
        self.status_var.set("Работает — F1 оверлей карты · PageUp/Down/End зум")

        bindings: list[tuple[str, int, str]] = []
        for hk in self.settings.get("scum_hotkey_toggle_overlay", ["f1"]):
            vk = resolve_vk(hk)
            if vk is None:
                self.log_line(f"Неизвестная клавиша оверлея: {hk}")
                continue
            bindings.append(("toggle_overlay", vk, hk))
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

        names = [f"{a}:{n}" for a, _vk, n in bindings]
        self.log_line(f"Запущено: {', '.join(names)}")
        self.log_line("F1 — карта поверх игры. Позиция идёт с сервера по SteamID.")
        sid = (self.steam_id_var.get() or self.settings.get("steam_id") or "").strip()
        if sid:
            self._sync_steam_id_to_server(sid, quiet=True)
        else:
            self._detect_steam_id_silent()
        if not is_admin():
            self.log_line("⚠ Не админ: для хоткеев лучше «От админа».")

    def _on_global_hotkey(self, action: str, name: str) -> None:
        if not self._hotkeys_on:
            return
        if action == "toggle_overlay":
            self.after(0, self._toggle_map_overlay)
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

    def _toggle_map_overlay(self) -> None:
        if not self.map_client:
            self._save()
            if not self.map_client:
                return
        now = time.time()
        if now - self._last_overlay_toggle_at < 0.6:
            return
        self._last_overlay_toggle_at = now
        self.log_line("[F1] открываю оверлей…")

        def url_factory() -> str | None:
            url, err = self.map_client.create_overlay_handoff(
                self.settings.get("map_slug") or "scum"
            )
            if not url:
                raise RuntimeError(err or "Нет URL оверлея")
            return url

        def work() -> None:
            try:
                visible = self._map_overlay.toggle(url_factory)

                def apply() -> None:
                    if visible:
                        self.log_line(
                            "[F1] оверлей запущен (окно поверх). "
                            "Если не видно — в SCUM поставьте Borderless / Windowed."
                        )
                    else:
                        self.log_line("[F1] оверлей закрыт")

                self.after(0, apply)
            except Exception as exc:
                msg = str(exc)
                self.after(0, lambda m=msg: self.log_line(f"[F1] оверлей: {m}"))
                self.after(
                    0,
                    lambda m=msg: messagebox.showerror(
                        "Оверлей карты",
                        f"{m}\n\n"
                        "1) Задеплойте сервер с /api/auth/overlay-handoff\n"
                        "2) Edge WebView2 Runtime\n"
                        "3) SCUM: Borderless windowed (не Exclusive fullscreen)\n"
                        "4) Клиент собран с pywebview",
                    ),
                )

        threading.Thread(target=work, daemon=True).start()

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
            self.log_line("Лог скопирован в буфер")
        except Exception as exc:
            messagebox.showerror("Лог", f"Не удалось скопировать: {exc}")

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
        try:
            self._map_overlay.destroy()
        except Exception:
            pass
        self._stop_hotkeys()
        self.destroy()


def run_scum_gui() -> None:
    app = ScumMapApp()
    app.mainloop()


if __name__ == "__main__":
    run_scum_gui()
