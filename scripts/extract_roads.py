#!/usr/bin/env python3
"""
extract_roads.py — Автоматическое извлечение дорог с тайлов топографической карты.

Принцип:
1. Скачать все тайлы топо-карты на выбранном zoom-уровне
2. Найти пиксели жёлтого (трасса) и белого/светло-серого (посёлковая) цветов
3. Скелетонизировать маску → трассировать линии в полилинии
4. Перевести пиксели → игровые координаты (0..MAP_SIZE)
5. Сохранить как road_segments.json для загрузки в БД

Использование:
    python extract_roads.py [--zoom 5] [--out road_segments.json]

После этого загрузить в БД:
    python extract_roads.py --load

Требования: opencv-python, scikit-image, requests, numpy
"""

import argparse
import json
import math
import os
import time
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
import requests

# ──────────────────────────────────────────────────────────────────────────────
# Конфигурация
# ──────────────────────────────────────────────────────────────────────────────

TILE_URL = "https://static.xam.nu/dayz/maps/pripyat/19.08/topographic/{z}/{x}/{y}.jpg"
MAP_SIZE = 20480         # игровые единицы
TILE_SIZE = 256          # пикселей на тайл

# Цветовые диапазоны в HSV для определения типа дороги
# HSV: H[0-179], S[0-255], V[0-255]
COLOR_RANGES = {
    "highway": [
        # Жёлтые/золотые дороги
        (np.array([17, 80, 150]), np.array([26, 255, 255])),
    ],
    "road": [
        # Узкий диапазон для серых дорог (чтобы отфильтровать фон)
        (np.array([0, 0, 150]), np.array([180, 18, 192])),
    ],
    "street": [
        # Голубые дороги в городах
        (np.array([90, 80, 150]), np.array([125, 255, 255])),
    ],
}

# Минимальный размер компонента (пикселей) — убирает шум
MIN_COMPONENT_PIXELS = 80

# Параметры децимации полилинии (Ramer–Douglas–Peucker epsilon в пикселях)
SIMPLIFY_EPSILON = 2.5

# Расстояние для сшивки концов отрезков (пикселей)
STITCH_DIST = 8

# Максимальное расстояние от игровой точки до дороги для snap (единицы карты)
SNAP_DISTANCE = 300


def download_tile(url: str, z: int, x: int, y: int, cache_dir: Path) -> np.ndarray | None:
    """Скачать тайл, использовать кэш на диске."""
    fpath = cache_dir / f"{z}_{x}_{y}.jpg"
    if fpath.exists():
        data = fpath.read_bytes()
    else:
        tile_url = url.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
        for attempt in range(3):
            try:
                r = requests.get(tile_url, timeout=10)
                if r.status_code == 200:
                    data = r.content
                    fpath.write_bytes(data)
                    break
                elif r.status_code == 404:
                    return None
            except requests.RequestException:
                if attempt == 2:
                    return None
                time.sleep(1)
        else:
            return None

    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return img


def make_water_mask(img: np.ndarray) -> np.ndarray:
    """Создать маску воды для фильтрации ложных береговых линий."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # Вода: H ~ 95-115, S ~ 70-120, V ~ 200-255
    water_mask = cv2.inRange(hsv, np.array([95, 70, 200]), np.array([115, 120, 255]))
    kernel_water = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    return cv2.dilate(water_mask, kernel_water)


def make_mask(bgr: np.ndarray, road_type: str) -> np.ndarray:
    """Создать бинарную маску для заданного типа дороги."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    combined = np.zeros(bgr.shape[:2], dtype=np.uint8)
    for lo, hi in COLOR_RANGES.get(road_type, []):
        m = cv2.inRange(hsv, lo, hi)
        combined = cv2.bitwise_or(combined, m)
    return combined


def skeletonize_mask(mask: np.ndarray) -> np.ndarray:
    """Скелетонизация бинарной маски (Zhang-Suen)."""
    # Используем OpenCV morphological thinning
    skel = np.zeros_like(mask)
    kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    temp = mask.copy()
    while True:
        eroded = cv2.erode(temp, kernel)
        opened = cv2.dilate(eroded, kernel)
        diff = cv2.subtract(temp, opened)
        skel = cv2.bitwise_or(skel, diff)
        temp = eroded.copy()
        if cv2.countNonZero(temp) == 0:
            break
    return skel


