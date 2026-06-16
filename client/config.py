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


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {
        "server_url": DEFAULT_SERVER,
        "client_key": "",
        "monitor_index": 1,
        "ocr_region": [210, 915, 330, 945],
        "mouse_nudge_before_ocr": True,
        "mouse_nudge_delay_ms": 200,
        "mouse_nudge_restore": True,
    }


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
