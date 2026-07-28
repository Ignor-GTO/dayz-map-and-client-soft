"""Build server/static/data/scum-locations.json from scum-map.com GraphQL.

Data source: public GraphQL at https://scum-map.com/{locale}/gql/
Coordinates: ingameLongitude/ingameLatitude (SCUM cm).
"""
from __future__ import annotations

import json
import urllib.request
from collections import Counter
from pathlib import Path

UA = {
    "User-Agent": "DayZMapSoft/1.0 (+local mirror of public SCUM POI labels)",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://scum-map.com",
    "Referer": "https://scum-map.com/ru/scum/island",
}

# Category id -> (our_category, label_class, min_zoom)
# Keep place-name style labels (like scum-map.com / gamemaps), not every loot spawn.
CATEGORY_MAP: dict[int, tuple[str, str, int]] = {
    # Settlements / named places
    27: ("cities", "city", 1),  # Villages
    26: ("local", "local", 2),  # Points of interest
    16: ("local", "local", 2),  # Samobor POIs
    31: ("local", "local", 2),  # Novigrad POIs
    420: ("local", "local", 2),  # Krsko POIs
    80: ("military", "military", 2),  # Outposts
    # Military / bunkers
    1: ("military", "military", 2),  # Bunkers
    456: ("military", "military", 2),  # Abandoned bunkers
    763: ("military", "military", 2),  # Secret Bunkers
    9: ("military", "military", 2),  # Killboxes
    14: ("military", "military", 2),  # WW2 bunkers
    761: ("military", "military", 3),  # Military Hangars
    320: ("military", "military", 3),  # Military Warehouses
    # Key infrastructure
    10: ("local", "local", 2),  # Police stations
    8: ("local", "local", 2),  # Gas stations
    5: ("local", "local", 3),  # Churches
    151: ("local", "local", 2),  # Hospital
    62: ("local", "local", 3),  # Schools
    18: ("local", "local", 2),  # Lighthouses
    17: ("local", "local", 3),  # Hunting Camps
    # Nature
    4: ("terrain", "terrain", 3),  # Caves
    279: ("terrain", "terrain", 3),  # Underwater Caves
    868: ("terrain", "terrain", 3),  # Mine entrances
    58: ("water", "water", 3),  # Big Shipwrecks
}

CATEGORY_LABELS = {
    "cities": "Населённые пункты",
    "military": "Военные / бункеры",
    "local": "Локации",
    "water": "Вода / затонувшие",
    "terrain": "Пещеры / рельеф",
}


def gql(query: str, variables: dict | None = None, locale: str = "ru") -> dict:
    url = f"https://scum-map.com/{locale}/gql/"
    payload = {"query": query, "variables": variables or {}}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=UA, method="POST")
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_layers(category_ids: list[int]) -> list[dict]:
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
    data = gql(
        query,
        {"categoryIdList": category_ids, "includeWithoutCategory": False},
    )
    if data.get("errors"):
        raise RuntimeError(data["errors"])
    return (((data.get("data") or {}).get("mapLayer") or {}).get("list")) or []


def nice_title(raw_title: str | None, category_name: str | None, number: object | None) -> str:
    title = (raw_title or "").strip()
    cat = (category_name or "").strip()
    num = str(number).strip() if number not in (None, "", 0, "0") else ""
    if not title or title.lower() == cat.lower():
        if num and cat:
            return f"{cat} {num}"
        return cat or title or "POI"
    if num and num not in title:
        return f"{title} {num}"
    return title


def main() -> None:
    ids = sorted(CATEGORY_MAP.keys())
    print("fetching categories", ids)
    layers = fetch_layers(ids)
    print("raw layers", len(layers))

    locations = []
    seen: set[tuple[str, float, float]] = set()
    for layer in layers:
        cat = layer.get("category") or {}
        cid = int(cat.get("id") or 0)
        if cid not in CATEGORY_MAP:
            continue
        x = layer.get("ingameLongitude")
        y = layer.get("ingameLatitude")
        if x is None or y is None:
            continue
        x = float(x)
        y = float(y)
        our_cat, label_class, min_zoom = CATEGORY_MAP[cid]
        title = nice_title(layer.get("title"), cat.get("name"), layer.get("number"))
        key = (title.lower(), round(x, 1), round(y, 1))
        if key in seen:
            continue
        seen.add(key)
        locations.append(
            {
                "title": title,
                "category": our_cat,
                "type": (cat.get("name") or our_cat).lower().replace(" ", "_"),
                "label_class": label_class,
                "x": x,
                "y": y,
                "min_zoom": min_zoom,
            }
        )

    counts = Counter(loc["category"] for loc in locations)
    categories = [
        {"id": cid, "label": CATEGORY_LABELS[cid], "count": counts[cid]}
        for cid in CATEGORY_LABELS
        if counts.get(cid, 0) > 0
    ]
    payload = {
        "source": "scum-map.com GraphQL (public markers)",
        "attribution": "Marker data © scum-map.com community",
        "categories": categories,
        "locations": locations,
    }

    out = Path(__file__).resolve().parents[1] / "static" / "data" / "scum-locations.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("wrote", out, "locations", len(locations), "categories", categories)
    print("by type", Counter(l["type"] for l in locations).most_common(15))


if __name__ == "__main__":
    main()
