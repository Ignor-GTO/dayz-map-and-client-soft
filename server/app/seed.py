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


def _migrate_rooms_pin_unique(conn) -> None:
    """Allow the same PIN on different maps (drop legacy UNIQUE(pin))."""
    tables = {
        row[0]
        for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }
    if "rooms" not in tables:
        return

    indexes = conn.execute(text("PRAGMA index_list(rooms)")).fetchall()
    pin_only_unique = []
    for idx in indexes:
        # PRAGMA index_list: (seq, name, unique, origin, partial)
        name = idx[1]
        is_unique = bool(idx[2])
        origin = idx[3] if len(idx) > 3 else "c"
        if not is_unique or not name:
            continue
        cols = [
            row[2]
            for row in conn.execute(text(f'PRAGMA index_info("{name}")')).fetchall()
        ]
        if cols == ["pin"]:
            pin_only_unique.append((name, origin))

    if not pin_only_unique:
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_map_pin ON rooms (map_id, pin)"))
        return

    # UNIQUE column constraints create sqlite_autoindex_* that cannot be DROP INDEX'd —
    # rebuild the table with composite uniqueness instead.
    logger.warning(
        "Rebuilding rooms table to replace legacy UNIQUE(pin) with UNIQUE(map_id, pin); indexes=%s",
        [n for n, _ in pin_only_unique],
    )
    cols = {row[1] for row in conn.execute(text("PRAGMA table_info(rooms)")).fetchall()}
    has_entry_pw = "entry_password_hash" in cols
    has_creator = "created_by_user_id" in cols
    has_users = "users" in tables
    creator_col = (
        "created_by_user_id INTEGER REFERENCES users(id)"
        if has_users
        else "created_by_user_id INTEGER"
    )

    conn.execute(text("PRAGMA foreign_keys=OFF"))
    conn.execute(text(
        "CREATE TABLE rooms_new ("
        "  id INTEGER PRIMARY KEY,"
        "  map_id INTEGER NOT NULL,"
        "  pin VARCHAR(16) NOT NULL,"
        "  entry_password_hash VARCHAR(128),"
        f"  {creator_col},"
        "  created_at DATETIME,"
        "  CONSTRAINT uq_map_pin UNIQUE (map_id, pin)"
        ")"
    ))

    select_entry = "entry_password_hash" if has_entry_pw else "NULL"
    select_creator = "created_by_user_id" if has_creator else "NULL"
    conn.execute(text(
        "INSERT INTO rooms_new (id, map_id, pin, entry_password_hash, created_by_user_id, created_at) "
        f"SELECT id, map_id, pin, {select_entry}, {select_creator}, created_at FROM rooms "
        "WHERE map_id IS NOT NULL"
    ))
    conn.execute(text("DROP TABLE rooms"))
    conn.execute(text("ALTER TABLE rooms_new RENAME TO rooms"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_rooms_map_id ON rooms (map_id)"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_rooms_pin ON rooms (pin)"))
    conn.execute(text("PRAGMA foreign_keys=ON"))
    logger.info("rooms table rebuilt with UNIQUE(map_id, pin)")


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
    if user_cols and "steam_id" not in user_cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN steam_id VARCHAR(32)"))
        logger.info("Added users.steam_id column")
        try:
            conn.execute(text("CREATE INDEX ix_users_steam_id ON users (steam_id)"))
        except Exception:
            pass

    pos_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(positions)")).fetchall()}
    if pos_cols and "travel_mode" not in pos_cols:
        conn.execute(text("ALTER TABLE positions ADD COLUMN travel_mode VARCHAR(16)"))
        logger.info("Added positions.travel_mode column")
    if pos_cols and "vehicle_role" not in pos_cols:
        conn.execute(text("ALTER TABLE positions ADD COLUMN vehicle_role VARCHAR(16)"))
        logger.info("Added positions.vehicle_role column")
    if pos_cols and "vehicle_type" not in pos_cols:
        conn.execute(text("ALTER TABLE positions ADD COLUMN vehicle_type VARCHAR(64)"))
        logger.info("Added positions.vehicle_type column")
    if pos_cols and "z" not in pos_cols:
        conn.execute(text("ALTER TABLE positions ADD COLUMN z FLOAT"))
        logger.info("Added positions.z column")
    if pos_cols and "yaw" not in pos_cols:
        conn.execute(text("ALTER TABLE positions ADD COLUMN yaw FLOAT"))
        logger.info("Added positions.yaw column")

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

    # Legacy DBs may still enforce UNIQUE(pin) globally. Same PIN must be allowed
    # on different maps (UniqueConstraint map_id+pin). Drop pin-only unique indexes.
    _migrate_rooms_pin_unique(conn)

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

    if "server_api_keys" not in road_tables:
        conn.execute(text(
            "CREATE TABLE server_api_keys ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  name VARCHAR(128) NOT NULL,"
            "  key_prefix VARCHAR(16) NOT NULL,"
            "  key_hash VARCHAR(128) NOT NULL UNIQUE,"
            "  map_id INTEGER NOT NULL REFERENCES dayz_maps(id),"
            "  room_id INTEGER REFERENCES rooms(id),"
            "  enabled BOOLEAN NOT NULL DEFAULT 1,"
            "  created_at DATETIME,"
            "  last_used_at DATETIME"
            ")"
        ))
        conn.execute(text("CREATE INDEX ix_server_api_keys_key_hash ON server_api_keys (key_hash)"))
        conn.execute(text("CREATE INDEX ix_server_api_keys_map_id ON server_api_keys (map_id)"))
        conn.execute(text("CREATE INDEX ix_server_api_keys_room_id ON server_api_keys (room_id)"))
        logger.info("Created server_api_keys table")

    if "map_deaths" not in road_tables:
        conn.execute(text(
            "CREATE TABLE map_deaths ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  map_id INTEGER NOT NULL REFERENCES dayz_maps(id),"
            "  room_id INTEGER REFERENCES rooms(id),"
            "  steam_id VARCHAR(32),"
            "  nickname VARCHAR(64) NOT NULL,"
            "  profile_id INTEGER,"
            "  x FLOAT NOT NULL,"
            "  y FLOAT NOT NULL,"
            "  z FLOAT,"
            "  died_at DATETIME,"
            "  created_at DATETIME"
            ")"
        ))
        conn.execute(text("CREATE INDEX ix_map_deaths_map_id ON map_deaths (map_id)"))
        conn.execute(text("CREATE INDEX ix_map_deaths_room_id ON map_deaths (room_id)"))
        conn.execute(text("CREATE INDEX ix_map_deaths_steam_id ON map_deaths (steam_id)"))
        conn.execute(text("CREATE INDEX ix_map_deaths_profile_id ON map_deaths (profile_id)"))
        conn.execute(text("CREATE INDEX ix_map_deaths_died_at ON map_deaths (died_at)"))
        logger.info("Created map_deaths table")

    _migrate_unified_accounts(conn)


