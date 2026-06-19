#!/usr/bin/env python3
"""
extract_roads_atlas.py — Правильное извлечение дорог: сшиваем все тайлы
в ОДНО большое изображение и обрабатываем целиком.

Это исключает разрывы на границах тайлов — главную причину фрагментации.

Использование:
    python scripts/extract_roads_atlas.py --zoom 4 --out road_segments_atlas.json
    python scripts/extract_roads_atlas.py --zoom 4 --out road_segments_atlas.json --load
"""

import argparse
import json
import math
import time
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
import requests
import skimage.morphology

# ──────────────────────────────────────────────────────────────────
TILE_URL = "https://static.xam.nu/dayz/maps/pripyat/19.08/topographic/{z}/{x}/{y}.jpg"
MAP_SIZE  = 20480
TILE_SIZE = 256

# HSV диапазоны для жёлтых дорог
ROAD_HSV_RANGES = [
    (np.array([14, 60, 140]), np.array([30, 255, 255])),   # жёлтые/золотые дороги
]

# Минимальный размер компонента в пикселях (убираем шум)
MIN_COMPONENT_PX = 100

# Epsilon для RDP упрощения (в пикселях атласа)
SIMPLIFY_EPS = 2.0

# Минимальная длина итогового сегмента в пикселях атласа
MIN_SEG_LEN_PX = 8


def download_tile(z, x, y, cache_dir: Path) -> np.ndarray | None:
    fpath = cache_dir / f"{z}_{x}_{y}.jpg"
    if fpath.exists():
        data = fpath.read_bytes()
    else:
        url = TILE_URL.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
        for attempt in range(3):
            try:
                r = requests.get(url, timeout=15)
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
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def build_atlas(zoom: int, cache_dir: Path) -> np.ndarray:
    """Скачать все тайлы и сшить в единое изображение."""
    n = 2 ** zoom
    atlas_px = n * TILE_SIZE
    print(f"Атлас: {n}×{n} тайлов = {atlas_px}×{atlas_px} пикселей")
    atlas = np.zeros((atlas_px, atlas_px, 3), dtype=np.uint8)

    total = n * n
    done = 0
    for ty in range(n):
        for tx in range(n):
            img = download_tile(zoom, tx, ty, cache_dir)
            done += 1
            if done % 20 == 0 or done == total:
                print(f"  Тайлов загружено: {done}/{total}", end="\r")
            if img is None:
                continue
            y0 = ty * TILE_SIZE
            x0 = tx * TILE_SIZE
            atlas[y0:y0+TILE_SIZE, x0:x0+TILE_SIZE] = img

    print(f"\nАтлас собран.")
    return atlas


def detect_roads(atlas: np.ndarray) -> np.ndarray:
    """Цветовая маска жёлтых дорог на атласе."""
    hsv = cv2.cvtColor(atlas, cv2.COLOR_BGR2HSV)
    mask = np.zeros(atlas.shape[:2], dtype=np.uint8)
    for lo, hi in ROAD_HSV_RANGES:
        mask = cv2.bitwise_or(mask, cv2.inRange(hsv, lo, hi))

    # Исключаем воду (синеватые пиксели)
    water_mask = cv2.inRange(hsv,
                             np.array([95, 60, 180]),
                             np.array([115, 130, 255]))
    mask = cv2.subtract(mask, cv2.dilate(water_mask,
                        cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))))

    # Морфология: закрываем небольшие разрывы и убираем шум
    k5 = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    k3 = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    # Закрываем небольшие пробелы (например, от текста или значков на дорогах)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k5, iterations=1)
    # Убираем одиночный мелкий шум
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  k3, iterations=1)

    # Удаляем маленькие компоненты (шум)
    n_comp, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    clean = np.zeros_like(mask)
    for i in range(1, n_comp):
        if stats[i, cv2.CC_STAT_AREA] >= MIN_COMPONENT_PX:
            clean[labels == i] = 255

    print(f"Маска: {cv2.countNonZero(clean)} пикселей дорог ({n_comp-1} компонентов до фильтрации)")
    return clean


