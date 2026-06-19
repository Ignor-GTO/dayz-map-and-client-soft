#!/usr/bin/env python3
"""
fix_roads_y.py — Инвертирует Y координаты в road_segments.json и перезагружает на сервер.
"""
import json
import sys
from pathlib import Path

import requests

MAP_SIZE = 20480
segments_path = Path("road_segments.json")
segments = json.loads(segments_path.read_text(encoding="utf-8"))
print(f"Загружено {len(segments)} сегментов")

# Проверим диапазон Y до и после
all_y_before = [pt[1] for s in segments for pt in s["points"]]
print(f"Y до:   min={min(all_y_before):.1f}, max={max(all_y_before):.1f}")

# Инвертируем Y
fixed = []
for seg in segments:
    new_points = [[pt[0], round(MAP_SIZE - pt[1], 1)] for pt in seg["points"]]
    fixed.append({"road_type": seg["road_type"], "points": new_points})

all_y_after = [pt[1] for s in fixed for pt in s["points"]]
print(f"Y после: min={min(all_y_after):.1f}, max={max(all_y_after):.1f}")

# Сохраняем
out_path = Path("road_segments_fixed.json")
out_path.write_text(json.dumps(fixed, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(f"Сохранено в {out_path} ({out_path.stat().st_size // 1024} KB)")

# Загружаем на сервер
password = input("Пароль администратора: ").strip()
server = "https://dayz-map.gto-team.uz"
map_slug = "pripyat"

session = requests.Session()
login_r = session.post(f"{server}/api/admin/login", json={"password": password})
if not login_r.ok:
    print(f"Ошибка входа: {login_r.status_code}")
    sys.exit(1)
print("Авторизация успешна.")

# Удаляем старые
print("Удаляю старые дороги...")
del_r = session.delete(f"{server}/api/admin/maps/{map_slug}/roads")
if del_r.ok:
    print(f"  Удалено: {del_r.json().get('deleted', 0)}")
else:
    # старая версия сервера — обходим через одиночные запросы
    print(f"  DELETE /roads не работает ({del_r.status_code}), пропускаю")

# Загружаем новые
print(f"Загружаю {len(fixed)} исправленных сегментов...")
total = len(fixed)
ok = 0
err = 0
for i, seg in enumerate(fixed):
    r = session.post(
        f"{server}/api/admin/maps/{map_slug}/roads",
        json=seg,
        timeout=10,
    )
    if r.ok:
        ok += 1
    else:
        err += 1
        if err <= 3:
            print(f"  ERR {i}: {r.status_code} {r.text[:80]}")
    if (i + 1) % 200 == 0 or i == total - 1:
        print(f"  {i+1}/{total} | OK:{ok} ERR:{err}", end="\r")

print(f"\nГотово! OK={ok} ERR={err}")
