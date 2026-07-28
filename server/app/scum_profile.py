"""SCUM map profile: local tiles + coordinate metadata."""

SCUM_MAP_SLUG = "scum"
SCUM_MAP_NAME = "SCUM Island"

# Pixel space of mustard/scum-map tiles at max Leaflet zoom (16 * 1280).
# Mustard folders are named 2..6; Leaflet uses 0..4 with zoomOffset=2.
SCUM_MAP_PX = 20480
SCUM_TILE_SIZE = 1280
SCUM_MIN_ZOOM = 0
SCUM_MAX_ZOOM = 4
SCUM_ZOOM_OFFSET = 2

SCUM_TILES_URL = "/tiles/scum/{z}/{x}_{y}.webp"

# Approximate in-game centimetre bounds of the island.
SCUM_BOUNDS = {
    "min_x": -920000.0,
    "max_x": 640000.0,
    "min_y": -920000.0,
    "max_y": 640000.0,
}


def scum_map_kwargs() -> dict:
    return {
        "slug": SCUM_MAP_SLUG,
        "name": SCUM_MAP_NAME,
        # Stored for admin UI; frontend uses coord_system=scum for real math.
        "map_size": float(SCUM_MAP_PX),
        "tiles_satellite": SCUM_TILES_URL,
        "tiles_topographic": SCUM_TILES_URL,
        "max_native_zoom": SCUM_MAX_ZOOM,
        "extra_zoom": 0,
        "locations_url": None,
        "locations_source": None,
        "radiation_url": None,
        "enabled": True,
        "sort_order": 10,
    }


def is_scum_map(slug: str | None) -> bool:
    return (slug or "").strip().lower() == SCUM_MAP_SLUG
