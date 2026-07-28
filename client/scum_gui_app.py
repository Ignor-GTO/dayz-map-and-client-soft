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
from clipboard_util import grab_clipboard_text
from config import load_config, normalize_hotkey_list, save_config
from scum_coords import parse_scum_clipboard
from version import __version__

try:
    import keyboard
except Exception:  # pragma: no cover
    keyboard = None

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
        self.current_page = 0

        self._cleanup_old_exe()
        self._build_ui()
        self._load_fields()
        self._maybe_init_client()
        self.log_line(f"[Клиент] SCUM v{__version__}")
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

    def _build_main_page(self) -> None:
        card = ttk.LabelFrame(self.main_page, text="Статус", padding=12)
        card.pack(fill="x", pady=(0, 8))
        self.status_var = tk.StringVar(value="Остановлено — нажмите «Запустить»")
        ttk.Label(card, textvariable=self.status_var, style="Status.TLabel").pack(anchor="w")
        ttk.Label(
            card,
            text=(
                "В игре: F1 → show position → выделите строку {X=… Y=…} → Ctrl+C.\n"
                "Клиент читает только буфер обмена (без OCR). M / авто 30 с шлют последнюю известную позицию."
            ),
            style="CardMuted.TLabel",
            wraplength=580,
        ).pack(anchor="w", pady=(6, 0))

        btns = ttk.Frame(self.main_page)
        btns.pack(fill="x", pady=6)
        self.toggle_btn = ttk.Button(btns, text="Запустить", command=self._toggle_hotkeys)
        self.toggle_btn.pack(side="left")
        ttk.Button(btns, text="Отправить из буфера", command=self._send_clipboard_now).pack(side="left", padx=8)

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
        self.key_var = tk.StringVar()
        ttk.Entry(conn, textvariable=self.key_var, show="•", width=64).pack(fill="x")

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
                "0 = только Ctrl+C / M. При 30: каждые 30 с повторно шлёт последнюю позицию из буфера "
                "(после хотя бы одного Ctrl+C)."
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
            ("Отправить позицию", self.hotkey_send_pos_var),
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
                "Читает координаты SCUM из буфера (Ctrl+C по show position) — без OCR.\n"
                "M / авто — повтор последней позиции · Page Up/Down/End — зум и фокус на сайте."
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
        self.hotkey_send_pos_var.set(", ".join(self.settings.get("scum_hotkey_send_pos", ["m"])))

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
        self.settings["scum_hotkey_send_pos"] = self._parse_hotkeys(self.hotkey_send_pos_var.get(), ["m"])
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
        if keyboard is None:
            messagebox.showerror("Ошибка", "Модуль keyboard недоступен")
            return
        if not self.map_client:
            self._save()
            if not self.map_client:
                return
        try:
            self.settings["scum_auto_interval_sec"] = self._auto_interval()
            self.settings["hotkey_zoom_in"] = self._parse_hotkeys(self.hotkey_zoom_in_var.get(), ["page up"])
            self.settings["hotkey_zoom_out"] = self._parse_hotkeys(self.hotkey_zoom_out_var.get(), ["page down"])
            self.settings["hotkey_focus_me"] = self._parse_hotkeys(self.hotkey_focus_me_var.get(), ["end"])
            self.settings["scum_hotkey_send_pos"] = self._parse_hotkeys(self.hotkey_send_pos_var.get(), ["m"])
            save_config(self.settings)
        except Exception:
            pass

        self._stop_workers.clear()
        self._hotkeys_on = True
        self.toggle_btn.configure(text="Остановить")
        interval = self._auto_interval()
        self.status_var.set(
            f"Работает — позиция / Ctrl+C"
            + (f" / авто {interval} с" if interval > 0 else "")
            + " / PageUp·PageDown·End"
        )

        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass

        registered = []
        for hk in self.settings.get("scum_hotkey_send_pos", ["m"]):
            try:
                keyboard.add_hotkey(
                    hk.strip().lower(),
                    lambda: self.after(0, lambda: self._capture_and_send("hotkey")),
                    suppress=False,
                )
                registered.append(hk)
            except Exception as e:
                self.log_line(f"Hotkey «{hk}» warn: {e}")

        for hk in self.settings.get("hotkey_zoom_in", ["page up"]):
            try:
                keyboard.add_hotkey(
                    hk.strip().lower(),
                    lambda: self.after(0, self._handle_zoom_in),
                    suppress=False,
                )
                registered.append(hk)
            except Exception as e:
                self.log_line(f"Hotkey zoom_in «{hk}»: {e}")

        for hk in self.settings.get("hotkey_zoom_out", ["page down"]):
            try:
                keyboard.add_hotkey(
                    hk.strip().lower(),
                    lambda: self.after(0, self._handle_zoom_out),
                    suppress=False,
                )
                registered.append(hk)
            except Exception as e:
                self.log_line(f"Hotkey zoom_out «{hk}»: {e}")

        for hk in self.settings.get("hotkey_focus_me", ["end"]):
            try:
                keyboard.add_hotkey(
                    hk.strip().lower(),
                    lambda: self.after(0, self._handle_focus_me),
                    suppress=False,
                )
                registered.append(hk)
            except Exception as e:
                self.log_line(f"Hotkey focus_me «{hk}»: {e}")

        # Seed clipboard so old copy doesn't fire immediately
        self._clipboard_digest = (grab_clipboard_text() or "").strip() or None
        self._fresh_clipboard_coords = None
        threading.Thread(target=self._clipboard_loop, daemon=True).start()
        if interval > 0:
            threading.Thread(target=self._auto_loop, args=(interval,), daemon=True).start()

        self.log_line(f"Запущено. Клавиши: {', '.join(registered) or '—'}")
        self.log_line("Скопируйте позицию в игре (Ctrl+C) — клиент сразу отправит на карту.")
        self.log_line("Если клавиши молчат в полноэкранной игре — запустите exe от имени администратора.")
        self.after(300, lambda: self._capture_and_send("startup"))

    def _stop_hotkeys(self) -> None:
        self._hotkeys_on = False
        self._stop_workers.set()
        self.toggle_btn.configure(text="Запустить")
        self.status_var.set("Остановлено — нажмите «Запустить»")
        try:
            if keyboard:
                keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        self.log_line("Остановлено")

    def _auto_loop(self, interval: int) -> None:
        while not self._stop_workers.wait(interval):
            self.after(0, lambda: self._capture_and_send(f"auto-{interval}s"))

    def _clipboard_loop(self) -> None:
        while not self._stop_workers.is_set():
            text = grab_clipboard_text()
            digest = (text or "").strip()
            if digest and digest != self._clipboard_digest:
                coords = parse_scum_clipboard(digest)
                self._clipboard_digest = digest
                if coords:
                    self._fresh_clipboard_coords = coords
                    self._clipboard_coords_at = time.time()
                    self.after(0, lambda c=coords: self._send_coords(c, source="Ctrl+C"))
                else:
                    preview = digest.replace("\n", " ")[:100]
                    if "X=" in digest.upper() or "{X" in digest.upper():
                        self.after(0, lambda p=preview: self.log_line(f"[буфер] не распознано: {p!r}"))
            time.sleep(0.35)

    # ------------------------------------------------------------------ capture
    def _send_clipboard_now(self) -> None:
        if not self.map_client:
            self._save()
            if not self.map_client:
                return
        text = grab_clipboard_text()
        coords = parse_scum_clipboard(text)
        if not coords:
            preview = ((text or "").replace("\n", " "))[:120]
            self.log_line(f"[буфер] нет SCUM-координат. Сейчас в буфере: {preview!r}")
            messagebox.showinfo(
                "Буфер",
                "В буфере нет координат вида {X=… Y=…}.\n"
                "В SCUM: F1 → show position → выделите строку → Ctrl+C.",
            )
            return
        self._send_coords(coords, source="буфер-кнопка")

    def _capture_and_send(self, source: str) -> None:
        """Send from clipboard, else last known position. No OCR."""
        clip = parse_scum_clipboard(grab_clipboard_text())
        if clip:
            self._fresh_clipboard_coords = clip
            self._clipboard_coords_at = time.time()
            self._send_coords(clip, source=f"{source}/clipboard")
            return
        if self._fresh_clipboard_coords:
            self._send_coords(self._fresh_clipboard_coords, source=f"{source}/last-clipboard")
            return
        if self._last_sent:
            self._send_coords(self._last_sent, source=f"{source}/last-sent")
            return
        if source == "startup":
            self.log_line("[startup] буфер пуст — скопируйте {X=… Y=…} в игре (Ctrl+C)")
        else:
            self.log_line(f"[{source}] нет координат в буфере. F1 → show position → Ctrl+C")

    def _send_coords(self, coords: tuple[float, float], source: str) -> None:
        if not self.map_client:
            self.log_line("Сначала сохраните настройки (вкладка Настройки)")
            self._show_page(1)
            return
        with self._send_lock:
            x, y = coords
            ok, err = self.map_client.send_position(x, y)
            if ok:
                self._last_sent = (x, y)
                self.log_line(f"[{source}] OK → {x:.1f} / {y:.1f}")
                self.status_var.set(f"Позиция {x:.0f} / {y:.0f}")
            else:
                self.log_line(f"[{source}] Ошибка отправки: {err}")
                if "401" in err or "403" in err:
                    self.log_line("Проверьте client key: войдите на SCUM-карту → Приложение → скопировать ключ.")

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
