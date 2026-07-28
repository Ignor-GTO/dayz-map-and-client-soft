import logging

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import (
    DEFAULT_ADMIN_PASSWORD,
    EXTRA_ADMIN_LOGINS,
    MAP_EXTRA_ZOOM,
    MAP_MAX_NATIVE_ZOOM,
    MAP_SIZE,
    MAP_TILES_SATELLITE,
    MAP_TILES_TOPOGRAPHIC,
)
from app.locations_service import DEFAULT_IZURVIVE_URLS
from app.radiation_service import DEFAULT_RADIATION_FILES
from app.models import AdminAccount, DayZMap, Setting
from app.scum_profile import SCUM_MAP_SLUG, scum_map_kwargs
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
    if marker_cols and "marker_category" not in marker_cols:
        conn.execute(text("ALTER TABLE markers ADD COLUMN marker_category VARCHAR(16) DEFAULT 'group'"))
    if marker_cols and "title" not in marker_cols:
        conn.execute(text("ALTER TABLE markers ADD COLUMN title VARCHAR(128)"))
    if marker_cols and "description" not in marker_cols:
        conn.execute(text("ALTER TABLE markers ADD COLUMN description TEXT"))
    if marker_cols and "image_url" not in marker_cols:
        conn.execute(text("ALTER TABLE markers ADD COLUMN image_url TEXT"))
    if marker_cols and "geometry_kind" not in marker_cols:
        conn.execute(text("ALTER TABLE markers ADD COLUMN geometry_kind VARCHAR(16) DEFAULT 'point'"))
    if marker_cols and "points_json" not in marker_cols:
        conn.execute(text("ALTER TABLE markers ADD COLUMN points_json TEXT"))
    if marker_cols and "radius" not in marker_cols:
        conn.execute(text("ALTER TABLE markers ADD COLUMN radius FLOAT"))
    if marker_cols and "stroke_color" not in marker_cols:
        conn.execute(text("ALTER TABLE markers ADD COLUMN stroke_color VARCHAR(16)"))
    if marker_cols and "fill_color" not in marker_cols:
        conn.execute(text("ALTER TABLE markers ADD COLUMN fill_color VARCHAR(16)"))
    if marker_cols and "map_id" not in marker_cols:
        conn.execute(text("ALTER TABLE markers ADD COLUMN map_id INTEGER REFERENCES dayz_maps(id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_markers_map_id ON markers (map_id)"))
        logger.info("Added markers.map_id column")
    if marker_cols:
        conn.execute(text(
            "UPDATE markers SET map_id = ("
            "  SELECT rooms.map_id FROM users "
            "  INNER JOIN rooms ON users.room_id = rooms.id "
            "  WHERE users.id = markers.user_id"
            ") WHERE marker_category = 'stash' AND map_id IS NULL"
        ))

    # road_segments table (created by SQLAlchemy create_all but add for existing DBs)
    road_tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}
    if "road_segments" not in road_tables:
        conn.execute(text(
            "CREATE TABLE road_segments ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  map_id INTEGER NOT NULL REFERENCES dayz_maps(id),"
            "  road_type VARCHAR(32) NOT NULL DEFAULT 'road',"
            "  points TEXT NOT NULL,"
            "  created_at DATETIME"
            ")"
        ))
        conn.execute(text("CREATE INDEX ix_road_segments_map_id ON road_segments (map_id)"))
        logger.info("Created road_segments table")

    if "map_buildings" not in road_tables:
        conn.execute(text(
            "CREATE TABLE map_buildings ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  map_id INTEGER NOT NULL REFERENCES dayz_maps(id),"
            "  title VARCHAR(128) NOT NULL,"
            "  classname VARCHAR(128),"
            "  description TEXT DEFAULT '',"
            "  building_type VARCHAR(32) NOT NULL DEFAULT 'structure',"
            "  x FLOAT NOT NULL,"
            "  y FLOAT NOT NULL,"
            "  width FLOAT NOT NULL DEFAULT 20,"
            "  depth FLOAT NOT NULL DEFAULT 15,"
            "  yaw FLOAT NOT NULL DEFAULT 0,"
            "  stroke_color VARCHAR(16),"
            "  fill_color VARCHAR(16),"
            "  enabled BOOLEAN NOT NULL DEFAULT 1,"
            "  created_at DATETIME"
            ")"
        ))
        conn.execute(text("CREATE INDEX ix_map_buildings_map_id ON map_buildings (map_id)"))
        logger.info("Created map_buildings table")

    if "traders" not in road_tables:
        conn.execute(text(
            "CREATE TABLE traders ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  map_id INTEGER NOT NULL REFERENCES dayz_maps(id),"
            "  name VARCHAR(128) NOT NULL,"
            "  x FLOAT,"
            "  y FLOAT,"
            "  poi_id INTEGER REFERENCES map_pois(id),"
            "  created_at DATETIME,"
            "  CONSTRAINT uq_trader_map_name UNIQUE (map_id, name)"
            ")"
        ))
        conn.execute(text("CREATE INDEX ix_traders_map_id ON traders (map_id)"))
        conn.execute(text("CREATE INDEX ix_traders_name ON traders (name)"))
        logger.info("Created traders table")
    else:
        trader_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(traders)")).fetchall()}
        if trader_cols and "x" not in trader_cols:
            conn.execute(text("ALTER TABLE traders ADD COLUMN x FLOAT"))
        if trader_cols and "y" not in trader_cols:
            conn.execute(text("ALTER TABLE traders ADD COLUMN y FLOAT"))
        if trader_cols and "poi_id" not in trader_cols:
            conn.execute(text("ALTER TABLE traders ADD COLUMN poi_id INTEGER REFERENCES map_pois(id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_traders_poi_id ON traders (poi_id)"))

    if "trader_sections" not in road_tables:
        conn.execute(text(
            "CREATE TABLE trader_sections ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  trader_id INTEGER NOT NULL REFERENCES traders(id),"
            "  name VARCHAR(128) NOT NULL,"
            "  created_at DATETIME,"
            "  CONSTRAINT uq_trader_section_name UNIQUE (trader_id, name)"
            ")"
        ))
        conn.execute(text("CREATE INDEX ix_trader_sections_trader_id ON trader_sections (trader_id)"))
        conn.execute(text("CREATE INDEX ix_trader_sections_name ON trader_sections (name)"))
        logger.info("Created trader_sections table")

    if "trader_subsections" not in road_tables:
        conn.execute(text(
            "CREATE TABLE trader_subsections ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  section_id INTEGER NOT NULL REFERENCES trader_sections(id),"
            "  name VARCHAR(128) NOT NULL,"
            "  created_at DATETIME,"
            "  CONSTRAINT uq_trader_subsection_name UNIQUE (section_id, name)"
            ")"
        ))
        conn.execute(text("CREATE INDEX ix_trader_subsections_section_id ON trader_subsections (section_id)"))
        conn.execute(text("CREATE INDEX ix_trader_subsections_name ON trader_subsections (name)"))
        logger.info("Created trader_subsections table")

    if "trader_items" not in road_tables:
        conn.execute(text(
            "CREATE TABLE trader_items ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  subsection_id INTEGER NOT NULL REFERENCES trader_subsections(id),"
            "  name VARCHAR(160) NOT NULL,"
            "  buy_price INTEGER NOT NULL DEFAULT 0,"
            "  sell_price INTEGER NOT NULL DEFAULT 0,"
            "  created_at DATETIME,"
            "  CONSTRAINT uq_trader_item_name UNIQUE (subsection_id, name)"
            ")"
        ))
        conn.execute(text("CREATE INDEX ix_trader_items_subsection_id ON trader_items (subsection_id)"))
        conn.execute(text("CREATE INDEX ix_trader_items_name ON trader_items (name COLLATE NOCASE)"))
        logger.info("Created trader_items table")

    user_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()}
    if user_cols and "role" not in user_cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(16) DEFAULT 'user'"))
        logger.info("Added users.role column")
    if user_cols and "profile_password_hash" not in user_cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN profile_password_hash VARCHAR(128)"))
        logger.info("Added users.profile_password_hash column")
    if user_cols and "avatar_url" not in user_cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN avatar_url TEXT"))
        logger.info("Added users.avatar_url column")

    room_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(rooms)")).fetchall()}
    if room_cols and "entry_password_hash" not in room_cols:
        conn.execute(text("ALTER TABLE rooms ADD COLUMN entry_password_hash VARCHAR(128)"))
        logger.info("Added rooms.entry_password_hash column")
    if room_cols and "created_by_user_id" not in room_cols:
        conn.execute(text("ALTER TABLE rooms ADD COLUMN created_by_user_id INTEGER REFERENCES users(id)"))
        logger.info("Added rooms.created_by_user_id column")
        conn.execute(text(
            "UPDATE rooms SET created_by_user_id = ("
            "  SELECT MIN(u.id) FROM users u WHERE u.room_id = rooms.id"
            ") WHERE created_by_user_id IS NULL AND EXISTS ("
            "  SELECT 1 FROM users u2 WHERE u2.room_id = rooms.id"
            ")"
        ))

    if "admin_accounts" not in road_tables:
        conn.execute(text(
            "CREATE TABLE admin_accounts ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  login VARCHAR(64) NOT NULL UNIQUE,"
            "  password_hash VARCHAR(128) NOT NULL,"
            "  role VARCHAR(16) NOT NULL DEFAULT 'admin',"
            "  created_at DATETIME"
            ")"
        ))
        conn.execute(text("CREATE INDEX ix_admin_accounts_login ON admin_accounts (login)"))
        logger.info("Created admin_accounts table")



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


