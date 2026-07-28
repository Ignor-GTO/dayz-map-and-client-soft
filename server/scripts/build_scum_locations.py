"""Build server/static/data/scum-locations.json from scum-map.com GraphQL.

Hierarchical sections + typed markers (bunkers, crops, buildings, …).
"""
from __future__ import annotations

import json
import re
import urllib.request
from collections import defaultdict
from pathlib import Path

UA = {
    "User-Agent": "DayZMapSoft/1.0 (+SCUM location mirror)",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://scum-map.com",
    "Referer": "https://scum-map.com/ru/scum/island",
}

# Display order + Russian labels (aligned with scum-map.com sidebar).
SECTION_META: list[tuple[str, str, bool]] = [
    # (english section name from API, ru label, default_enabled)
    ("Buildings", "Строения", False),
    ("Bunkers", "Бункеры", True),
    ("Construction materials", "Строительные материалы", False),
    ("Crops", "Овощи и фрукты", False),
    ("Loot containers", "Loot containers", False),
    ("Outposts", "Аванпосты", True),
    ("Points of interest", "Основные объекты", True),
    ("Quests", "Quests", False),
    ("Radiation", "Радиация", True),
    ("Vehicles", "Транспорт", False),
    ("Water sources", "Источники воды", False),
    ("Other", "Прочее", False),
]

# Higher min_zoom for dense categories.
DENSE_CATEGORY_IDS = {
    37, 38, 39, 40, 41, 42, 43, 44, 45, 47, 48, 49, 50, 52, 53, 54,  # crops
    28, 29, 30, 60, 790,  # construction
    20, 23, 36, 78, 19, 21, 22,  # vehicles
    24, 25, 34, 7,  # hunting towers / cabins / sheds / garages
    871, 872, 873,  # trees
}


def gql(query: str, variables: dict | None = None, locale: str = "ru") -> dict:
    url = f"https://scum-map.com/{locale}/gql/"
    payload = {"query": query, "variables": variables or {}}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=UA, method="POST")
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


def slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return s or "other"


def fetch_categories() -> list[dict]:
    data = gql(
        """
        query($urlId: MapUrlIdScalar!) {
          mapCategory {
            listForMap(urlId: $urlId, customOnly: false) {
              id
              name
              sortOrder
              section { name }
              appearance { color colorBackground icon }
            }
          }
        }
        """,
        {"urlId": "bunkers_and_killboxes"},
    )
    if data.get("errors"):
        raise RuntimeError(data["errors"])
    return (((data.get("data") or {}).get("mapCategory") or {}).get("listForMap")) or []


def fetch_layers(category_ids: list[int]) -> list[dict]:
    all_layers: list[dict] = []
    chunk = 40
    query = """
    query($categoryIdList: [Int!]!, $includeWithoutCategory: Boolean!) {
      mapLayer {
        list(
          categoryIdList: $categoryIdList
          urlId: null
          includeWithoutCategory: $includeWithoutCategory
        ) {
          id
          title
          ... on MapLayerMarker {
            ingameLongitude
            ingameLatitude
            number
          }
          category { id name }
        }
      }
    }
    """
    for i in range(0, len(category_ids), chunk):
        part = category_ids[i : i + chunk]
        data = gql(query, {"categoryIdList": part, "includeWithoutCategory": False})
        if data.get("errors"):
            raise RuntimeError(data["errors"])
        layers = (((data.get("data") or {}).get("mapLayer") or {}).get("list")) or []
        print(f"  chunk {i}-{i+len(part)} -> {len(layers)}")
        all_layers.extend(layers)
    return all_layers


def nice_title(raw_title: str | None, category_name: str | None, number: object | None) -> str:
    title = (raw_title or "").strip()
    cat = (category_name or "").strip()
    num = str(number).strip() if number not in (None, "", 0, "0") else ""
    if not title or title.lower() == cat.lower():
        if num and cat:
            return f"{cat} {num}"
        return cat or title or "POI"
    if num and num not in title:
        return f"{title} ({num})"
    return title


