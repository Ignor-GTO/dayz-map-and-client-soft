#!/usr/bin/env python3
"""
stitch_roads.py — Сшивает короткие сегменты дорог в длинные полилинии.

Алгоритм:
1. Строит граф: концы сегментов → соседние концы (в радиусе STITCH_DIST игровых единиц)
2. Обходит граф, соединяя цепочки сегментов в длинные полилинии
3. Результат сохраняет в road_segments_stitched.json и загружает на сервер

Использование:
    python scripts/stitch_roads.py
"""

import json
import math
import sys
from pathlib import Path

import requests

# Максимальное расстояние для сшивки концов (в игровых единицах)
# zoom=5, atlas=8192px, MAP_SIZE=20480 → 1 пиксель = 2.5 игровых единицы
# 6 пикселей = 15 единиц — чуть больше расстояния между соседними точками на тайле
STITCH_DIST = 20.0

# Минимальная длина сегмента для включения (в игровых единицах)
MIN_SEGMENT_LEN = 5.0


def dist(a, b):
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2)


def segment_length(pts):
    total = 0.0
    for i in range(len(pts)-1):
        total += dist(pts[i], pts[i+1])
    return total


def stitch_segments(segments):
    """Сшить короткие сегменты в длинные полилинии."""
    print(f"Входных сегментов: {len(segments)}")

    # Фильтруем слишком короткие
    segs = [s for s in segments if len(s["points"]) >= 2 and segment_length(s["points"]) >= MIN_SEGMENT_LEN]
    print(f"После фильтрации по длине: {len(segs)}")

    # Для каждого сегмента запоминаем его концы
    # Endpoint index: (seg_idx, end_idx) где end_idx = 0 или -1
    endpoints = []
    for i, seg in enumerate(segs):
        endpoints.append((i, 0, tuple(seg["points"][0])))       # начало
        endpoints.append((i, -1, tuple(seg["points"][-1])))     # конец

    # Строим индекс концов для быстрого поиска соседей
    # Простая сетка (bucket) для поиска ближайших
    cell_size = STITCH_DIST
    grid = {}
    for ep_idx, (seg_i, end, pt) in enumerate(endpoints):
        cx = int(pt[0] / cell_size)
        cy = int(pt[1] / cell_size)
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                key = (cx+dx, cy+dy)
                grid.setdefault(key, []).append(ep_idx)

    # Для каждого конца найдём ближайший конец другого сегмента
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
            if dist(pt, other_pt) <= STITCH_DIST:
                adj.setdefault(ep_idx, []).append(other_idx)

    # Обходим граф и строим цепочки
    used_segs = set()
    result = []

    def get_chain(start_ep_idx):
        """Строим цепочку от данного конца."""
        seg_i, end, pt = endpoints[start_ep_idx]
        if seg_i in used_segs:
            return None
        used_segs.add(seg_i)

        pts = list(segs[seg_i]["points"])
        if end == -1:
            pts = pts[::-1]  # разворачиваем, чтобы pt было в начале

        road_type = segs[seg_i]["road_type"]

        # Ищем продолжение от конца цепочки
        current_end_ep_idx = start_ep_idx ^ 1  # противоположный конец того же сегмента
        # (start_ep_idx чётный → конец нечётный и наоборот)
        # Реальный индекс: если start_ep_idx = seg_i*2+0, то противоположный = seg_i*2+1
        opp_ep_idx = seg_i * 2 + (1 if end == 0 else 0)

        while True:
            neighbors = [n for n in adj.get(opp_ep_idx, []) if endpoints[n][0] not in used_segs]
            if not neighbors:
                break
            # Выбираем ближайшего
            opp_pt = endpoints[opp_ep_idx][2]
            best = min(neighbors, key=lambda n: dist(endpoints[n][2], opp_pt))
            next_seg_i, next_end, next_pt = endpoints[best]
            used_segs.add(next_seg_i)

            next_pts = list(segs[next_seg_i]["points"])
            if next_end == -1:
                next_pts = next_pts[::-1]

            # Добавляем точки (пропуская первую, т.к. она близка к последней)
            pts.extend(next_pts[1:])
            opp_ep_idx = next_seg_i * 2 + (1 if next_end == 0 else 0)

        return {"road_type": road_type, "points": pts}

    for ep_idx in range(0, len(endpoints), 2):  # только начала сегментов
        seg_i = endpoints[ep_idx][0]
        if seg_i in used_segs:
            continue
        chain = get_chain(ep_idx)
        if chain and len(chain["points"]) >= 2:
            result.append(chain)

    print(f"После сшивки: {len(result)} сегментов")
    by_type = {}
    for s in result:
        by_type[s["road_type"]] = by_type.get(s["road_type"], 0) + 1
    for t, c in by_type.items():
        print(f"  {t}: {c}")

    return result


def main():
    # Загружаем исправленный (Y инвертирован) файл
    src = Path("road_segments_fixed.json")
    if not src.exists():
        src = Path("road_segments.json")
    segments = json.loads(src.read_text(encoding="utf-8"))
    print(f"Загружено из {src}")

    stitched = stitch_segments(segments)

    out = Path("road_segments_stitched.json")
    out.write_text(json.dumps(stitched, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Сохранено в {out} ({out.stat().st_size // 1024} KB)")

    password = input("Пароль администратора (Enter для пропуска загрузки): ").strip()
    if not password:
        print("Загрузка пропущена.")
        return

    server = "https://dayz-map.gto-team.uz"
    map_slug = "pripyat"

    session = requests.Session()
    r = session.post(f"{server}/api/admin/login", json={"password": password})
    if not r.ok:
        print(f"Ошибка входа: {r.status_code}")
        sys.exit(1)
    print("Авторизация успешна.")

    # Удаляем все существующие
    print("Получаю список сегментов для удаления...")
    r = session.get(f"{server}/api/admin/maps/{map_slug}/roads")
    if r.ok:
        old = r.json()
        print(f"Удаляю {len(old)} старых сегментов...")
        for i, seg in enumerate(old):
            session.delete(f"{server}/api/admin/maps/{map_slug}/roads/{seg['id']}", timeout=10)
            if (i + 1) % 200 == 0:
                print(f"  {i+1}/{len(old)}", end="\r")
        print(f"  Удалено {len(old)}")

    # Загружаем новые
    print(f"Загружаю {len(stitched)} сшитых сегментов...")
    ok = 0
    err = 0
    for i, seg in enumerate(stitched):
        r = session.post(f"{server}/api/admin/maps/{map_slug}/roads", json=seg, timeout=10)
        if r.ok:
            ok += 1
        else:
            err += 1
        if (i + 1) % 100 == 0 or i == len(stitched) - 1:
            print(f"  {i+1}/{len(stitched)} OK:{ok} ERR:{err}", end="\r")
    print(f"\nГотово! OK={ok} ERR={err}")


if __name__ == "__main__":
    main()
