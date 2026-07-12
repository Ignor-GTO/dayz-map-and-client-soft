"""Trader price lookup via public map API."""

from __future__ import annotations

import difflib

import httpx

from item_tooltip_ocr import is_valid_item_name, normalize_item_name


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


def _match_score(query: str, name: str) -> float:
    q = query.strip().casefold()
    n = name.strip().casefold()
    if not q or not n:
        return 0.0
    if q == n:
        return 1.0
    if q in n or n in q:
        shorter = min(len(q), len(n))
        longer = max(len(q), len(n))
        if shorter >= 3:
            return 0.78 + 0.2 * (shorter / longer)
    return difflib.SequenceMatcher(None, q, n).ratio()


def pick_best_match(query: str, items: list[dict]) -> dict | None:
    if not items:
        return None
    q = normalize_item_name(query).casefold()
    if len(q) < 2:
        return None

    best_item: dict | None = None
    best_score = 0.0
    for item in items:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        score = _match_score(q, name)
        if score > best_score:
            best_score = score
            best_item = item

    if best_score >= 0.58:
        return best_item
    return None


def lookup_item_price(server_url: str, map_slug: str, item_name: str) -> dict | None:
    name = normalize_item_name(item_name)
    if not is_valid_item_name(name):
        return None
    items = search_trader_items(server_url, map_slug, name, limit=15)
    match = pick_best_match(name, items)
    if match:
        return match
    # Retry with shorter token for long names like "AN/PVS-4 Ночной прицел".
    short = name.split()[0] if " " in name else name
    if short != name and len(short) >= 3:
        items = search_trader_items(server_url, map_slug, short, limit=15)
        match = pick_best_match(name, items)
        if match:
            return match
    if "/" in name:
        token = name.split("/")[-1].split()[0]
        if len(token) >= 3:
            items = search_trader_items(server_url, map_slug, token, limit=15)
            match = pick_best_match(name, items)
            if match:
                return match
    return None