async def _ensure_admin_login_aliases(db: AsyncSession) -> None:
    if not EXTRA_ADMIN_LOGINS:
        return
    rows = (await db.execute(select(AdminAccount).order_by(AdminAccount.id))).scalars().all()
    if not rows:
        return
    source = next((row for row in rows if row.login == "admin"), rows[0])
    created = False
    for login in EXTRA_ADMIN_LOGINS:
        if login == source.login:
            continue
        exists = await db.execute(select(AdminAccount).where(AdminAccount.login == login))
        if exists.scalar_one_or_none():
            continue
        db.add(AdminAccount(login=login, password_hash=source.password_hash, role=source.role))
        logger.info("Created admin login alias: %s", login)
        created = True
    if created:
        await db.commit()


async def ensure_maps_seeded(db: AsyncSession) -> None:
    count = await db.scalar(select(func.count()).select_from(DayZMap)) or 0
    if count == 0:
        logger.warning("dayz_maps is empty — running seed_defaults")
        await seed_defaults(db)
    else:
        await _ensure_admin_login_aliases(db)
    await ensure_scum_map_seeded(db)


async def ensure_scum_map_seeded(db: AsyncSession) -> None:
    result = await db.execute(select(DayZMap).where(DayZMap.slug == SCUM_MAP_SLUG))
    game_map = result.scalar_one_or_none()
    kwargs = scum_map_kwargs()
    if game_map is None:
        db.add(DayZMap(**kwargs))
        await db.commit()
        logger.info("Created SCUM map: %s", SCUM_MAP_SLUG)
        return

    changed = False
    for key in ("tiles_satellite", "tiles_topographic", "max_native_zoom", "extra_zoom", "map_size", "name"):
        desired = kwargs[key]
        if getattr(game_map, key) != desired:
            setattr(game_map, key, desired)
            changed = True
    if not game_map.enabled:
        game_map.enabled = True
        changed = True
    if changed:
        await db.commit()
        logger.info("Updated SCUM map tile config: %s", SCUM_MAP_SLUG)


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

    scum = await db.execute(select(DayZMap).where(DayZMap.slug == SCUM_MAP_SLUG))
    if scum.scalar_one_or_none() is None:
        db.add(DayZMap(**scum_map_kwargs()))
        logger.info("Created SCUM map: %s", SCUM_MAP_SLUG)

    setting = await db.get(Setting, ADMIN_PASSWORD_KEY)
    if setting is None:
        db.add(Setting(key=ADMIN_PASSWORD_KEY, value=hash_admin_password(DEFAULT_ADMIN_PASSWORD)))
        logger.info("Created default admin password setting")

    admin_count = await db.scalar(select(func.count()).select_from(AdminAccount)) or 0
    if admin_count == 0:
        legacy = await db.get(Setting, ADMIN_PASSWORD_KEY)
        password_hash = legacy.value if legacy else hash_admin_password(DEFAULT_ADMIN_PASSWORD)
        db.add(AdminAccount(login="admin", password_hash=password_hash, role="admin"))
        logger.info("Created default admin account (login: admin)")
        await db.flush()

    await _ensure_admin_login_aliases(db)

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