def trace_skeleton_to_polylines(skeleton: np.ndarray) -> list[list[tuple[int, int]]]:
    """
    Трассировать скелет в список полилиний.
    Возвращает список [[x,y], [x,y], ...].
    """
    # Находим все ненулевые пиксели
    pts_yx = np.column_stack(np.where(skeleton > 0))
    if len(pts_yx) == 0:
        return []

    # Строим граф смежности
    pts_set = {(int(r), int(c)) for r, c in pts_yx}
    adj: dict[tuple, list[tuple]] = {p: [] for p in pts_set}
    for r, c in pts_set:
        for dr in [-1, 0, 1]:
            for dc in [-1, 0, 1]:
                if dr == 0 and dc == 0:
                    continue
                nb = (r + dr, c + dc)
                if nb in pts_set:
                    adj[(r, c)].append(nb)

    # Ищем линии: обходим граф DFS от вершин с degree 1 или 0
    visited = set()
    polylines = []

    def walk(start, prev=None):
        """Пройти по цепочке пикселей."""
        path = [start]
        visited.add(start)
        curr = start
        while True:
            neighbors = [n for n in adj[curr] if n not in visited]
            if len(neighbors) == 0:
                break
            if len(neighbors) == 1:
                nxt = neighbors[0]
                visited.add(nxt)
                path.append(nxt)
                curr = nxt
            else:
                # Разветвление — останавливаемся
                break
        return path

    # Начинаем от точек с degree 1 (концы линий)
    endpoints = [p for p, nb in adj.items() if len(nb) <= 1]
    if not endpoints:
        endpoints = list(pts_set)

    for start in endpoints:
        if start in visited:
            continue
        path = walk(start)
        if len(path) >= 3:
            polylines.append(path)

    # Подобрать оставшиеся (циклы)
    for pt in pts_set:
        if pt in visited:
            continue
        path = walk(pt)
        if len(path) >= 3:
            polylines.append(path)

    return polylines


def simplify_polyline(pts_rc: list[tuple], epsilon: float) -> list[tuple]:
    """Упростить полилинию алгоритмом Ramer-Douglas-Peucker."""
    if len(pts_rc) < 3:
        return pts_rc
    pts = np.array([[c, r] for r, c in pts_rc], dtype=np.float32)
    pts_cv = pts.reshape((-1, 1, 2))
    simplified = cv2.approxPolyDP(pts_cv, epsilon, closed=False)
    return [(int(p[0][1]), int(p[0][0])) for p in simplified]


def pixel_to_game(px: int, py: int, zoom: int) -> tuple[float, float]:
    """
    Перевести пиксель тайлового атласа → игровые координаты.

    Для Leaflet CRS.Simple (tile_bounds = [0,0] to [-256, 256]):
    - Весь атлас = 2^zoom × 256 пикселей
    - Игровые коорд.: x = px / atlas_size * MAP_SIZE
                       y = py / atlas_size * MAP_SIZE (y растёт вниз)
    """
    atlas_size = (2 ** zoom) * TILE_SIZE
    gx = px / atlas_size * MAP_SIZE
    gy = py / atlas_size * MAP_SIZE
    return gx, gy


def extract_roads_from_tiles(
    zoom: int,
    tile_url: str,
    cache_dir: Path,
    road_types: list[str],
    progress: bool = True,
) -> list[dict]:
    """
    Основная функция: скачать тайлы, обработать, вернуть список сегментов.
    """
    n_tiles = 2 ** zoom
    results = []

    for road_type in road_types:
        if road_type not in COLOR_RANGES:
            continue
        print(f"\n=== Обработка типа: {road_type} ===")

        for ty in range(n_tiles):
            for tx in range(n_tiles):
                if progress:
                    print(f"  Тайл ({tx},{ty})/{n_tiles-1}", end="\r")

                img = download_tile(tile_url, zoom, tx, ty, cache_dir)
                if img is None:
                    continue

                # 1. Маска цвета
                mask = make_mask(img, road_type)

                # Фильтруем береговую линию (воду) для обычных и городских улиц
                if road_type != "highway":
                    w_mask = make_water_mask(img)
                    mask = cv2.subtract(mask, w_mask)

                if cv2.countNonZero(mask) < MIN_COMPONENT_PIXELS:
                    continue

                # 2. Морфология: убираем шум, утолщаем
                kernel3 = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
                mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel3, iterations=2)
                mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel3, iterations=1)

                # 3. Удалить маленькие компоненты
                n_comp, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
                clean = np.zeros_like(mask)
                for i in range(1, n_comp):
                    if stats[i, cv2.CC_STAT_AREA] >= MIN_COMPONENT_PIXELS:
                        clean[labels == i] = 255

                if cv2.countNonZero(clean) == 0:
                    continue

                # 4. Скелетонизация
                skel = skeletonize_mask(clean)

                # 5. Трассировка в полилинии
                polylines_rc = trace_skeleton_to_polylines(skel)

                # 6. Упростить и перевести в игровые координаты
                tile_origin_px = (tx * TILE_SIZE, ty * TILE_SIZE)

                for poly_rc in polylines_rc:
                    simplified = simplify_polyline(poly_rc, SIMPLIFY_EPSILON)
                    if len(simplified) < 2:
                        continue

                    game_points = []
                    for r, c in simplified:
                        px = tile_origin_px[0] + c
                        py = tile_origin_px[1] + r
                        gx, gy = pixel_to_game(px, py, zoom)
                        game_points.append([round(gx, 1), round(gy, 1)])

                    if len(game_points) >= 2:
                        results.append({
                            "road_type": road_type,
                            "points": game_points,
                        })

        print(f"\n  Найдено {sum(1 for r in results if r['road_type'] == road_type)} сегментов для {road_type}")

    print(f"\nВсего сегментов: {len(results)}")
    return results


