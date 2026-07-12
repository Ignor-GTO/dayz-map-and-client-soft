"""Trader price lookup via public map API."""

from __future__ import annotations

import httpx


def fmt_price(value: int | float | None) -> str:
    n = int(value or 0)
    return f"{n:,}".replace(",", " ")


def search_trader_items(
    server_url: str,
    map_slug: str,
    query: str,
    *,
    limit: int = 10,
) -> list[dict]:
    q = str(query or "").strip()
    if not q:
        return []
    base = server_url.rstrip("/")
    r = httpx.get(
        f"{base}/api/maps/{map_slug}/traders/items",
        params={"q": q, "limit": max(1, min(limit, 50))},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else []


def pick_best_match(query: str, items: list[dict]) -> dict | None:
    if not items:
        return None
    q = query.strip().casefold()
    for item in items:
        name = str(item.get("name") or "").strip()
        if name.casefold() == q:
            return item
    for item in items:
        name = str(item.get("name") or "").strip().casefold()
        if q in name or name in q:
            return item
    return items[0]


def lookup_item_price(server_url: str, map_slug: str, item_name: str) -> dict | None:
    items = search_trader_items(server_url, map_slug, item_name, limit=15)
    return pick_best_match(item_name, items)
