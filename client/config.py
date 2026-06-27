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


def normalize_hotkey_token(token: str) -> str:
    t = (token or "").strip().lower()
    if t in {"*", "multiply", "kp multiply", "numpad multiply"}:
        return "num *"
    if t in {"/", "divide", "kp divide", "numpad divide"}:
        return "num /"
    if t in {"+", "add", "kp add", "numpad add"}:
        return "num +"
    if t in {"-", "subtract", "kp subtract", "numpad subtract"}:
        return "num -"
    return t


def normalize_hotkey_list(values: list[str]) -> list[str]:
    normalized = [normalize_hotkey_token(v) for v in values if str(v).strip()]
    # Keep order, remove duplicates
    return list(dict.fromkeys(normalized))


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
    "hotkey_toggle_map": ["num lock"],
    "game_map_key": "m",
    "hotkey_send_marker": ["ctrl+shift+d"],
    "hotkey_snip_coords": ["ctrl+shift+s", "ctrl+shift+c"],
    "hotkey_close_map": ["esc"],
    "hotkey_zoom_in": ["page up"],
    "hotkey_zoom_out": ["page down"],
    "hotkey_focus_me": ["end"],
    "ocr_preprocess_mode": "auto",
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    # Migration: if hotkey_toggle_map contains both "m" and "num lock" (old behavior),
                    # split them by removing "m" from toggle keys and setting game_map_key to "m"
                    if "hotkey_toggle_map" in loaded and isinstance(loaded["hotkey_toggle_map"], list):
                        toggle_list = normalize_hotkey_list(loaded["hotkey_toggle_map"])
                        if "m" in toggle_list and len(toggle_list) > 1:
                            loaded["hotkey_toggle_map"] = [k for k in toggle_list if k != "m"]
                            if "game_map_key" not in loaded:
                                loaded["game_map_key"] = "m"
                        # Migration: on some keyboards NumLock can be recorded as plain "8".
                        # This causes accidental triggering when pressing digit 8.
                        if "8" in toggle_list:
                            fixed_toggle = [
                                "num lock" if k == "8" else k for k in toggle_list
                            ]
                            loaded["hotkey_toggle_map"] = list(dict.fromkeys(fixed_toggle))
                    # Normalize all stored hotkey lists so numpad symbols are unambiguous.
                    for key in (
                        "hotkey_toggle_map",
                        "hotkey_send_marker",
                        "hotkey_snip_coords",
                        "hotkey_close_map",
                        "hotkey_zoom_in",
                        "hotkey_zoom_out",
                        "hotkey_focus_me",
                    ):
                        if key in loaded and isinstance(loaded[key], list):
                            loaded[key] = normalize_hotkey_list(loaded[key])
                    if "game_map_key" in loaded and isinstance(loaded["game_map_key"], str):
                        loaded["game_map_key"] = normalize_hotkey_token(loaded["game_map_key"])
                    # Migration: old defaults Num+/Num- are unreliable on some layouts.
                    # If user still has untouched defaults, switch to PageUp/PageDown.
                    if (
                        isinstance(loaded.get("hotkey_zoom_in"), list)
                        and isinstance(loaded.get("hotkey_zoom_out"), list)
                    ):
                        zoom_in = [k.strip().lower() for k in loaded.get("hotkey_zoom_in", []) if k.strip()]
                        zoom_out = [k.strip().lower() for k in loaded.get("hotkey_zoom_out", []) if k.strip()]
                        if zoom_in == ["num +"] and zoom_out == ["num -"]:
                            loaded["hotkey_zoom_in"] = ["page up"]
                            loaded["hotkey_zoom_out"] = ["page down"]
                    cfg.update(loaded)
        except Exception:
            pass
    return cfg


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