def skeletonize(mask: np.ndarray) -> np.ndarray:
    """Zhang-Suen thinning через skimage.morphology.skeletonize (гарантирует 1px ширину)."""
    print("Скелетонизация...", end=" ", flush=True)
    bool_mask = mask > 0
    skel_bool = skimage.morphology.skeletonize(bool_mask)
    skel = (skel_bool * 255).astype(np.uint8)
    print(f"{cv2.countNonZero(skel)} пикселей скелета")
    return skel


def _build_pixel_graph(pts_set: set[tuple[int, int]]) -> dict[tuple[int, int], list[tuple[int, int]]]:
    adj = {}
    for r, c in pts_set:
        nbs = []
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                nb = (r + dr, c + dc)
                if nb in pts_set:
                    nbs.append(nb)
        adj[(r, c)] = nbs
    return adj


def prune_spurs(skel: np.ndarray, max_spur_len: int = 15) -> np.ndarray:
    """
    Удаляет тупиковые ветви (шпоры) скелета, длина которых меньше max_spur_len пикселей.
    """
    print(f"Прунинг шпор (max_len={max_spur_len})...")
    ys, xs = np.where(skel > 0)
    pts_set = set(zip(ys.tolist(), xs.tolist()))
    
    changed = True
    iteration = 0
    while changed and iteration < 5:
        changed = False
        iteration += 1
        adj = _build_pixel_graph(pts_set)
        
        endpoints = [p for p, nbs in adj.items() if len(nbs) == 1]
        to_remove = set()
        
        for ep in endpoints:
            path = [ep]
            curr = ep
            prev = None
            is_spur = False
            
            while True:
                nbs = adj[curr]
                if len(nbs) >= 3:
                    is_spur = True
                    break
                if len(nbs) <= 1 and curr != ep:
                    is_spur = True
                    break
                
                next_nodes = [n for n in nbs if n != prev]
                if not next_nodes:
                    break
                nxt = next_nodes[0]
                path.append(nxt)
                prev = curr
                curr = nxt
                
                if len(path) > max_spur_len:
                    break
            
            if is_spur and len(path) <= max_spur_len:
                remove_pts = path[:-1] if len(adj[path[-1]]) >= 3 else path
                for p in remove_pts:
                    to_remove.add(p)
        
        if to_remove:
            pts_set -= to_remove
            changed = True
            print(f"  Итерация {iteration}: удалено {len(to_remove)} пикселей шпор")
            
    new_skel = np.zeros_like(skel)
    for r, c in pts_set:
        new_skel[r, c] = 255
    return new_skel


def trace_to_polylines(skel: np.ndarray) -> list[list[tuple[int,int]]]:
    """
    Правильная трассировка скелета в полилинии.

    Алгоритм:
    1. Строим граф смежности.
    2. Классифицируем узлы: endpoint (степень 1), chain (степень 2), junction (степень ≥ 3).
    3. Для каждой пары ключевых узлов (junction/endpoint) прослеживаем
       полный путь через chain-узлы → один сегмент на каждый участок дороги.
    """
    print("Трассировка полилиний...")
    ys, xs = np.where(skel > 0)
    if len(ys) == 0:
        return []

    pts_set: set[tuple] = set(zip(ys.tolist(), xs.tolist()))

    # Строим граф
    adj = _build_pixel_graph(pts_set)

    def is_key(p: tuple) -> bool:
        """Endpoint (1) или junction (≥ 3)."""
        return len(adj[p]) != 2

    # Трассируем ребра: от каждого ключевого узла по каждому его соседу
    visited_edges: set[frozenset] = set()
    polylines: list[list[tuple]] = []

    key_nodes = [p for p in pts_set if is_key(p)]
    if not key_nodes:
        # Только циклы (все степень 2) — обходим как один маршрут
        key_nodes = [next(iter(pts_set))]

    for start in key_nodes:
        for first_step in adj[start]:
            edge_id = frozenset((start, first_step))
            if edge_id in visited_edges:
                continue
            visited_edges.add(edge_id)

            path = [start, first_step]
            prev, curr = start, first_step

            # Идём пока не дойдём до ключевого узла
            while not is_key(curr):
                nbs = [n for n in adj[curr] if n != prev]
                if not nbs:
                    break
                nxt = nbs[0]
                visited_edges.add(frozenset((curr, nxt)))
                path.append(nxt)
                prev, curr = curr, nxt

            polylines.append(path)

    print(f"Сырых полилиний: {len(polylines)}")
    return polylines



