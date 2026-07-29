"""Create a server ingest API key (prints plaintext once).

Usage (from server/):
  python -m app.create_server_api_key --map scum --name "SCUM prod"
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.auth import generate_server_api_key, hash_api_key
from app.database import SessionLocal, init_db
from app.models import DayZMap, Room, ServerApiKey
from app.seed import ensure_maps_seeded


async def main() -> None:
    parser = argparse.ArgumentParser(description="Create server API key for position ingest")
    parser.add_argument("--map", dest="map_slug", default="scum")
    parser.add_argument("--name", default="SCUM server")
    parser.add_argument("--room-id", type=int, default=None)
    parser.add_argument("--pin", default=None, help="Optional PIN to scope the key to a room")
    args = parser.parse_args()

    await init_db()
    async with SessionLocal() as db:
        await ensure_maps_seeded(db)
        result = await db.execute(
            select(DayZMap).where(DayZMap.slug == args.map_slug.strip().lower())
        )
        game_map = result.scalar_one_or_none()
        if not game_map:
            raise SystemExit(f"Map not found: {args.map_slug}")

        room = None
        if args.room_id is not None:
            room = await db.get(Room, args.room_id)
            if not room or room.map_id != game_map.id:
                raise SystemExit("room-id does not belong to map")
        elif args.pin:
            room_result = await db.execute(
                select(Room).where(Room.map_id == game_map.id, Room.pin == args.pin.strip())
            )
            room = room_result.scalar_one_or_none()
            if not room:
                raise SystemExit(f"PIN room not found: {args.pin}")

        plain = generate_server_api_key()
        row = ServerApiKey(
            name=args.name.strip() or "SCUM server",
            key_prefix=plain[:12],
            key_hash=hash_api_key(plain),
            map_id=game_map.id,
            room_id=room.id if room else None,
            enabled=True,
        )
        db.add(row)
        await db.commit()
        print("Created server API key (copy now, shown once):")
        print(plain)
        print(f"map={game_map.slug} room_id={row.room_id} id={row.id}")


if __name__ == "__main__":
    asyncio.run(main())