def main() -> None:
    print("fetching categories…")
    cats = fetch_categories()
    print("categories", len(cats))

    cat_by_id: dict[int, dict] = {}
    for c in cats:
        cid = int(c["id"])
        section_en = ((c.get("section") or {}).get("name")) or "Other"
        app = c.get("appearance") or {}
        cat_by_id[cid] = {
            "id": f"scum_{cid}",
            "raw_id": cid,
            "label": c.get("name") or f"#{cid}",
            "section_en": section_en,
            "section_id": slugify(section_en),
            "icon": app.get("icon") or "faMapMarker",
            "color": app.get("colorBackground") or app.get("color") or "#888888",
            "sort_order": int(c.get("sortOrder") or 9999),
        }

    ids = sorted(cat_by_id.keys())
    print("fetching layers for", len(ids), "categories…")
    layers = fetch_layers(ids)
    print("raw layers", len(layers))

    locations = []
    seen: set[tuple[str, float, float]] = set()
    counts: dict[str, int] = defaultdict(int)

    for layer in layers:
        cat = layer.get("category") or {}
        cid = int(cat.get("id") or 0)
        meta = cat_by_id.get(cid)
        if not meta:
            continue
        x = layer.get("ingameLongitude")
        y = layer.get("ingameLatitude")
        if x is None or y is None:
            continue
        x = float(x)
        y = float(y)
        title = nice_title(layer.get("title"), cat.get("name"), layer.get("number"))
        key = (f"{meta['id']}:{title.lower()}", round(x, 0), round(y, 0))
        if key in seen:
            continue
        seen.add(key)
        min_zoom = 4 if cid in DENSE_CATEGORY_IDS else 2
        if meta["section_id"] in {"points_of_interest", "bunkers"} and cid in {27, 26, 1, 456, 763}:
            min_zoom = 1
        loc = {
            "title": title,
            "category": meta["id"],  # fine-grained filter id
            "type": slugify(meta["label"]),
            "label_class": "scum-pin",
            "section_id": meta["section_id"],
            "icon": meta["icon"],
            "color": meta["color"],
            "x": x,
            "y": y,
            "min_zoom": min_zoom,
        }
        locations.append(loc)
        counts[meta["id"]] += 1

    # Build sections in preferred order
    section_lookup = {slugify(en): (en, ru, enabled) for en, ru, enabled in SECTION_META}
    by_section: dict[str, list[dict]] = defaultdict(list)
    for meta in cat_by_id.values():
        by_section[meta["section_id"]].append(meta)

    sections = []
    for en, ru, enabled in SECTION_META:
        sid = slugify(en)
        items = sorted(by_section.get(sid, []), key=lambda m: (m["sort_order"], m["label"]))
        categories = []
        section_count = 0
        for meta in items:
            cnt = counts.get(meta["id"], 0)
            if cnt <= 0:
                continue
            section_count += cnt
            categories.append(
                {
                    "id": meta["id"],
                    "label": meta["label"],
                    "count": cnt,
                    "icon": meta["icon"],
                    "color": meta["color"],
                    "default_enabled": enabled,
                }
            )
        if not categories:
            continue
        sections.append(
            {
                "id": sid,
                "label": ru,
                "count": section_count,
                "default_enabled": enabled,
                "categories": categories,
            }
        )

    # Flat categories for backward-compatible DayZ filter consumers
    flat_categories = [
        {"id": c["id"], "label": c["label"], "count": c["count"]}
        for s in sections
        for c in s["categories"]
    ]

    payload = {
        "format": "scum_sections_v1",
        "source": "scum-map.com GraphQL (public markers)",
        "attribution": "Marker data © scum-map.com community",
        "sections": sections,
        "categories": flat_categories,
        "locations": locations,
    }

    out = Path(__file__).resolve().parents[1] / "static" / "data" / "scum-locations.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(
        "wrote",
        out,
        "locations",
        len(locations),
        "sections",
        len(sections),
        "bytes",
        out.stat().st_size,
    )


if __name__ == "__main__":
    main()
