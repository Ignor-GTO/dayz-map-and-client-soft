#!/usr/bin/env python3
"""Parse trade.txt into obitel_trade.json for admin import."""

from __future__ import annotations

import json
import re
from pathlib import Path

TRADER = "Обитель"
SOURCE = Path(r"d:\LLAMA\trade.txt")
OUTPUT = Path(__file__).resolve().parent / "obitel_trade.json"

PRICE_PAIR = re.compile(
    r"(.+?)\s*[—–-]\s*покупка\s+(\d+)\s*/\s*продажа\s+(\d+)",
    re.IGNORECASE,
)
PRICE_BUY_ONLY = re.compile(
    r"(.+?)\s*[—–-]\s*покупка\s+(\d+)\s*$",
    re.IGNORECASE,
)
TABLE_ROW = re.compile(r"^\s*(.+?)\s*\|\s*(\d*)\s*\|\s*(\d*)\s*$")
BUY_SELL_INLINE = re.compile(
    r"(.+?)\s*[—–-]\s*покупка\s+(\d+)\s*/\s*продажа\s+(\d+)",
    re.IGNORECASE,
)
SCOUT_SINGLE = re.compile(r"(.+?)\s*[—–-]\s*(\d+)")


def item(trader: str, section: str, subsection: str, name: str, buy: int, sell: int) -> dict:
    return {
        "trader": trader,
        "section": section,
        "subsection": subsection,
        "name": name.strip(),
        "buy_price": int(buy),
        "sell_price": int(sell),
    }


def parse_int(value: str) -> int:
    value = (value or "").strip()
    return int(value) if value else 0


def normalize_chimera_claw(name: str, sell_price: int) -> str:
    if name.strip() == "Коготь химеры":
        if sell_price == 960:
            return "Коготь химеры (малый)"
        if sell_price == 6000:
            return "Коготь химеры (большой)"
    return name.strip()


