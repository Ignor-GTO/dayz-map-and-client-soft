"""Build server/static/data/scum-locations.json from scum-map.com GraphQL.

Hierarchical sections + typed markers (bunkers, crops, buildings, …)
with Russian labels, descriptions and photos when available.
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

SCUM_CDN = "https://scum-map.com"

# Display order + English section keys (RU resolved via i18n / fallback).
SECTION_META: list[tuple[str, str, bool]] = [
    # (english section name from API, fallback ru, default_enabled)
    ("Buildings", "Строения", False),
    ("Bunkers", "Бункеры", True),
    ("Construction materials", "Строительные материалы", False),
    ("Crops", "Овощи и фрукты", False),
    ("Loot containers", "Контейнеры с лутом", False),
    ("Outposts", "Аванпосты", True),
    ("Points of interest", "Основные объекты", True),
    ("Quests", "Квесты", False),
    ("Radiation", "Радиация", True),
    ("Vehicles", "Транспорт", False),
    ("Water sources", "Источники воды", False),
    ("Other", "Прочее", False),
]

# Fallback RU for categories missing from scum-map.com i18n catalog.
CATEGORY_RU_FALLBACK: dict[str, str] = {
    "Fishing spots": "Рыболовные места",
    "Wells": "Колодцы",
    "Natural springs": "Родники",
    "Hand water pumps": "Ручные колонки",
    "Water dispensers": "Диспенсеры воды",
    "Industrial storage silos": "Промышленные силосы",
    "Quest books": "Квестовые книги",
    "Decorative fountains": "Декоративные фонтаны",
    "Fountains": "Фонтаны",
    "Mine entrances": "Входы в шахты",
    "Animal feeders": "Кормушки для животных",
    "Hairdresser": "Парикмахерская",
    "Fig trees": "Инжир",
    "Rose hip / dog rose": "Шиповник",
    "Hunter's Grotto": "Охотничий грот",
    "Bunker Hatch Doors": "Люки бункеров",
    "Phone Booths": "Телефонные будки",
    "Red Toolboxes": "Красные ящики с инструментами",
    "Pile of planks": "Кучи досок",
    "Secret Bunkers": "Секретные бункеры",
    "Military Hangars": "Военные ангары",
    "Gun Shops": "Оружейные магазины",
    "Hunting Shops": "Охотничьи магазины",
    "Samobor POIs": "Объекты Самобора",
    "Bookshelves": "Книжные полки",
    "Novigrad POIs": "Объекты Новиграда",
    "Quest Mailboxes": "Квестовые почтовые ящики",
    "Quest Boards": "Квестовые доски",
    "ATM": "Банкоматы",
    "Restaurants": "Рестораны",
    "Loot containers": "Контейнеры с лутом",
    "Quests": "Квесты",
    "Olive trees": "Оливковые деревья",
}

# Higher min_zoom for dense categories (keeps map usable with many filters on).
DENSE_CATEGORY_IDS = {
    37, 38, 39, 40, 41, 42, 43, 44, 45, 47, 48, 49, 50, 52, 53, 54,  # crops
    28, 29, 30, 60, 790,  # construction
    20, 23, 36, 78, 19, 21, 22,  # vehicles
    24, 25, 34, 7,  # hunting towers / cabins / sheds / garages
    871, 872, 873,  # trees
    858, 869, 866, 778, 789, 210,  # fishing / feeders / decorative / toolboxes / shelves / ATM
}

VERY_DENSE_CATEGORY_IDS = {
    37, 38, 39, 40, 41, 42, 43, 44, 45, 47, 48, 49, 50, 52, 53, 54,
    20, 23, 36, 871, 872, 873,
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


def fetch_i18n_ru() -> dict[str, str]:
    data = gql(
        """
        query($locale: String!) {
          i18n {
            list(locale: $locale) {
              key
              value
            }
          }
        }
        """,
        {"locale": "ru"},
    )
    if data.get("errors"):
        print("i18n errors", data["errors"])
        return {}
    items = (((data.get("data") or {}).get("i18n") or {}).get("list")) or []
    return {str(it["key"]): str(it["value"]) for it in items if it.get("key") and it.get("value")}


def tr(i18n: dict[str, str], key: str | None, fallback: str | None = None) -> str:
    raw = (key or "").strip()
    if not raw:
        return (fallback or "").strip()
    if raw in i18n:
        return clean_ru_label(i18n[raw])
    if raw in CATEGORY_RU_FALLBACK:
        return CATEGORY_RU_FALLBACK[raw]
    return clean_ru_label(fallback or raw)


def clean_ru_label(text: str) -> str:
    """Drop trailing English parentheticals like 'Яблоки (Apple)'."""
    s = (text or "").strip()
    s = re.sub(r"\s*\(([A-Za-z][^)]*)\)\s*$", "", s).strip()
    return s or text


def abs_image_url(path: str | None) -> str | None:
    if not path:
        return None
    p = str(path).strip()
    if not p:
        return None
    if p.startswith("http://") or p.startswith("https://"):
        return p
    if p.startswith("/"):
        return f"{SCUM_CDN}{p}"
    return f"{SCUM_CDN}/{p}"


def pick_images(image_path: str | None, image_list: list | None) -> list[str]:
    """Prefer place photos, then aerial, then plans / other."""
    urls: list[str] = []
    seen: set[str] = set()

    def add(path: str | None) -> None:
        url = abs_image_url(path)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)

    typed: list[tuple[int, str]] = []
    for item in image_list or []:
        fp = (item or {}).get("filePath") if isinstance(item, dict) else None
        if not fp:
            continue
        low = str(fp).lower()
        if "place_photo" in low:
            prio = 0
        elif "aerial_photo" in low:
            prio = 1
        elif "/plan/" in low or "plan/" in low:
            prio = 3
        else:
            prio = 2
        typed.append((prio, str(fp)))
    typed.sort(key=lambda t: t[0])
    for _, fp in typed:
        add(fp)
    add(image_path)
    return urls[:6]


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
    chunk = 30
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
            description
            imagePath
            imageList { id filePath }
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


def bunker_code_from_images(image_path: str | None, image_list: list | None) -> str | None:
    paths: list[str] = []
    if image_path:
        paths.append(str(image_path))
    for item in image_list or []:
        fp = (item or {}).get("filePath") if isinstance(item, dict) else None
        if fp:
            paths.append(str(fp))
    for path in paths:
        m = re.search(r"/([a-z]\d+[a-z]?)(?:_bunker)?\.(?:jpg|jpeg|png|webp)$", path, re.I)
        if m:
            return m.group(1).upper()
        m = re.search(r"/bunker/([a-z0-9]+)\.(?:jpg|jpeg|png|webp)$", path, re.I)
        if m:
            return m.group(1).upper()
    return None


def nice_title(
    raw_title: str | None,
    category_name_en: str | None,
    category_label_ru: str,
    number: object | None,
    i18n: dict[str, str],
    image_path: str | None = None,
    image_list: list | None = None,
) -> str:
    title = (raw_title or "").strip()
    cat_en = (category_name_en or "").strip()
    num = str(number).strip() if number not in (None, "", 0, "0") else ""

    # Translate known English titles via i18n when possible.
    if title and title in i18n:
        title = clean_ru_label(i18n[title])
    elif title and title.lower() == cat_en.lower():
        title = category_label_ru
    elif not title:
        title = category_label_ru

    # "D1 Bunker" / "Z2 Bunker" → «Бункер D1»
    m = re.match(r"^([A-Za-z]\d+[A-Za-z]?)\s+Bunker$", title, re.I)
    if m:
        return f"Бункер {m.group(1).upper()}"
    m = re.match(r"^Bunker\s+([A-Za-z]\d+[A-Za-z]?)$", title, re.I)
    if m:
        return f"Бункер {m.group(1).upper()}"

    generic = (not title) or title.lower() in {cat_en.lower(), category_label_ru.lower(), "bunkers", "бункеры"}
    if generic:
        code = bunker_code_from_images(image_path, image_list)
        if code:
            return f"Бункер {code}"
        if num and category_label_ru:
            return f"{category_label_ru} {num}"
        return category_label_ru or title or "POI"
    if num and num not in title:
        return f"{title} ({num})"
    return title


def short_description(description: str | None, category_label_ru: str, title: str) -> str | None:
    text = (description or "").strip()
    if text:
        # Translate if the whole description is an i18n key (rare).
        return text
    # Lightweight fallback so popup is not empty for important places.
    if category_label_ru and category_label_ru.lower() not in title.lower():
        return category_label_ru
    return None


def main() -> None:
    print("fetching i18n (ru)…")
    i18n = fetch_i18n_ru()
    print("i18n keys", len(i18n))

    print("fetching categories…")
    cats = fetch_categories()
    print("categories", len(cats))

    cat_by_id: dict[int, dict] = {}
    for c in cats:
        cid = int(c["id"])
        section_en = ((c.get("section") or {}).get("name")) or "Other"
        app = c.get("appearance") or {}
        name_en = c.get("name") or f"#{cid}"
        label_ru = tr(i18n, name_en, CATEGORY_RU_FALLBACK.get(name_en, name_en))
        cat_by_id[cid] = {
            "id": f"scum_{cid}",
            "raw_id": cid,
            "label": label_ru,
            "label_en": name_en,
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
    with_img = 0
    with_desc = 0

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
        title = nice_title(
            layer.get("title"),
            meta["label_en"],
            meta["label"],
            layer.get("number"),
            i18n,
            layer.get("imagePath"),
            layer.get("imageList"),
        )
        key = (f"{meta['id']}:{title.lower()}", round(x, 0), round(y, 0))
        if key in seen:
            continue
        seen.add(key)

        if cid in VERY_DENSE_CATEGORY_IDS:
            min_zoom = 5
        elif cid in DENSE_CATEGORY_IDS:
            min_zoom = 4
        else:
            min_zoom = 2
        if meta["section_id"] in {"points_of_interest", "bunkers"} and cid in {27, 26, 1, 456, 763, 9, 14}:
            min_zoom = 1

        images = pick_images(layer.get("imagePath"), layer.get("imageList"))
        desc = short_description(layer.get("description"), meta["label"], title)
        if images:
            with_img += 1
        if desc:
            with_desc += 1

        loc: dict = {
            "title": title,
            "category": meta["id"],
            "type": slugify(meta["label_en"]),
            "label_class": "scum-pin",
            "section_id": meta["section_id"],
            "icon": meta["icon"],
            "color": meta["color"],
            "x": x,
            "y": y,
            "min_zoom": min_zoom,
        }
        if desc:
            loc["description"] = desc
        if images:
            loc["image"] = images[0]
            if len(images) > 1:
                loc["images"] = images
        # Dense pins render as lightweight dots on the client.
        if cid in DENSE_CATEGORY_IDS or cid in VERY_DENSE_CATEGORY_IDS:
            loc["dense"] = True
        locations.append(loc)
        counts[meta["id"]] += 1

    section_lookup = {slugify(en): (en, ru, enabled) for en, ru, enabled in SECTION_META}
    by_section: dict[str, list[dict]] = defaultdict(list)
    for meta in cat_by_id.values():
        by_section[meta["section_id"]].append(meta)

    sections = []
    for en, ru_fallback, enabled in SECTION_META:
        sid = slugify(en)
        items = sorted(by_section.get(sid, []), key=lambda m: (m["sort_order"], m["label"]))
        categories = []
        section_count = 0
        section_label = tr(i18n, en, ru_fallback)
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
                "label": section_label,
                "count": section_count,
                "default_enabled": enabled,
                "categories": categories,
            }
        )

    # Orphan categories without a known section → Other
    known = {s["id"] for s in sections}
    orphan_metas = [m for m in cat_by_id.values() if m["section_id"] not in known and counts.get(m["id"], 0)]
    if orphan_metas:
        other = next((s for s in sections if s["id"] == "other"), None)
        if not other:
            other = {
                "id": "other",
                "label": tr(i18n, "Other", "Прочее"),
                "count": 0,
                "default_enabled": False,
                "categories": [],
            }
            sections.append(other)
        for meta in sorted(orphan_metas, key=lambda m: (m["sort_order"], m["label"])):
            cnt = counts.get(meta["id"], 0)
            other["count"] += cnt
            other["categories"].append(
                {
                    "id": meta["id"],
                    "label": meta["label"],
                    "count": cnt,
                    "icon": meta["icon"],
                    "color": meta["color"],
                    "default_enabled": False,
                }
            )

    flat_categories = [
        {"id": c["id"], "label": c["label"], "count": c["count"]}
        for s in sections
        for c in s["categories"]
    ]

    payload = {
        "format": "scum_sections_v2",
        "source": "scum-map.com GraphQL (public markers)",
        "attribution": "Marker data © scum-map.com community",
        "locale": "ru",
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
        "with_img",
        with_img,
        "with_desc",
        with_desc,
        "bytes",
        out.stat().st_size,
    )


if __name__ == "__main__":
    main()
