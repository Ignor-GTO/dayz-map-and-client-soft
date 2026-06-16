import hashlib

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DEFAULT_ADMIN_PASSWORD, MAP_ATTRIBUTION
from app.models import DayZMap, Setting

ADMIN_PASSWORD_KEY = "admin_password_hash"


def hash_admin_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_admin_password(password: str, stored_hash: str) -> bool:
    return hash_admin_password(password) == stored_hash


async def migrate_schema(conn) -> None:
    await conn.run_sync(_migrate_sqlite)


def _migrate_sqlite(conn) -> None:
    cols = {row[1] for row in conn.execute(text("PRAGMA table_info(rooms)")).fetchall()}
    if cols and "map_id" not in cols:
        conn.execute(text("ALTER TABLE rooms ADD COLUMN map_id INTEGER"))
        default_map = conn.execute(text("SELECT id FROM dayz_maps ORDER BY id LIMIT 1")).fetchone()
        if default_map:
            conn.execute(text("UPDATE rooms SET map_id = :mid WHERE map_id IS NULL"), {"mid": default_map[0]})


async def seed_defaults(db: AsyncSession) -> None:
    result = await db.execute(select(DayZMap).limit(1))
    if result.scalar_one_or_none() is None:
        db.add(
            DayZMap(
                slug="pripyat",
                name="Припять (Pripyat Gamma)",
                map_size=20480,
                tiles_satellite="https://static.xam.nu/dayz/maps/pripyat/19.08/satellite/{z}/{x}/{y}.jpg",
                tiles_topographic="https://static.xam.nu/dayz/maps/pripyat/19.08/topographic/{z}/{x}/{y}.jpg",
                max_native_zoom=7,
                extra_zoom=3,
                enabled=True,
                sort_order=0,
            )
        )

    setting = await db.get(Setting, ADMIN_PASSWORD_KEY)
    if setting is None:
        db.add(Setting(key=ADMIN_PASSWORD_KEY, value=hash_admin_password(DEFAULT_ADMIN_PASSWORD)))

    await db.commit()

    # assign orphan rooms to first map
    maps = await db.execute(select(DayZMap).order_by(DayZMap.sort_order, DayZMap.id))
    first_map = maps.scalars().first()
    if first_map:
        await db.execute(
            text("UPDATE rooms SET map_id = :mid WHERE map_id IS NULL"),
            {"mid": first_map.id},
        )
        await db.commit()
