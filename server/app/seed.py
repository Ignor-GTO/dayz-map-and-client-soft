import logging

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import (
    DEFAULT_ADMIN_PASSWORD,
    MAP_EXTRA_ZOOM,
    MAP_MAX_NATIVE_ZOOM,
    MAP_SIZE,
    MAP_TILES_SATELLITE,
    MAP_TILES_TOPOGRAPHIC,
)
from app.locations_service import DEFAULT_IZURVIVE_URLS
from app.radiation_service import DEFAULT_RADIATION_FILES
from app.models import DayZMap, Setting
from app.settings_service import PUBLIC_PIN_CREATION_KEY

logger = logging.getLogger(__name__)

ADMIN_PASSWORD_KEY = "admin_password_hash"

DEFAULT_MAP_SLUG = "pripyat"
DEFAULT_MAP_NAME = "Припять (Pripyat Gamma)"


def hash_admin_password(password: str) -> str:
    import hashlib

    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_admin_password(password: str, stored_hash: str) -> bool:
    return hash_admin_password(password) == stored_hash


async def migrate_schema(conn) -> None:
    await conn.run_sync(_migrate_sqlite)


def _migrate_sqlite(conn) -> None:
    cols = {row[1] for row in conn.execute(text("PRAGMA table_info(rooms)")).fetchall()}
    if cols and "map_id" not in cols:
        conn.execute(text("ALTER TABLE rooms ADD COLUMN map_id INTEGER"))

    map_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(dayz_maps)")).fetchall()}
    if map_cols and "locations_url" not in map_cols:
        conn.execute(text("ALTER TABLE dayz_maps ADD COLUMN locations_url TEXT"))
    if map_cols and "locations_source" not in map_cols:
        conn.execute(text("ALTER TABLE dayz_maps ADD COLUMN locations_source VARCHAR(16)"))
    if map_cols and "radiation_url" not in map_cols:
        conn.execute(text("ALTER TABLE dayz_maps ADD COLUMN radiation_url TEXT"))

    poi_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(map_pois)")).fetchall()}
    if poi_cols and "icon" not in poi_cols:
        conn.execute(text("ALTER TABLE map_pois ADD COLUMN icon VARCHAR(32) DEFAULT 'star'"))
    if poi_cols and "description_image_url" not in poi_cols:
        conn.execute(text("ALTER TABLE map_pois ADD COLUMN description_image_url TEXT"))

    marker_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(markers)")).fetchall()}
    if marker_cols and "type" not in marker_cols:
        conn.execute(text("ALTER TABLE markers ADD COLUMN type VARCHAR(32) DEFAULT 'marker'"))


def default_map_kwargs() -> dict:
    return {
        "slug": DEFAULT_MAP_SLUG,
        "name": DEFAULT_MAP_NAME,
        "map_size": MAP_SIZE,
        "tiles_satellite": MAP_TILES_SATELLITE,
        "tiles_topographic": MAP_TILES_TOPOGRAPHIC,
        "max_native_zoom": MAP_MAX_NATIVE_ZOOM,
        "extra_zoom": MAP_EXTRA_ZOOM,
        "locations_url": DEFAULT_IZURVIVE_URLS.get(DEFAULT_MAP_SLUG),
        "locations_source": "izurvive",
        "radiation_url": DEFAULT_RADIATION_FILES.get(DEFAULT_MAP_SLUG),
        "enabled": True,
        "sort_order": 0,
    }


async def ensure_maps_seeded(db: AsyncSession) -> None:
    count = await db.scalar(select(func.count()).select_from(DayZMap)) or 0
    if count == 0:
        logger.warning("dayz_maps is empty — running seed_defaults")
        await seed_defaults(db)


async def seed_defaults(db: AsyncSession) -> None:
    result = await db.execute(select(DayZMap).where(DayZMap.slug == DEFAULT_MAP_SLUG))
    game_map = result.scalar_one_or_none()
    if game_map is None:
        db.add(DayZMap(**default_map_kwargs()))
        logger.info("Created default map: %s", DEFAULT_MAP_SLUG)
    else:
        if not game_map.locations_url:
            game_map.locations_url = DEFAULT_IZURVIVE_URLS.get(DEFAULT_MAP_SLUG)
            game_map.locations_source = "izurvive"
        if not game_map.radiation_url and DEFAULT_MAP_SLUG == game_map.slug:
            game_map.radiation_url = DEFAULT_RADIATION_FILES.get(DEFAULT_MAP_SLUG)

    setting = await db.get(Setting, ADMIN_PASSWORD_KEY)
    if setting is None:
        db.add(Setting(key=ADMIN_PASSWORD_KEY, value=hash_admin_password(DEFAULT_ADMIN_PASSWORD)))
        logger.info("Created default admin password setting")

    pin_setting = await db.get(Setting, PUBLIC_PIN_CREATION_KEY)
    if pin_setting is None:
        db.add(Setting(key=PUBLIC_PIN_CREATION_KEY, value="1"))
        logger.info("Created default public PIN creation setting")

    await db.commit()

    maps = await db.execute(select(DayZMap).order_by(DayZMap.sort_order, DayZMap.id))
    first_map = maps.scalars().first()
    if first_map:
        await db.execute(
            text("UPDATE rooms SET map_id = :mid WHERE map_id IS NULL"),
            {"mid": first_map.id},
        )
        await db.commit()