def simplify(pts_rc: list[tuple], eps: float) -> list[tuple]:
    if len(pts_rc) < 3:
        return pts_rc
    pts = np.array([[c, r] for r, c in pts_rc], dtype=np.float32).reshape(-1, 1, 2)
    simp = cv2.approxPolyDP(pts, eps, closed=False)
    return [(int(p[0][1]), int(p[0][0])) for p in simp]


def pixel_to_game(px: int, py: int, atlas_size: int) -> tuple[float, float]:
    """
    Leaflet CRS.Simple: gameToLatLng → lat = y/ratio - 256
    y=0 → lat=-256 (низ), y=MAP_SIZE → lat=0 (верх).
    Тайлы: py=0 = верх → нужна инверсия Y.
    """
    gx = px / atlas_size * MAP_SIZE
    gy = MAP_SIZE - (py / atlas_size * MAP_SIZE)
    return round(gx, 1), round(gy, 1)


def seg_len_px(pts_rc: list[tuple]) -> float:
    total = 0.0
    for i in range(len(pts_rc) - 1):
        dr = pts_rc[i+1][0] - pts_rc[i][0]
        dc = pts_rc[i+1][1] - pts_rc[i][1]
        total += math.sqrt(dr*dr + dc*dc)
    return total


def dist(a: tuple[float, float] | list[float], b: tuple[float, float] | list[float]) -> float:
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2)


def segment_length(pts: list[list[float]]) -> float:
    total = 0.0
    for i in range(len(pts)-1):
        total += dist(pts[i], pts[i+1])
    return total


