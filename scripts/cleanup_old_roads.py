#!/usr/bin/env python3
"""
cleanup_old_roads.py — Удаляет первые N сегментов дорог по ID (старые с неправильным Y).
"""
import sys
import requests

server = "https://dayz-map.gto-team.uz"
map_slug = "pripyat"

password = input("Пароль администратора: ").strip()
session = requests.Session()

login_r = session.post(f"{server}/api/admin/login", json={"password": password})
if not login_r.ok:
    print(f"Ошибка входа: {login_r.status_code}")
    sys.exit(1)
print("Авторизация успешна.")

# Получаем все сегменты
print("Получаю список всех сегментов...")
r = session.get(f"{server}/api/admin/maps/{map_slug}/roads")
if not r.ok:
    print(f"Ошибка: {r.status_code} {r.text}")
    sys.exit(1)

segments = r.json()
print(f"Всего сегментов: {len(segments)}")

# Сортируем по ID, берём первые 6172 (старые)
segments_sorted = sorted(segments, key=lambda s: s["id"])
to_delete = segments_sorted[:6172]
print(f"Удаляю {len(to_delete)} старых сегментов (ID {to_delete[0]['id']} — {to_delete[-1]['id']})...")

ok = 0
err = 0
for i, seg in enumerate(to_delete):
    r = session.delete(f"{server}/api/admin/maps/{map_slug}/roads/{seg['id']}", timeout=10)
    if r.ok:
        ok += 1
    else:
        err += 1
        if err <= 3:
            print(f"  ERR id={seg['id']}: {r.status_code}")
    if (i + 1) % 200 == 0 or i == len(to_delete) - 1:
        print(f"  {i+1}/{len(to_delete)} | OK:{ok} ERR:{err}", end="\r")

print(f"\nГотово! Удалено: {ok}, ошибок: {err}")
print(f"Осталось в БД: {len(segments) - ok}")
