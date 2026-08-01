import hashlib
import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import SECRET_KEY, SESSION_COOKIE
from app.database import get_db
from app.models import AdminAccount, DayZMap, Room, ServerApiKey, User

serializer = URLSafeSerializer(SECRET_KEY, salt="dayz-map-session")
admin_serializer = URLSafeSerializer(SECRET_KEY, salt="dayz-map-admin")
ADMIN_SESSION_COOKIE = "dayz_map_admin"


def hash_client_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    return hash_password(password) == stored_hash


def generate_client_key() -> str:
    return secrets.token_urlsafe(32)


def generate_server_api_key() -> str:
    """Plaintext server ingest key (shown once). Prefix smk_ for easy recognition."""
    return "smk_" + secrets.token_urlsafe(32)


def hash_api_key(key: str) -> str:
    return hash_client_key(key.strip())


def channel_key(map_id: int, room_id: int) -> str:
    return f"map:{map_id}:room:{room_id}"


def set_session(response: Response, user_id: int, client_key: str | None = None) -> None:
    payload: dict[str, int | str] = {"user_id": user_id}
    if client_key:
        payload["client_key"] = client_key
    token = serializer.dumps(payload)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )


def read_session_client_key(request: Request) -> str | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        data = serializer.loads(token)
    except BadSignature:
        return None
    key = data.get("client_key")
    return key if isinstance(key, str) and key else None


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE)


def set_admin_session(response: Response, admin_id: int) -> None:
    token = admin_serializer.dumps({"admin_id": admin_id})
    response.set_cookie(
        key=ADMIN_SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7,
    )


def clear_admin_session(response: Response) -> None:
    response.delete_cookie(ADMIN_SESSION_COOKIE)


async def require_admin(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AdminAccount:
    token = request.cookies.get(ADMIN_SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Admin not authenticated")
    try:
        data = admin_serializer.loads(token)
        admin_id = data.get("admin_id")
        if not admin_id:
            raise HTTPException(status_code=401, detail="Invalid admin session")
    except BadSignature:
        raise HTTPException(status_code=401, detail="Invalid admin session")

    account = await db.get(AdminAccount, admin_id)
    if not account:
        raise HTTPException(status_code=401, detail="Admin account not found")
    return account


async def require_admin_role(
    account: Annotated[AdminAccount, Depends(require_admin)],
) -> AdminAccount:
    if account.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return account


async def get_optional_admin_account(
    request: Request,
    db: AsyncSession,
) -> AdminAccount | None:
    token = request.cookies.get(ADMIN_SESSION_COOKIE)
    if not token:
        return None
    try:
        data = admin_serializer.loads(token)
        admin_id = data.get("admin_id")
        if not admin_id:
            return None
    except BadSignature:
        return None
    return await db.get(AdminAccount, admin_id)


async def user_has_admin_panel_access(
    request: Request,
    db: AsyncSession,
    user: User,
) -> bool:
    if (user.role or "user") in {"admin", "moderator"}:
        return True
    if await get_optional_admin_account(request, db):
        return True
    nickname = user.nickname.strip().lower()
    if nickname:
        result = await db.execute(
            select(AdminAccount).where(func.lower(AdminAccount.login) == nickname)
        )
        if result.scalar_one_or_none():
            return True
    return False


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
        .options(
            selectinload(User.room).selectinload(Room.map),
            selectinload(User.account),
        )
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
        .options(
            selectinload(User.room).selectinload(Room.map),
            selectinload(User.account),
        )
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


async def get_server_api_key(
    db: AsyncSession,
    authorization: str | None,
    x_api_key: str | None = None,
) -> ServerApiKey:
    raw = None
    if authorization and authorization.startswith("Bearer "):
        raw = authorization.removeprefix("Bearer ").strip()
    elif x_api_key:
        raw = x_api_key.strip()
    if not raw:
        raise HTTPException(status_code=401, detail="Missing server API key")

    key_hash = hash_api_key(raw)
    result = await db.execute(
        select(ServerApiKey)
        .options(selectinload(ServerApiKey.map), selectinload(ServerApiKey.room))
        .where(ServerApiKey.key_hash == key_hash)
    )
    api_key = result.scalar_one_or_none()
    if not api_key or not api_key.enabled:
        raise HTTPException(status_code=401, detail="Invalid server API key")
    return api_key


async def authenticate_server_api_key(
    db: Annotated[AsyncSession, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-Api-Key")] = None,
) -> ServerApiKey:
    return await get_server_api_key(db, authorization, x_api_key)


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
        .options(
            selectinload(User.room).selectinload(Room.map),
            selectinload(User.account),
        )
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