def _migrate_unified_accounts(conn) -> None:
    """Create accounts table and backfill users.account_id without dropping any rows."""
    tables = {
        row[0]
        for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
    }
    if "users" not in tables:
        return

    if "accounts" not in tables:
        conn.execute(text(
            "CREATE TABLE accounts ("
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  display_name VARCHAR(64) NOT NULL,"
            "  steam_id VARCHAR(32),"
            "  profile_password_hash VARCHAR(128),"
            "  avatar_url TEXT,"
            "  created_at DATETIME"
            ")"
        ))
        conn.execute(text("CREATE INDEX ix_accounts_steam_id ON accounts (steam_id)"))
        logger.info("Created accounts table")

    user_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()}
    if "account_id" not in user_cols:
        conn.execute(text("ALTER TABLE users ADD COLUMN account_id INTEGER REFERENCES accounts(id)"))
        logger.info("Added users.account_id column")
        try:
            conn.execute(text("CREATE INDEX ix_users_account_id ON users (account_id)"))
        except Exception:
            pass

    # 1:1 account for every membership that still lacks one (no data loss).
    orphans = conn.execute(text(
        "SELECT id, nickname, steam_id, profile_password_hash, avatar_url, created_at "
        "FROM users WHERE account_id IS NULL"
    )).fetchall()
    for row in orphans:
        user_id, nickname, steam_id, pw_hash, avatar_url, created_at = row
        conn.execute(
            text(
                "INSERT INTO accounts (display_name, steam_id, profile_password_hash, avatar_url, created_at) "
                "VALUES (:display_name, :steam_id, :profile_password_hash, :avatar_url, :created_at)"
            ),
            {
                "display_name": nickname or f"user-{user_id}",
                "steam_id": steam_id,
                "profile_password_hash": pw_hash,
                "avatar_url": avatar_url,
                "created_at": created_at,
            },
        )
        account_id = conn.execute(text("SELECT last_insert_rowid()")).scalar()
        conn.execute(
            text("UPDATE users SET account_id = :account_id WHERE id = :user_id"),
            {"account_id": account_id, "user_id": user_id},
        )
    if orphans:
        logger.info("Backfilled accounts for %s user memberships", len(orphans))

    # Safe merge: same non-null steam_id → one account (keep lowest account id).
    steam_groups = conn.execute(text(
        "SELECT steam_id, MIN(account_id) AS keep_id, GROUP_CONCAT(DISTINCT account_id) AS ids "
        "FROM users "
        "WHERE steam_id IS NOT NULL AND steam_id != '' AND account_id IS NOT NULL "
        "GROUP BY steam_id "
        "HAVING COUNT(DISTINCT account_id) > 1"
    )).fetchall()
    merged_accounts = 0
    for steam_id, keep_id, ids_csv in steam_groups:
        ids = [int(x) for x in str(ids_csv).split(",") if x]
        for old_id in ids:
            if old_id == keep_id:
                continue
            # Prefer non-null profile fields onto keep account.
            conn.execute(text(
                "UPDATE accounts SET "
                "  avatar_url = COALESCE(accounts.avatar_url, (SELECT avatar_url FROM accounts WHERE id = :old_id)), "
                "  profile_password_hash = COALESCE(accounts.profile_password_hash, "
                "    (SELECT profile_password_hash FROM accounts WHERE id = :old_id)), "
                "  display_name = COALESCE(NULLIF(accounts.display_name, ''), "
                "    (SELECT display_name FROM accounts WHERE id = :old_id)) "
                "WHERE id = :keep_id"
            ), {"old_id": old_id, "keep_id": keep_id})
            conn.execute(
                text("UPDATE users SET account_id = :keep_id WHERE account_id = :old_id"),
                {"keep_id": keep_id, "old_id": old_id},
            )
            conn.execute(text("DELETE FROM accounts WHERE id = :old_id"), {"old_id": old_id})
            merged_accounts += 1
    if merged_accounts:
        logger.info("Merged %s duplicate accounts by steam_id", merged_accounts)

    # Sync denormalized user fields from account (canonical).
    conn.execute(text(
        "UPDATE users SET "
        "  avatar_url = (SELECT avatar_url FROM accounts WHERE accounts.id = users.account_id), "
        "  profile_password_hash = (SELECT profile_password_hash FROM accounts WHERE accounts.id = users.account_id), "
        "  steam_id = COALESCE("
        "    (SELECT steam_id FROM accounts WHERE accounts.id = users.account_id), "
        "    users.steam_id"
        "  ) "
        "WHERE account_id IS NOT NULL"
    ))


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
    for key in ("tiles_satellite", "tiles_topographic", "max_native_zoom", "extra_zoom", "map_size", "name", "locations_source"):
        desired = kwargs[key]
        if getattr(game_map, key) != desired:
            setattr(game_map, key, desired)
            changed = True
    if game_map.locations_url:
        game_map.locations_url = None
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
