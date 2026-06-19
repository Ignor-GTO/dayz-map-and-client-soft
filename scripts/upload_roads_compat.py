#!/usr/bin/env python3
"""
upload_roads_compat.py — Загрузка road_segments.json на сервер через одиночный POST API.
Используется как обходной путь, если /roads/bulk не задеплоен.

Использование:
    python scripts/upload_roads_compat.py --server https://dayz-map.gto-team.uz --map-slug pripyat
"""

import argparse
import json
import time
from pathlib import Path

import requests


def upload_roads(server_url: str, map_slug: str, segments_file: str, password: str, clear_first: bool = False):
    session = requests.Session()

    # Авторизация
    print("Вход в Admin...")
    login_r = session.post(f"{server_url}/api/admin/login", json={"password": password})
    if not login_r.ok:
        print(f"Ошибка входа: {login_r.status_code} {login_r.text}")
        return

    print("Авторизация успешна.")

    # Загрузка JSON
    segments = json.loads(Path(segments_file).read_text(encoding="utf-8"))
    print(f"Загружено {len(segments)} сегментов из {segments_file}")

    # Очистка (опционально)
    if clear_first:
        print("Очистка существующих дорог...")
        del_r = session.delete(f"{server_url}/api/admin/maps/{map_slug}/roads")
        if del_r.ok:
            print(f"  Удалено: {del_r.json().get('deleted', 0)}")
        else:
            print(f"  Ошибка очистки: {del_r.status_code} {del_r.text}")

    # Сначала попробуем bulk
    print("Попытка bulk-загрузки...")
    bulk_r = session.post(
        f"{server_url}/api/admin/maps/{map_slug}/roads/bulk",
        json=segments,
        timeout=120,
    )
    if bulk_r.ok:
        print(f"Bulk загрузка успешна! Загружено сегментов: {len(bulk_r.json())}")
        return
    else:
        print(f"Bulk недоступен ({bulk_r.status_code}), переключаюсь на одиночную загрузку...")

    # Одиночная загрузка батчами
    total = len(segments)
    ok_count = 0
    err_count = 0
    batch_size = 50

    for i, seg in enumerate(segments):
        r = session.post(
            f"{server_url}/api/admin/maps/{map_slug}/roads",
            json={"road_type": seg["road_type"], "points": seg["points"]},
            timeout=10,
        )
        if r.ok:
            ok_count += 1
        else:
            err_count += 1
            if err_count <= 5:
                print(f"  Ошибка сегмента {i}: {r.status_code} {r.text[:100]}")

        # Прогресс
        if (i + 1) % batch_size == 0 or i == total - 1:
            print(f"  Прогресс: {i+1}/{total} | OK: {ok_count} | ERR: {err_count}", end="\r")
            time.sleep(0.05)  # небольшая пауза чтобы не флудить сервер

    print(f"\nГотово! Загружено: {ok_count}, ошибок: {err_count}")


def main():
    parser = argparse.ArgumentParser(description="Загрузка дорог на сервер (compat режим)")
    parser.add_argument("--server", default="https://dayz-map.gto-team.uz")
    parser.add_argument("--map-slug", default="pripyat")
    parser.add_argument("--file", default="road_segments.json")
    parser.add_argument("--clear", action="store_true", help="Очистить дороги перед загрузкой")
    args = parser.parse_args()

    password = input("Пароль администратора: ").strip()
    upload_roads(args.server, args.map_slug, args.file, password, clear_first=args.clear)


if __name__ == "__main__":
    main()