def load_into_db(segments: list[dict], map_slug: str, server_url: str = "http://localhost:8000", clear_first: bool = False):
    """Загрузить сегменты через Admin API."""
    # Сначала нужно войти в Admin
    print("Загрузка в базу данных через API...")
    admin_password = input("Введите пароль администратора: ").strip()

    session = requests.Session()
    login_r = session.post(f"{server_url}/api/admin/login", json={"password": admin_password})
    if not login_r.ok:
        print(f"Ошибка входа: {login_r.status_code} {login_r.text}")
        return

    if clear_first:
        print("Очистка существующих дорог на карте...")
        clear_r = session.delete(f"{server_url}/api/admin/maps/{map_slug}/roads")
        if clear_r.ok:
            print(f"  Успешно удалено дорожных сегментов: {clear_r.json().get('deleted', 0)}")
        else:
            print(f"  Ошибка при очистке дорог: {clear_r.status_code} {clear_r.text}")

    print(f"Загружаю {len(segments)} сегментов в базу (bulk)...")
    r = session.post(
        f"{server_url}/api/admin/maps/{map_slug}/roads/bulk",
        json=segments,
    )
    if r.ok:
        print(f"Успешно загружено сегментов: {len(r.json())}")
    else:
        print(f"Ошибка bulk загрузки: {r.status_code} {r.text}")


def main():
    parser = argparse.ArgumentParser(description="Извлечение дорог с тайлов карты")
    parser.add_argument("--zoom", type=int, default=5, help="Zoom уровень (4-6, по умолч. 5)")
    parser.add_argument("--out", default="road_segments.json", help="Выходной JSON файл")
    parser.add_argument("--load", action="store_true", help="Загрузить в БД после извлечения")
    parser.add_argument("--clear", action="store_true", help="Очистить существующие дороги на этой карте перед импортом")
    parser.add_argument("--types", default="highway", help="Типы дорог через запятую: highway, road, street (по умолчанию: highway)")
    parser.add_argument("--map-slug", default="pripyat", help="Slug карты для загрузки")
    parser.add_argument("--server", default="http://localhost:8000", help="URL сервера")
    parser.add_argument("--cache-dir", default="tile_cache", help="Папка кэша тайлов")
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(exist_ok=True)

    road_types = [t.strip() for t in args.types.split(",") if t.strip()]
    if not road_types:
        print("Ошибка: не указаны типы дорог для извлечения")
        return

    print(f"Извлечение дорог: zoom={args.zoom}, тайлов={2**args.zoom}x{2**args.zoom}")
    print(f"Типы дорог: {', '.join(road_types)}")
    print(f"URL тайлов: {TILE_URL}")
    print(f"Кэш: {cache_dir.resolve()}")
    print()

    segments = extract_roads_from_tiles(args.zoom, TILE_URL, cache_dir, road_types)

    out_path = Path(args.out)
    out_path.write_text(json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nСохранено в {out_path} ({out_path.stat().st_size // 1024} KB)")

    if args.load:
        load_into_db(segments, args.map_slug, args.server, clear_first=args.clear)
    else:
        print(f"\nДля загрузки в БД выполните:")
        print(f"  python extract_roads.py --load --map-slug {args.map_slug} --clear")


if __name__ == "__main__":
    main()
