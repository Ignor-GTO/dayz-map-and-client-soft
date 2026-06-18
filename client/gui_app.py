import io
import json
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from typing import Callable

import keyboard
import pystray
from PIL import Image, ImageDraw

from api_client import MapClient
from capture import grab_region, list_monitors
from clipboard_util import grab_clipboard_image, grab_clipboard_text, prepare_coord_image
from config import load_config, save_config
from ocr import extract_coordinates, extract_coordinates_with_text, parse_coordinates
from region_overlay import OcrRegionEditor
from status_overlay import GameHudOverlay
from ocr_preprocess import IZURVIVE_OCR_REGION
from version import __version__


def create_tray_image() -> Image.Image:
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    dc = ImageDraw.Draw(image)
    dc.ellipse([8, 8, 56, 56], outline=(59, 130, 246, 255), width=4)
    dc.ellipse([28, 28, 36, 36], fill=(16, 185, 129, 255))
    dc.line([32, 4, 32, 18], fill=(59, 130, 246, 255), width=4)
    dc.line([32, 46, 32, 60], fill=(59, 130, 246, 255), width=4)
    dc.line([4, 32, 18, 32], fill=(59, 130, 246, 255), width=4)
    dc.line([46, 32, 60, 32], fill=(59, 130, 246, 255), width=4)
    return image


class ClientApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"DayZ Map Client v{__version__} — GTO Team")
        self.geometry("640x720")
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
        self.current_page = 0

        self.preprocess_modes_map = {
            "Автоматический выбор (Все цвета)": "auto",
            "Белый (на тёмном)": "white",
            "Зелёный / Лайм (на тёмном)": "lime",
            "Высокий контраст (Любой цвет)": "high_contrast",
        }
        self.preprocess_modes_reverse_map = {v: k for k, v in self.preprocess_modes_map.items()}

        self.mouse_nudge_sides_map = {
            "Влево": "left",
            "Вправо": "right",
            "Вверх": "top",
            "Вниз": "bottom",
        }
        self.mouse_nudge_sides_reverse_map = {v: k for k, v in self.mouse_nudge_sides_map.items()}

        self._build_ui()
        self._load_fields()
        self.log_line(f"[Клиент] v{__version__}")
        self.after(400, self._startup_ocr_check)
        self.protocol("WM_DELETE_WINDOW", self._minimize_to_tray)
        self.bind_all("<Control-Key>", self._handle_global_shortcuts)

    def _build_ui(self) -> None:
        self.status_var = tk.StringVar(value="Остановлено")
        # Define modern dark theme colors
        self.bg_color = "#121820"       # Deep dark blue/gray
        self.fg_color = "#e2e8f0"       # Off-white / light slate
        self.accent_color = "#3b82f6"   # Modern blue
        self.accent_hover = "#2563eb"   # Darker blue for hover
        self.card_bg = "#1e293b"        # Slate dark gray for containers
        self.border_color = "#334155"   # Slate border
        self.text_muted = "#94a3b8"     # Gray for captions
        self.success_color = "#10b981"  # Emerald green (OK)
        self.danger_color = "#ef4444"   # Rose red (Error)

        self.configure(bg=self.bg_color)
        
        style = ttk.Style()
        style.theme_use("clam")
        
        # Configure TFrame
        style.configure("TFrame", background=self.bg_color)
        style.configure("Card.TFrame", background=self.card_bg, borderwidth=1, relief="solid")
        
        # Configure TLabelframe
        style.configure("TLabelframe", background=self.card_bg, bordercolor=self.border_color, padding=12)
        style.configure("TLabelframe.Label", background=self.card_bg, foreground=self.accent_color, font=("Segoe UI", 10, "bold"))
        
        # Configure TLabel
        style.configure("TLabel", background=self.bg_color, foreground=self.fg_color, font=("Segoe UI", 10))
        style.configure("Card.TLabel", background=self.card_bg, foreground=self.fg_color, font=("Segoe UI", 10))
        style.configure("Header.TLabel", background=self.bg_color, foreground=self.fg_color, font=("Segoe UI", 13, "bold"))
        style.configure("Muted.TLabel", background=self.bg_color, foreground=self.text_muted, font=("Segoe UI", 9))
        style.configure("CardMuted.TLabel", background=self.card_bg, foreground=self.text_muted, font=("Segoe UI", 9))
        style.configure("Status.TLabel", background=self.card_bg, foreground=self.accent_color, font=("Segoe UI", 10, "bold"))
        
        # Configure TButton
        style.configure("TButton", 
                        background=self.accent_color, 
                        foreground="#ffffff", 
                        bordercolor=self.border_color, 
                        font=("Segoe UI", 9, "bold"), 
                        padding=[10, 5])
        style.map("TButton",
                  background=[("active", self.accent_hover), ("disabled", "#1e293b")],
                  foreground=[("disabled", "#64748b")])
                  
        style.configure("Accent.TButton", 
                        background=self.success_color, 
                        foreground="#ffffff")
        style.map("Accent.TButton",
                  background=[("active", "#059669")])
                  
        style.configure("Action.TButton", 
                        background=self.card_bg, 
                        foreground=self.fg_color,
                        bordercolor=self.border_color)
        style.map("Action.TButton",
                  background=[("active", self.border_color)])
                  
        # Configure TEntry
        style.configure("TEntry", 
                        fieldbackground=self.card_bg, 
                        foreground=self.fg_color, 
                        bordercolor=self.border_color, 
                        insertcolor=self.fg_color,
                        padding=5)
        style.map("TEntry",
                  bordercolor=[("focus", self.accent_color)])
                  
        # Configure TCombobox
        style.configure("TCombobox", 
                        fieldbackground=self.card_bg, 
                        foreground=self.fg_color, 
                        bordercolor=self.border_color,
                        arrowcolor=self.fg_color,
                        padding=5)
        style.map("TCombobox",
                  fieldbackground=[("readonly", self.card_bg)],
                  foreground=[("readonly", self.fg_color)],
                  bordercolor=[("focus", self.accent_color)])
                  
        # Configure TCheckbutton
        style.configure("TCheckbutton", 
                        background=self.bg_color, 
                        foreground=self.fg_color, 
                        indicatorbackground=self.card_bg, 
                        indicatorforeground=self.accent_color)
        style.map("TCheckbutton",
                  background=[("active", self.bg_color)])
                  
        style.configure("Card.TCheckbutton", 
                        background=self.card_bg, 
                        foreground=self.fg_color, 
                        indicatorbackground=self.bg_color, 
                        indicatorforeground=self.accent_color)
        style.map("Card.TCheckbutton",
                  background=[("active", self.card_bg)])

        style.configure("Vertical.TScrollbar", 
                        background=self.card_bg, 
                        troughcolor=self.bg_color, 
                        bordercolor=self.border_color,
                        arrowcolor=self.fg_color)

        style.configure("Header.TFrame", background=self.bg_color)
        style.configure("HeaderTitle.TLabel", background=self.bg_color, foreground=self.accent_color, font=("Segoe UI", 12, "bold"))

        # Header panel
        header_frm = ttk.Frame(self, style="Header.TFrame", padding=10)
        header_frm.pack(fill="x", side="top")
        
        title_lbl = ttk.Label(header_frm, text="🧭 DAYZ GPS ASSISTANT", style="HeaderTitle.TLabel")
        title_lbl.pack(side="left", pady=2)
        
        nav_frm = ttk.Frame(header_frm, style="Header.TFrame")
        nav_frm.pack(side="right")
        
        self.nav_btn_main = ttk.Button(nav_frm, text="Главная", command=lambda: self._show_page(0), style="Accent.TButton", width=12)
        self.nav_btn_main.pack(side="left", padx=2)
        
        self.nav_btn_settings = ttk.Button(nav_frm, text="Настройки", command=lambda: self._show_page(1), style="Action.TButton", width=12)
        self.nav_btn_settings.pack(side="left", padx=2)

        # Pages Container
        self.pages_container = ttk.Frame(self)
        self.pages_container.pack(fill="both", expand=True, padx=5, pady=5)
        
        self.main_page = ttk.Frame(self.pages_container)
        self.settings_page = ttk.Frame(self.pages_container)

        # ---------------- MAIN PAGE ----------------
        main_frm = ttk.Frame(self.main_page, padding=10)
        main_frm.pack(fill="both", expand=True)

        # Status & Hotkeys Control Card
        ctrl_card = ttk.Frame(main_frm, padding=12, style="Card.TFrame")
        ctrl_card.pack(fill="x", pady=(0, 10))

        # Status row
        status_subfrm = ttk.Frame(ctrl_card, style="Card.TFrame")
        status_subfrm.pack(fill="x", pady=(0, 5))
        ttk.Label(status_subfrm, text="Статус службы:", font=("Segoe UI", 10, "bold"), style="Card.TLabel").pack(side="left")
        self.status_label = ttk.Label(status_subfrm, textvariable=self.status_var, style="Status.TLabel")
        self.status_label.pack(side="left", padx=5)

        # Start button row
        btn_subfrm = ttk.Frame(ctrl_card, style="Card.TFrame")
        btn_subfrm.pack(fill="x")
        self.start_btn = ttk.Button(btn_subfrm, text="Запустить hotkeys", command=self.toggle_hotkeys, width=22)
        self.start_btn.pack(side="left", padx=(0, 10))

        # Instructions / Help
        help_card = ttk.Frame(main_frm, padding=12, style="Card.TFrame")
        help_card.pack(fill="x", pady=(0, 10))
        
        ttk.Label(help_card, text="Быстрые действия:", font=("Segoe UI", 10, "bold"), style="Card.TLabel").pack(anchor="w", pady=(0, 5))
        
        self.help_lbl_1 = ttk.Label(
            help_card, 
            text="• Открыть карту / Обновить позицию: клавиша задаётся в настройках",
            style="CardMuted.TLabel"
        )
        self.help_lbl_1.pack(anchor="w")
        self.help_lbl_2 = ttk.Label(
            help_card, 
            text="• Отправить метку на карту: клавиша задаётся в настройках",
            style="CardMuted.TLabel"
        )
        self.help_lbl_2.pack(anchor="w")
        self.help_lbl_3 = ttk.Label(
            help_card, 
            text="• Снимок координат с экрана: клавиша задаётся в настройках",
            style="CardMuted.TLabel"
        )
        self.help_lbl_3.pack(anchor="w")
        self.help_lbl_4 = ttk.Label(
            help_card, 
            text="• Закрыть карту: клавиша закрытия задаётся в настройках",
            style="CardMuted.TLabel"
        )
        self.help_lbl_4.pack(anchor="w")
        self.help_lbl_5 = ttk.Label(
            help_card, 
            text="• Авто-захват из буфера (Win+Shift+S): работает автоматически при запущенных hotkeys",
            style="CardMuted.TLabel"
        )
        self.help_lbl_5.pack(anchor="w")

        # ScrolledText Log
        log_frm = ttk.Frame(main_frm)
        log_frm.pack(fill="both", expand=True)
        ttk.Label(log_frm, text="Лог событий:", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 5))
        
        self.log = scrolledtext.ScrolledText(
            log_frm,
            height=16,
            width=64,
            bg="#1e293b",
            fg="#e2e8f0",
            insertbackground="#e2e8f0",
            highlightthickness=1,
            highlightbackground="#334155",
            highlightcolor="#3b82f6",
            font=("Consolas", 9),
            state="disabled",
            selectbackground="#3b82f6",
            selectforeground="white",
            inactiveselectbackground="#475569"
        )
        self.log.pack(fill="both", expand=True)

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

        # ---------------- SETTINGS PAGE ----------------
        # Fixed Save Button frame at the bottom of settings page
        settings_btn_frame = ttk.Frame(self.settings_page, padding=10)
        settings_btn_frame.pack(side="bottom", fill="x")
        
        save_btn = ttk.Button(settings_btn_frame, text="Сохранить настройки", command=self.save_settings, style="Accent.TButton")
        save_btn.pack(side="right", padx=5)

        # Scrollable Canvas container
        canvas = tk.Canvas(self.settings_page, borderwidth=0, highlightthickness=0, bg=self.bg_color)
        scrollbar = ttk.Scrollbar(self.settings_page, orient="vertical", command=canvas.yview, style="Vertical.TScrollbar")
        scrollable_frame = ttk.Frame(canvas, style="TFrame")

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )

        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Expand scrollable frame to fill canvas width
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(canvas_window, width=e.width),
            add="+"
        )

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Scroll on settings page with mouse wheel
        def _on_mousewheel(event):
            try:
                if self.current_page == 1: # settings page
                    canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except Exception:
                pass
        
        self.bind_all("<MouseWheel>", _on_mousewheel, add="+")

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

        # --- Categories Panels ---
        conn_lf = ttk.LabelFrame(scrollable_frame, text=" Подключение к серверу ", padding=10)
        conn_lf.pack(fill="x", padx=10, pady=5)
        
        ttk.Label(conn_lf, text="URL сервера:", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=4)
        self.server_var = tk.StringVar()
        self.server_entry = ttk.Entry(conn_lf, textvariable=self.server_var, width=40)
        self.server_entry.grid(row=0, column=1, sticky="we", padx=5, pady=4)
        
        ttk.Label(conn_lf, text="Ключ клиента:", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=4)
        self.key_var = tk.StringVar()
        self.key_entry = ttk.Entry(conn_lf, textvariable=self.key_var, width=40, show="*")
        self.key_entry.grid(row=1, column=1, sticky="we", padx=5, pady=4)
        
        conn_lf.columnconfigure(1, weight=1)

        # Capture Panel
        capture_lf = ttk.LabelFrame(scrollable_frame, text=" Экран и захват ", padding=10)
        capture_lf.pack(fill="x", padx=10, pady=5)
        
        ttk.Label(capture_lf, text="Монитор:", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=4)
        self.monitor_var = tk.StringVar()
        self.monitor_combo = ttk.Combobox(capture_lf, textvariable=self.monitor_var, state="readonly", width=30)
        self.monitor_combo.grid(row=0, column=1, sticky="we", padx=5, pady=4)
        self.monitor_combo.bind("<<ComboboxSelected>>", self._on_monitor_changed)
        
        ttk.Button(capture_lf, text="↻", width=3, command=self._refresh_monitors, style="Action.TButton").grid(
            row=0, column=2, sticky="w", padx=5, pady=4
        )
        
        ttk.Label(capture_lf, text="Область OCR (L,T,R,B):", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=4)
        region_frm = ttk.Frame(capture_lf, style="Card.TFrame")
        region_frm.grid(row=1, column=1, columnspan=2, sticky="w", pady=4)
        
        self.region_vars = [tk.IntVar(value=v) for v in self.cfg.get("ocr_region", IZURVIVE_OCR_REGION)]
        for i, var in enumerate(self.region_vars):
            entry = ttk.Entry(region_frm, textvariable=var, width=8)
            entry.pack(side="left", padx=2)
            entry.bind("<Button-3>", self._show_entry_menu)
            
        self.region_btn = ttk.Button(region_frm, text="Редактор", command=self.toggle_ocr_region, style="Action.TButton")
        self.region_btn.pack(side="left", padx=6)
        ttk.Button(region_frm, text="iZurvive", command=self._apply_izurvive_preset, style="Action.TButton").pack(side="left", padx=2)
        
        ttk.Label(capture_lf, text="Цвет текста (OCR режим):", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=4)
        self.ocr_preprocess_mode_var = tk.StringVar()
        self.ocr_preprocess_mode_combo = ttk.Combobox(
            capture_lf,
            textvariable=self.ocr_preprocess_mode_var,
            state="readonly",
            width=30
        )
        self.ocr_preprocess_mode_combo.grid(row=2, column=1, columnspan=2, sticky="we", padx=5, pady=4)
        self.ocr_preprocess_mode_combo["values"] = list(self.preprocess_modes_map.keys())
        
        capture_lf.columnconfigure(1, weight=1)

        # Hotkeys Panel
        hotkey_lf = ttk.LabelFrame(scrollable_frame, text=" Горячие клавиши ", padding=10)
        hotkey_lf.pack(fill="x", padx=10, pady=5)
        
        ttk.Label(hotkey_lf, text="Открыть карту / позиция:", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=4)
        self.hotkey_toggle_map_var = tk.StringVar()
        self.hotkey_toggle_map_entry = ttk.Entry(hotkey_lf, textvariable=self.hotkey_toggle_map_var, width=35)
        self.hotkey_toggle_map_entry.grid(row=0, column=1, sticky="we", padx=5, pady=4)
        
        ttk.Label(hotkey_lf, text="Отправить метку:", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=4)
        self.hotkey_send_marker_var = tk.StringVar()
        self.hotkey_send_marker_entry = ttk.Entry(hotkey_lf, textvariable=self.hotkey_send_marker_var, width=35)
        self.hotkey_send_marker_entry.grid(row=1, column=1, sticky="we", padx=5, pady=4)
        
        ttk.Label(hotkey_lf, text="Снимок координат:", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=4)
        self.hotkey_snip_coords_var = tk.StringVar()
        self.hotkey_snip_coords_entry = ttk.Entry(hotkey_lf, textvariable=self.hotkey_snip_coords_var, width=35)
        self.hotkey_snip_coords_entry.grid(row=2, column=1, sticky="we", padx=5, pady=4)
        
        ttk.Label(hotkey_lf, text="Закрыть карту:", style="Card.TLabel").grid(row=3, column=0, sticky="w", pady=4)
        self.hotkey_close_map_var = tk.StringVar()
        self.hotkey_close_map_entry = ttk.Entry(hotkey_lf, textvariable=self.hotkey_close_map_var, width=35)
        self.hotkey_close_map_entry.grid(row=3, column=1, sticky="we", padx=5, pady=4)
        
        ttk.Label(
            hotkey_lf, 
            text="Можно указать несколько клавиш через запятую (например: m, num lock)", 
            style="CardMuted.TLabel"
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(2, 4))
        
        hotkey_lf.columnconfigure(1, weight=1)

        # Mouse Nudge Panel
        nudge_lf = ttk.LabelFrame(scrollable_frame, text=" Сдвиг курсора мыши перед OCR ", padding=10)
        nudge_lf.pack(fill="x", padx=10, pady=5)
        
        self.mouse_nudge_var = tk.BooleanVar()
        self.mouse_nudge_chk = ttk.Checkbutton(
            nudge_lf,
            text="Сдвигать мышь перед OCR (необходимо для iZurvive)",
            variable=self.mouse_nudge_var,
            style="Card.TCheckbutton"
        )
        self.mouse_nudge_chk.grid(row=0, column=0, columnspan=2, sticky="w", pady=4)
        
        ttk.Label(nudge_lf, text="Направление сдвига:", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=4)
        self.mouse_nudge_side_var = tk.StringVar()
        self.mouse_nudge_side_combo = ttk.Combobox(
            nudge_lf,
            textvariable=self.mouse_nudge_side_var,
            state="readonly",
            width=35
        )
        self.mouse_nudge_side_combo.grid(row=1, column=1, sticky="we", padx=5, pady=4)
        self.mouse_nudge_side_combo["values"] = list(self.mouse_nudge_sides_map.keys())
        
        ttk.Label(nudge_lf, text="Задержка сдвига (мс):", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=4)
        self.mouse_nudge_delay_var = tk.StringVar()
        self.mouse_nudge_delay_entry = ttk.Entry(nudge_lf, textvariable=self.mouse_nudge_delay_var, width=35)
        self.mouse_nudge_delay_entry.grid(row=2, column=1, sticky="we", padx=5, pady=4)
        
        ttk.Label(nudge_lf, text="Отступ от края экрана (пкс):", style="Card.TLabel").grid(row=3, column=0, sticky="w", pady=4)
        self.mouse_nudge_offset_var = tk.StringVar()
        self.mouse_nudge_offset_entry = ttk.Entry(nudge_lf, textvariable=self.mouse_nudge_offset_var, width=35)
        self.mouse_nudge_offset_entry.grid(row=3, column=1, sticky="we", padx=5, pady=4)
        
        self.mouse_nudge_restore_var = tk.BooleanVar()
        self.mouse_nudge_restore_chk = ttk.Checkbutton(
            nudge_lf,
            text="Возвращать курсор мыши в исходное положение",
            variable=self.mouse_nudge_restore_var,
            style="Card.TCheckbutton"
        )
        self.mouse_nudge_restore_chk.grid(row=4, column=0, columnspan=2, sticky="w", pady=4)
        
        nudge_lf.columnconfigure(1, weight=1)

        # Diagnostics Panel
        diag_lf = ttk.LabelFrame(scrollable_frame, text=" Диагностика и проверка OCR ", padding=10)
        diag_lf.pack(fill="x", padx=10, pady=5)
        
        diag_btn_frm = ttk.Frame(diag_lf, style="Card.TFrame")
        diag_btn_frm.pack(fill="x", pady=4)
        
        ttk.Button(diag_btn_frm, text="Тест OCR (M)", command=self.test_ocr, style="Action.TButton").pack(side="left", padx=2, expand=True, fill="x")
        ttk.Button(diag_btn_frm, text="Проверить OCR", command=self.check_ocr, style="Action.TButton").pack(side="left", padx=2, expand=True, fill="x")
        ttk.Button(diag_btn_frm, text="Установить Windows OCR", command=self.install_windows_ocr, style="Action.TButton").pack(side="left", padx=2, expand=True, fill="x")

        # Bind context menu to entries
        for entry in [
            self.server_entry, 
            self.key_entry, 
            self.hotkey_toggle_map_entry, 
            self.hotkey_send_marker_entry, 
            self.hotkey_snip_coords_entry, 
            self.hotkey_close_map_entry,
            self.mouse_nudge_delay_entry,
            self.mouse_nudge_offset_entry
        ]:
            entry.bind("<Button-3>", self._show_entry_menu)

        # Show default page
        self._show_page(0)

        # Create tray icon
        self._create_tray_icon()

        self._refresh_monitors()

    def _show_page(self, page_index: int) -> None:
        self.current_page = page_index
        if page_index == 0:
            self.settings_page.pack_forget()
            self.main_page.pack(fill="both", expand=True)
            self.nav_btn_main.configure(style="Accent.TButton")
            self.nav_btn_settings.configure(style="Action.TButton")
        elif page_index == 1:
            self.main_page.pack_forget()
            self.settings_page.pack(fill="both", expand=True)
            self.nav_btn_main.configure(style="Action.TButton")
            self.nav_btn_settings.configure(style="Accent.TButton")

    def _create_tray_icon(self) -> None:
        self.tray_image = create_tray_image()
        self.tray_menu = pystray.Menu(
            pystray.MenuItem("Открыть", self._restore_from_tray, default=True),
            pystray.MenuItem("Выход", self._quit_app)
        )
        self.tray_icon = pystray.Icon(
            "dayz_gps_assistant",
            self.tray_image,
            title="DayZ GPS Assistant",
            menu=self.tray_menu
        )
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _minimize_to_tray(self) -> None:
        self.withdraw()
        self.log_line("[Трей] Приложение свернуто в трей.")

    def _restore_from_tray(self, icon=None, item=None) -> None:
        self.after(0, self._restore_gui)

    def _restore_gui(self) -> None:
        self.deiconify()
        self.focus_force()
        self.lift()

    def _quit_app(self, icon=None, item=None) -> None:
        self.after(0, self.on_close)

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
        
        # Preprocess mode
        mode_val = self.cfg.get("ocr_preprocess_mode", "auto")
        self.ocr_preprocess_mode_var.set(self.preprocess_modes_reverse_map.get(mode_val, "Автоматический выбор (Все цвета)"))
        
        # Hotkeys
        self.hotkey_toggle_map_var.set(", ".join(self.cfg.get("hotkey_toggle_map", ["m", "num lock"])))
        self.hotkey_send_marker_var.set(", ".join(self.cfg.get("hotkey_send_marker", ["ctrl+shift+d"])))
        self.hotkey_snip_coords_var.set(", ".join(self.cfg.get("hotkey_snip_coords", ["ctrl+shift+s", "ctrl+shift+c"])))
        self.hotkey_close_map_var.set(", ".join(self.cfg.get("hotkey_close_map", ["esc"])))
        
        # Mouse nudge settings
        self.mouse_nudge_var.set(self.cfg.get("mouse_nudge_before_ocr", True))
        nudge_side = self.cfg.get("mouse_nudge_side", "left")
        self.mouse_nudge_side_var.set(self.mouse_nudge_sides_reverse_map.get(nudge_side, "Влево"))
        self.mouse_nudge_delay_var.set(str(self.cfg.get("mouse_nudge_delay_ms", 400)))
        self.mouse_nudge_offset_var.set(str(self.cfg.get("mouse_nudge_edge_offset", 8)))
        self.mouse_nudge_restore_var.set(self.cfg.get("mouse_nudge_restore", True))
        self._update_help_labels()

    def _update_help_labels(self) -> None:
        toggle_keys = ", ".join(self.cfg.get("hotkey_toggle_map", ["m", "num lock"])).upper()
        send_keys = ", ".join(self.cfg.get("hotkey_send_marker", ["ctrl+shift+d"])).upper()
        snip_keys = ", ".join(self.cfg.get("hotkey_snip_coords", ["ctrl+shift+s", "ctrl+shift+c"])).upper()
        close_keys = ", ".join(self.cfg.get("hotkey_close_map", ["esc"])).upper()
        
        self.help_lbl_1.configure(text=f"• Открыть карту / Обновить позицию: {toggle_keys}")
        self.help_lbl_2.configure(text=f"• Отправить метку на карту: {send_keys}")
        self.help_lbl_3.configure(text=f"• Снимок координат с экрана: {snip_keys}")
        self.help_lbl_4.configure(text=f"• Закрыть карту: {close_keys}")

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
            
        # Hotkeys validation
        hotkey_fields = {
            "Открыть карту/позиция": (self.hotkey_toggle_map_var.get(), "hotkey_toggle_map"),
            "Отправить метку": (self.hotkey_send_marker_var.get(), "hotkey_send_marker"),
            "Снимок координат": (self.hotkey_snip_coords_var.get(), "hotkey_snip_coords"),
            "Закрыть карту": (self.hotkey_close_map_var.get(), "hotkey_close_map"),
        }
        
        parsed_hotkeys = {}
        for label, (value_str, config_key) in hotkey_fields.items():
            parts = [p.strip().lower() for p in value_str.split(",") if p.strip()]
            for p in parts:
                try:
                    keyboard.parse_hotkey(p)
                except Exception:
                    messagebox.showerror("Ошибка", f"Недопустимое сочетание клавиш для '{label}': '{p}'")
                    return
            parsed_hotkeys[config_key] = parts

        # Parse and validate numeric settings
        try:
            delay = int(self.mouse_nudge_delay_var.get())
            if delay < 0:
                raise ValueError()
        except ValueError:
            messagebox.showerror("Ошибка", "Задержка мыши должна быть целым неотрицательным числом")
            return

        try:
            offset = int(self.mouse_nudge_offset_var.get())
            if offset < 0:
                raise ValueError()
        except ValueError:
            messagebox.showerror("Ошибка", "Отступ мыши должен быть целым неотрицательным числом")
            return

        monitor_index = self.monitor_combo.current() + 1 if self._monitors else 1
        ocr_mode = self.preprocess_modes_map.get(self.ocr_preprocess_mode_var.get(), "auto")
        nudge_side = self.mouse_nudge_sides_map.get(self.mouse_nudge_side_var.get(), "left")
        
        self.cfg.update(
            {
                "server_url": self.server_var.get().strip(),
                "client_key": self.key_var.get().strip(),
                "monitor_index": monitor_index,
                "ocr_region": [v.get() for v in self.region_vars],
                "ocr_preprocess_mode": ocr_mode,
                "hotkey_toggle_map": parsed_hotkeys["hotkey_toggle_map"],
                "hotkey_send_marker": parsed_hotkeys["hotkey_send_marker"],
                "hotkey_snip_coords": parsed_hotkeys["hotkey_snip_coords"],
                "hotkey_close_map": parsed_hotkeys["hotkey_close_map"],
                "mouse_nudge_before_ocr": self.mouse_nudge_var.get(),
                "mouse_nudge_side": nudge_side,
                "mouse_nudge_delay_ms": delay,
                "mouse_nudge_edge_offset": offset,
                "mouse_nudge_restore": self.mouse_nudge_restore_var.get(),
            }
        )
        save_config(self.cfg)
        self.map_client = MapClient(self.cfg["server_url"], self.cfg["client_key"])
        self._update_help_labels()
        self.log_line("[OK] Настройки сохранены")
        
        if self.hotkeys_active:
            self.stop_hotkeys()
            self.start_hotkeys()

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
        import ctypes
        try:
            is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            is_admin = False

        if is_admin:
            self.log_line("[ОК] Клиент запущен с правами администратора.")
        else:
            self.log_line(
                "[Внимание] Клиент запущен БЕЗ прав администратора!\n"
                "Эмуляция клавиш (например, открытие карты по Num Lock) может не работать в игре.\n"
                "Рекомендуется запустить клиент от имени Администратора."
            )

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
        side_ru = self.mouse_nudge_side_var.get()
        side_en = self.mouse_nudge_sides_map.get(side_ru, "left")
        
        try:
            delay = int(self.mouse_nudge_delay_var.get())
        except ValueError:
            delay = 400
            
        try:
            offset = int(self.mouse_nudge_offset_var.get())
        except ValueError:
            offset = 8
            
        return {
            "enabled": self.mouse_nudge_var.get(),
            "side": side_en,
            "delay_ms": delay,
            "restore": self.mouse_nudge_restore_var.get(),
            "edge_offset": offset,
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
        
        toggle_keys = self.cfg.get("hotkey_toggle_map", ["m", "num lock"])
        self.status_var.set(f"Работает — {', '.join(toggle_keys).upper()} открыть карту")
        self.start_btn.configure(text="Остановить hotkeys")
        
        for hk in toggle_keys:
            if hk.strip():
                keyboard.add_hotkey(
                    hk.strip().lower(), 
                    lambda key=hk: self.after(0, lambda: self._handle_m_hotkey(key)), 
                    suppress=False
                )
                
        for hk in self.cfg.get("hotkey_send_marker", ["ctrl+shift+d"]):
            if hk.strip():
                keyboard.add_hotkey(hk.strip().lower(), lambda: self.after(0, self._handle_marker_hotkey), suppress=False)
                
        for hk in self.cfg.get("hotkey_snip_coords", ["ctrl+shift+s", "ctrl+shift+c"]):
            if hk.strip():
                keyboard.add_hotkey(hk.strip().lower(), lambda: self.after(0, self._handle_snip_hotkey), suppress=False)
                
        for hk in self.cfg.get("hotkey_close_map", ["esc"]):
            if hk.strip():
                keyboard.add_hotkey(hk.strip().lower(), lambda: self.after(0, self._handle_esc_hotkey), suppress=False)
                
        self._stop_clipboard.clear()
        threading.Thread(target=self._clipboard_loop, daemon=True).start()
        self.log_line(
            f"[Запуск] Hotkeys: "
            f"карта: {', '.join(toggle_keys).upper()}, "
            f"метка: {', '.join(self.cfg.get('hotkey_send_marker', ['ctrl+shift+d'])).upper()}, "
            f"снимок: {', '.join(self.cfg.get('hotkey_snip_coords', ['ctrl+shift+s', 'ctrl+shift+c'])).upper()}, "
            f"закрыть: {', '.join(self.cfg.get('hotkey_close_map', ['esc'])).upper()}; "
            f"Win+Shift+S — авто из буфера"
        )

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
        toggle_keys = self.cfg.get("hotkey_toggle_map", ["m", "num lock"])
        send_keys = self.cfg.get("hotkey_send_marker", ["ctrl+shift+d"])
        if self._map_session_active:
            self.status_var.set(f"Карта открыта — {', '.join(toggle_keys).upper()} закрыть · {', '.join(send_keys).upper()} — метка")
        else:
            self.status_var.set(f"Работает — {', '.join(toggle_keys).upper()} открыть карту / позиция")

    def _capture_coords(self, *, nudge: bool, check_cancel: Callable[[], bool] | None = None) -> tuple[float, float] | None:
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

            with_mouse_nudge(
                monitor, 
                region, 
                capture, 
                check_cancel=check_cancel,
                **self._mouse_nudge_kwargs()
            )
        else:
            capture()

        if err := result.get("error"):
            raise err
        raw = result.get("raw")
        if raw and not (check_cancel and check_cancel()):
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

    def _handle_m_hotkey(self, pressed_key: str = "m") -> None:
        if not self.map_client:
            return

        if self._map_session_active:
            self._end_map_session()
            if pressed_key.strip().lower() != "m":
                try:
                    keyboard.press("m")
                    self.after(100, lambda: keyboard.release("m"))
                except Exception as e:
                    self.log_line(f"[Ошибка] Не удалось симулировать нажатие 'M': {e}")
            return

        self._start_map_session()
        if pressed_key.strip().lower() != "m":
            try:
                keyboard.press("m")
                self.after(100, lambda: keyboard.release("m"))
            except Exception as e:
                self.log_line(f"[Ошибка] Не удалось симулировать нажатие 'M': {e}")

        self._ensure_hud().show_busy("Позиция игрока…")

        def work() -> None:
            try:
                def is_cancelled() -> bool:
                    return not self._map_session_active

                coords = self._capture_coords(nudge=True, check_cancel=is_cancelled)
                if is_cancelled():
                    return

                if coords:
                    x, y = coords
                    self._session_player_coords = (x, y)
                    self.after(0, lambda: self.log_line(f"[M] {x:.0f} / {y:.0f}"))
                    if self.map_client:
                        ok, err_msg = self.map_client.send_position(x, y)
                        if is_cancelled():
                            return
                        if ok:
                            self.after(0, lambda: self.log_line("[M] Позиция отправлена"))
                            self.after(0, lambda: self._ensure_hud().show_ok(x, y))
                        else:
                            self.after(0, lambda t=err_msg: self.log_line(f"[M] Ошибка отправки: {t}"))
                            self.after(0, lambda: self._ensure_hud().show_error("Ошибка отправки"))
                    if not is_cancelled():
                        self.after(0, lambda: self._ensure_hud().show_map_session())
                else:
                    self.after(0, lambda: self.log_line("[M] Координаты не распознаны"))
                    self.after(0, lambda: self._ensure_hud().show_error("OCR не распознал"))
                    self.after(0, lambda: self._ensure_hud().show_map_session())
            except Exception as exc:
                if is_cancelled():
                    return
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
        from clipboard_util import has_clipboard_image
        time.sleep(0.5)
        img = self._clipboard_image()
        if img is not None:
            self._clipboard_hash = self._image_hash(img)
        while not self._stop_clipboard.is_set():
            if self.map_client and has_clipboard_image():
                img = self._clipboard_image()
                if img is not None:
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
        if hasattr(self, "tray_icon") and self.tray_icon:
            self.tray_icon.stop()
        self.destroy()


def run_gui() -> None:
    app = ClientApp()
    app.mainloop()
