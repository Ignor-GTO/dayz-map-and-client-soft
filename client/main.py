import io
import sys
import threading
import time

import keyboard
from PIL import ImageGrab

from api_client import MapClient
from config import load_config, save_config
from ocr import extract_coordinates, ocr_from_screen, setup_tesseract


def prompt_setup(cfg: dict) -> dict:
    if cfg.get("client_key"):
        return cfg

    print("=== DayZ Map Client — первый запуск ===")
    print("1. Откройте https://dayz-map.gto-team.uz")
    print("2. Войдите с PIN группы и никнеймом")
    print("3. Скопируйте ключ клиента\n")

    key = input("Вставьте ключ клиента: ").strip()
    if key:
        cfg["client_key"] = key
        save_config(cfg)
    else:
        print("[Ошибка] Ключ обязателен. Перезапустите клиент.")
        sys.exit(1)
    return cfg


def get_clipboard_image():
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


class ClipboardWatcher(threading.Thread):
    """Detects new screenshot in clipboard (Win+Shift+S) and sends marker."""

    def __init__(self, map_client: MapClient, ocr_region: tuple[int, int, int, int]):
        super().__init__(daemon=True)
        self.map_client = map_client
        self.ocr_region = ocr_region
        self._last_hash: str | None = None

    def _image_hash(self, img) -> str:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return str(hash(buf.getvalue()))

    def run(self):
        print("[Clipboard] Следим за скриншотами Win+Shift+S...")
        time.sleep(2)
        img = get_clipboard_image()
        if img is not None:
            self._last_hash = self._image_hash(img)
        while True:
            img = get_clipboard_image()
            if img is not None:
                h = self._image_hash(img)
                if h != self._last_hash:
                    self._last_hash = h
                    coords = extract_coordinates(img)
                    if coords:
                        x, y = coords
                        print(f"[Метка OCR] {x:.0f} / {y:.0f}")
                        self.map_client.send_marker(x, y)
                    else:
                        print("[Clipboard] Скриншот без координат — пропуск")
            time.sleep(0.5)


def on_m_pressed(map_client: MapClient, region: tuple[int, int, int, int]):
    print("[M] OCR позиции...")
    coords = ocr_from_screen(region)
    if coords:
        x, y = coords
        print(f"[Live] {x:.0f} / {y:.0f}")
        if map_client.send_position(x, y):
            print("[Live] Отправлено на сервер")
    else:
        print("[Ошибка] Координаты не распознаны. Откройте GPS в игре.")


def main():
    cfg = prompt_setup(load_config())
    setup_tesseract(cfg.get("tesseract_cmd", ""))

    if not cfg.get("client_key"):
        print("[Ошибка] Нет ключа. Настройте config.json")
        sys.exit(1)

    region = tuple(cfg.get("ocr_region", [10, 900, 300, 1050]))
    client = MapClient(cfg["server_url"], cfg["client_key"])

    watcher = ClipboardWatcher(client, region)
    watcher.start()

    print(f"[Запуск] Сервер: {cfg['server_url']}")
    print("[Hotkey] M — live-позиция (когда GPS на экране)")
    print("[Hotkey] Win+Shift+S — метка со скриншота")
    print("Ctrl+C — выход\n")

    keyboard.add_hotkey("m", lambda: on_m_pressed(client, region))
    keyboard.wait()


if __name__ == "__main__":
    main()
