import hashlib
import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import SECRET_KEY, SESSION_COOKIE
from app.database import get_db
from app.models import DayZMap, Room, User

serializer = URLSafeSerializer(SECRET_KEY, salt="dayz-map-session")
admin_serializer = URLSafeSerializer(SECRET_KEY, salt="dayz-map-admin")
ADMIN_SESSION_COOKIE = "dayz_map_admin"


def hash_client_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_client_key() -> str:
    return secrets.token_urlsafe(32)


def channel_key(map_id: int, room_id: int) -> str:
    return f"map:{map_id}:room:{room_id}"


def set_session(response: Response, user_id: int) -> None:
    token = serializer.dumps({"user_id": user_id})
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE)


def set_admin_session(response: Response) -> None:
    token = admin_serializer.dumps({"admin": True})
    response.set_cookie(
        key=ADMIN_SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7,
    )


def clear_admin_session(response: Response) -> None:
    response.delete_cookie(ADMIN_SESSION_COOKIE)


async def require_admin(request: Request) -> None:
    token = request.cookies.get(ADMIN_SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Admin not authenticated")
    try:
        data = admin_serializer.loads(token)
        if not data.get("admin"):
            raise HTTPException(status_code=401, detail="Invalid admin session")
    except BadSignature:
        raise HTTPException(status_code=401, detail="Invalid admin session")


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        data = serializer.loads(token)
        user_id = data["user_id"]
    except (BadSignature, KeyError):
        raise HTTPException(status_code=401, detail="Invalid session")

    result = await db.execute(
        select(User)
        .options(selectinload(User.room).selectinload(Room.map))
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def get_user_by_client_key(
    db: AsyncSession,
    authorization: str | None,
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing client key")
    key = authorization.removeprefix("Bearer ").strip()
    if not key:
        raise HTTPException(status_code=401, detail="Missing client key")

    key_hash = hash_client_key(key)
    result = await db.execute(
        select(User)
        .options(selectinload(User.room).selectinload(Room.map))
        .where(User.client_key_hash == key_hash)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid client key")
    return user


async def authenticate_client(
    db: Annotated[AsyncSession, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    return await get_user_by_client_key(db, authorization)


async def get_current_user_from_ws(db: AsyncSession, token: str | None) -> User | None:
    if not token:
        return None
    try:
        data = serializer.loads(token)
        user_id = data["user_id"]
    except (BadSignature, KeyError):
        return None

    result = await db.execute(
        select(User)
        .options(selectinload(User.room).selectinload(Room.map))
        .where(User.id == user_id)
    )
    return result.scalar_one_or_none()


async def get_map_by_slug(db: AsyncSession, slug: str, *, require_enabled: bool = True) -> DayZMap:
    from app.seed import ensure_maps_seeded

    await ensure_maps_seeded(db)
    query = select(DayZMap).where(DayZMap.slug == slug.strip().lower())
    if require_enabled:
        query = query.where(DayZMap.enabled.is_(True))
    result = await db.execute(query)
    game_map = result.scalar_one_or_none()
    if not game_map:
        raise HTTPException(status_code=404, detail="Map not found")
    return game_map


async def get_or_create_room(db: AsyncSession, map_id: int, pin: str) -> Room:
    result = await db.execute(select(Room).where(Room.map_id == map_id, Room.pin == pin))
    room = result.scalar_one_or_none()
    if room:
        return room
    room = Room(map_id=map_id, pin=pin)
    db.add(room)
    await db.flush()
    return room
