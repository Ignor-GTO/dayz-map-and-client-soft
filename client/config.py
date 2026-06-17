import json
import os
import sys
from pathlib import Path

DEFAULT_SERVER = "https://dayz-map.gto-team.uz"

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).resolve().parent

CONFIG_PATH = BASE_DIR / "config.json"


DEFAULT_CONFIG = {
    "server_url": DEFAULT_SERVER,
    "client_key": "",
    "monitor_index": 1,
    "ocr_region": [130, 888, 500, 970],
    "mouse_nudge_before_ocr": True,
    "mouse_nudge_side": "left",
    "mouse_nudge_delay_ms": 400,
    "mouse_nudge_edge_offset": 8,
    "mouse_nudge_restore": True,
    "hotkey_toggle_map": ["m", "num lock"],
    "hotkey_send_marker": ["ctrl+shift+d"],
    "hotkey_snip_coords": ["ctrl+shift+s", "ctrl+shift+c"],
    "hotkey_close_map": ["esc"],
    "ocr_preprocess_mode": "auto",
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    cfg.update(loaded)
        except Exception:
            pass
    return cfg


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