def parse_medic_block(text: str, section: str) -> list[dict]:
    items: list[dict] = []
    subsection = ""
    blob = " ".join(text.split())

    # Split by subsection headers (capitalized phrases before item patterns)
    parts = re.split(
        r"\s+(?=CDV-700|Радиационный|Сигарета|Противогаз|Полевая|Детектор|Болт|Фильтр противогаза)",
        blob,
    )

    headers = [
        ("CDV-700", "Счетчики Гейгера"),
        ("Радиационный", "Тестер на радиацию"),
        ("Сигарета", "Лечение от радиации"),
        ("Противогаз", "Радиационная защита"),
        ("Полевая", "Спецсвязь по выбросам"),
        ("Детектор", "Детекторы артефактов"),
        ("Болт", "Болты для разрядки аномалий"),
    ]

    for chunk in parts:
        chunk = chunk.strip()
        if not chunk:
            continue
        subsection = "Полевой медик"
        for prefix, sub in headers:
            if chunk.startswith(prefix) or prefix in chunk[:40]:
                subsection = sub
                break

        for m in BUY_SELL_INLINE.finditer(chunk):
            name, buy, sell = m.group(1).strip(), int(m.group(2)), int(m.group(3))
            if name.startswith("Фильтр противогаза"):
                name = "Фильтр противогаза STAYER A1"
            items.append(item(TRADER, section, subsection, name, buy, sell))

        # Filter without sell price
        if "Фильтр противогаза STAYER" in chunk and not any(
            i["name"] == "Фильтр противогаза STAYER A1" for i in items
        ):
            m = re.search(r"Фильтр противогаза STAYER\s*A1\s*[—–-]\s*покупка\s+(\d+)", chunk)
            if m:
                items.append(
                    item(TRADER, section, "Радиационная защита", "Фильтр противогаза STAYER A1", int(m.group(1)), 0)
                )

        # Split combined lines manually for medic
        extra_patterns = [
            ("CDV-700", "Счетчики Гейгера", 3250, 975),
            ("Радиационный Инъектор", "Тестер на радиацию", 5200, 1560),
            ("Сигарета", "Лечение от радиации", 325, 97),
            ("Косяк", "Лечение от радиации", 2860, 858),
            ("Противогаз РШ4", "Радиационная защита", 15000, 1500),
            ("Полевая радиостанция", "Спецсвязь по выбросам", 3750, 1200),
            ("Армейская рация", "Спецсвязь по выбросам", 110000, 33000),
            ("Детектор Отклик", "Детекторы артефактов", 53500, 16050),
            ("Болт", "Болты для разрядки аномалий", 5, 1),
        ]
        for name, sub, buy, sell in extra_patterns:
            if not any(i["name"] == name for i in items):
                items.append(item(TRADER, section, sub, name, buy, sell))

    # Deduplicate by name+subsection keeping first
    seen = set()
    unique = []
    for row in items:
        key = (row["subsection"], row["name"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def parse_scout_parts(text: str, section: str, subsection: str) -> list[dict]:
    items: list[dict] = []
    blob = " ".join(text.split())
    for name, price_s in re.findall(r"(.+?)\s*[—–-]\s*(\d+)", blob):
        name = re.sub(r"\s+", " ", name).strip()
        price = int(price_s)
        name = normalize_chimera_claw(name, price)
        items.append(item(TRADER, section, subsection, name, 0, price))
    return items


def parse_batushka(lines: list[str]) -> list[dict]:
    items: list[dict] = []
    section = "Батюшка"
    subsection = ""
    parent_sub = ""
    in_table = False

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue

        if line.startswith("Подраздел:"):
            parent_sub = line.split(":", 1)[1].strip()
            if parent_sub == "Еда":
                subsection = parent_sub  # will become Еда — X
            elif parent_sub in ("Оружие", "Медицина", "Расходники"):
                subsection = parent_sub
            else:
                subsection = parent_sub
            in_table = False
            continue

        if line.startswith("РАЗДЕЛ:"):
            subsection = line.split(":", 1)[1].strip()
            in_table = False
            continue

        m_cat = re.match(r"^\[(.+)\]$", line.strip())
        if m_cat:
            cat = m_cat.group(1).strip()
            if parent_sub in ("Еда", "Оружие", "Медицина", "Расходники"):
                subsection = f"{parent_sub} — {cat}"
            else:
                subsection = cat
            in_table = False
            continue

        if "Предмет" in line and "Покупка" in line:
            in_table = True
            continue
        if line.strip().startswith("---"):
            continue
        if line.strip().startswith("===="):
            in_table = False
            continue

        if in_table:
            m = TABLE_ROW.match(line)
            if not m:
                continue
            name = m.group(1).strip()
            buy = parse_int(m.group(2))
            sell = parse_int(m.group(3))

            # Misplaced item: pants listed under backpacks
            if subsection == "Рюкзаки" and name == "Брюки":
                subsection_override = "Ноги"
            else:
                subsection_override = subsection

            items.append(item(TRADER, section, subsection_override, name, buy, sell))

    return items


def main() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    chunks = re.split(r"-{10,}", text)

    all_items: list[dict] = []

    # Block 0: medic
    medic_chunk = chunks[0]
    medic_text = medic_chunk.split("Раздел: Сборщик органов мутантов")[0]
    medic_text = medic_text.split("Раздел: Полевой медик", 1)[-1]
    all_items.extend(parse_medic_block(medic_text, "Полевой медик"))

    # Block 1: scout
    scout_chunk = chunks[1] if len(chunks) > 1 else ""
    parts_chunk = scout_chunk.split("Подраздел: Шкуры животных")
    mutants = parts_chunk[0].split("Подраздел: Части тел мутантов")[-1]
    skins = parts_chunk[1].split("Раздел: Батюшка")[0] if len(parts_chunk) > 1 else ""

    all_items.extend(parse_scout_parts(mutants, "Сборщик органов мутантов", "Части тел мутантов"))
    all_items.extend(parse_scout_parts(skins, "Сборщик органов мутантов", "Шкуры животных"))

    # Batushka
    batushka_start = text.split("Раздел: Батюшка", 1)[-1]
    batushka_lines = batushka_start.splitlines()
    all_items.extend(parse_batushka(batushka_lines))

    # Fix Еда subsections prefix
    for row in all_items:
        if row["section"] == "Батюшка" and row["subsection"] == "Еда":
            row["subsection"] = "Еда — Общее"

    OUTPUT.write_text(json.dumps(all_items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(all_items)} items to {OUTPUT}")


if __name__ == "__main__":
    main()
