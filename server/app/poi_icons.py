"""POI icon presets for admin and map display."""

POI_ICONS: dict[str, dict[str, str]] = {
    "star": {"glyph": "★", "label": "Звезда", "color": "#3498db"},
    "trader": {"glyph": "🛒", "label": "Торговец", "color": "#2980b9"},
    "camp": {"glyph": "⛺", "label": "Лагерь", "color": "#c0392b"},
    "heli": {"glyph": "H", "label": "Вертолёт", "color": "#e91e9b"},
    "skull": {"glyph": "☠", "label": "Опасно", "color": "#2c3e50"},
    "house": {"glyph": "⌂", "label": "Дом", "color": "#8e44ad"},
    "car": {"glyph": "🚗", "label": "Техника", "color": "#16a085"},
    "loot": {"glyph": "📦", "label": "Лут", "color": "#d35400"},
    "medical": {"glyph": "+", "label": "Медицина", "color": "#27ae60"},
    "water": {"glyph": "≋", "label": "Вода", "color": "#1abc9c"},
    "tower": {"glyph": "▲", "label": "Вышка", "color": "#bdc3c7"},
    "collector": {"glyph": "◎", "label": "Коллекционер", "color": "#f1c40f"},
    "military": {"glyph": "✚", "label": "Военное", "color": "#7f8c8d"},
}

DEFAULT_POI_ICON = "star"


def normalize_poi_icon(icon: str | None) -> str:
    key = (icon or DEFAULT_POI_ICON).strip().lower()
    return key if key in POI_ICONS else DEFAULT_POI_ICON