def stitch_segments(segments: list[dict], stitch_dist: float = 20.0, min_len: float = 5.0) -> list[dict]:
    """Сшить короткие сегменты в длинные полилинии."""
    print(f"Входных сегментов для сшивки: {len(segments)}")

    # Фильтруем слишком короткие
    segs = [s for s in segments if len(s["points"]) >= 2 and segment_length(s["points"]) >= min_len]
    print(f"После фильтрации по длине перед сшивкой: {len(segs)}")

    if not segs:
        return []

    # Для каждого сегмента запоминаем его концы
    endpoints = []
    for i, seg in enumerate(segs):
        endpoints.append((i, 0, tuple(seg["points"][0])))       # начало
        endpoints.append((i, -1, tuple(seg["points"][-1])))     # конец

    # Строим индекс концов для быстрого поиска соседей
    cell_size = stitch_dist
    grid = {}
    for ep_idx, (seg_i, end, pt) in enumerate(endpoints):
        cx = int(pt[0] / cell_size)
        cy = int(pt[1] / cell_size)
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                key = (cx+dx, cy+dy)
                grid.setdefault(key, []).append(ep_idx)

    # Для каждого конца найдём близкие концы других сегментов
    adj = {}  # ep_idx → [ep_idx близкого конца]
    for ep_idx, (seg_i, end, pt) in enumerate(endpoints):
        cx = int(pt[0] / cell_size)
        cy = int(pt[1] / cell_size)
        candidates = grid.get((cx, cy), [])
        for other_idx in candidates:
            if other_idx == ep_idx:
                continue
            other_seg_i, other_end, other_pt = endpoints[other_idx]
            if other_seg_i == seg_i:
                continue  # тот же сегмент
            if dist(pt, other_pt) <= stitch_dist:
                adj.setdefault(ep_idx, []).append(other_idx)

    # Обходим граф и строим цепочки
    used_segs = set()
    result = []

    def get_chain(start_ep_idx):
        seg_i, end, pt = endpoints[start_ep_idx]
        if seg_i in used_segs:
            return None
        used_segs.add(seg_i)

        pts = list(segs[seg_i]["points"])
        if end == -1:
            pts = pts[::-1]  # разворачиваем, чтобы pt было в начале

        road_type = segs[seg_i]["road_type"]

        opp_ep_idx = seg_i * 2 + (1 if end == 0 else 0)

        while True:
            neighbors = [n for n in adj.get(opp_ep_idx, []) if endpoints[n][0] not in used_segs]
            if not neighbors:
                break
            opp_pt = endpoints[opp_ep_idx][2]
            best = min(neighbors, key=lambda n: dist(endpoints[n][2], opp_pt))
            next_seg_i, next_end, next_pt = endpoints[best]
            used_segs.add(next_seg_i)

            next_pts = list(segs[next_seg_i]["points"])
            if next_end == -1:
                next_pts = next_pts[::-1]

            pts.extend(next_pts[1:])
            opp_ep_idx = next_seg_i * 2 + (1 if next_end == 0 else 0)

        return {"road_type": road_type, "points": pts}

    for ep_idx in range(0, len(endpoints), 2):  # только начала
        seg_i = endpoints[ep_idx][0]
        if seg_i in used_segs:
            continue
        chain = get_chain(ep_idx)
        if chain and len(chain["points"]) >= 2:
            result.append(chain)

    print(f"После сшивки: {len(result)} сегментов")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zoom",      type=int, default=5)
    parser.add_argument("--out",       default="road_segments_atlas.json")
    parser.add_argument("--cache-dir", default="tile_cache")
    parser.add_argument("--load",      action="store_true")
    parser.add_argument("--clear",     action="store_true")
    parser.add_argument("--server",    default="https://dayz-map.gto-team.uz")
    parser.add_argument("--map-slug",  default="pripyat")
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(exist_ok=True)
    atlas_size = (2 ** args.zoom) * TILE_SIZE

    # 1. Собираем атлас
    atlas = build_atlas(args.zoom, cache_dir)

    # 2. Маска дорог
    mask = detect_roads(atlas)

    # 3. Скелетонизация
    skel = skeletonize(mask)
    skel = prune_spurs(skel, max_spur_len=3)

    # 4. Трассировка
    polylines_rc = trace_to_polylines(skel)

    # 5. Упрощение + фильтрация + конвертация
    segments = []
    skipped = 0
    for poly_rc in polylines_rc:
        simp = simplify(poly_rc, SIMPLIFY_EPS)
        if len(simp) < 2:
            skipped += 1
            continue
        if seg_len_px(simp) < MIN_SEG_LEN_PX:
            skipped += 1
            continue
        game_pts = [list(pixel_to_game(c, r, atlas_size)) for r, c in simp]
        segments.append({"road_type": "highway", "points": game_pts})

    # Сшиваем сегменты
    segments = stitch_segments(segments, stitch_dist=30.0, min_len=5.0)
    print(f"Итого сегментов: {len(segments)} (пропущено коротких: {skipped})")

    # 6. Сохраняем
    out_path = Path(args.out)
    out_path.write_text(json.dumps(segments, ensure_ascii=False, separators=(",",":")), encoding="utf-8")
    print(f"Сохранено: {out_path} ({out_path.stat().st_size//1024} KB)")

    if not args.load:
        print(f"\nДля загрузки выполните:")
        print(f"  python scripts/extract_roads_atlas.py --zoom {args.zoom} --out {args.out} --load --clear")
        return

    # 7. Загружаем на сервер
    password = input("Пароль администратора: ").strip()
    server   = args.server
    slug     = args.map_slug
    session  = requests.Session()

    r = session.post(f"{server}/api/admin/login", json={"password": password})
    if not r.ok:
        print(f"Ошибка входа: {r.status_code}")
        return
    print("Авторизован.")

    if args.clear:
        print("Очищаю старые сегменты на сервере...")
        r = session.delete(f"{server}/api/admin/maps/{slug}/roads")
        if r.ok:
            print(f"  Успешно удалено дорожных сегментов: {r.json().get('deleted', 0)}")
        else:
            print(f"  Ошибка при очистке дорог: {r.status_code} {r.text}")

    print(f"Загружаю {len(segments)} сегментов в базу (bulk)...")
    r = session.post(f"{server}/api/admin/maps/{slug}/roads/bulk", json=segments, timeout=30)
    if r.ok:
        print(f"Готово! Успешно загружено сегментов: {len(r.json())}")
    else:
        print(f"Ошибка bulk загрузки: {r.status_code} {r.text}")


if __name__ == "__main__":
    main()
