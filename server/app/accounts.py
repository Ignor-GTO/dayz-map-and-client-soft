"""Unified Account helpers — one profile across maps/rooms, no data loss."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import verify_password
from app.models import Account, DayZMap, Room, User


def profile_password_hash_of(user: User) -> str | None:
    if user.account and user.account.profile_password_hash:
        return user.account.profile_password_hash
    return user.profile_password_hash


def avatar_url_of(user: User) -> str | None:
    if user.account and user.account.avatar_url:
        return user.account.avatar_url
    return user.avatar_url


def steam_id_of(user: User) -> str | None:
    if user.account and user.account.steam_id:
        return user.account.steam_id
    return user.steam_id


def verify_user_profile_password(user: User, profile_password: str | None) -> bool:
    stored = profile_password_hash_of(user)
    if not stored:
        return True
    if not profile_password:
        return False
    return verify_password(profile_password, stored)


def sync_membership_profile_fields(user: User, account: Account) -> None:
    """Keep denormalized user fields in sync for ingest / room broadcasts."""
    user.account_id = account.id
    user.avatar_url = account.avatar_url
    user.profile_password_hash = account.profile_password_hash
    user.steam_id = account.steam_id


async def sync_all_memberships(db: AsyncSession, account: Account) -> list[User]:
    result = await db.execute(select(User).where(User.account_id == account.id))
    members = list(result.scalars().all())
    for member in members:
        sync_membership_profile_fields(member, account)
    return members


async def delete_orphan_accounts(db: AsyncSession, account_ids: set[int]) -> None:
    for account_id in account_ids:
        if not account_id:
            continue
        remaining = await db.execute(
            select(User.id).where(User.account_id == account_id).limit(1)
        )
        if remaining.scalar_one_or_none() is not None:
            continue
        account = await db.get(Account, account_id)
        if account:
            await db.delete(account)


async def _account_nicks(db: AsyncSession, account_id: int) -> set[str]:
    result = await db.execute(select(User.nickname).where(User.account_id == account_id))
    return {str(n).strip().lower() for n in result.scalars().all() if n}


def _absorb_account_fields(target: Account, donor: Account | None) -> None:
    if not donor or donor.id == target.id:
        return
    if not target.avatar_url and donor.avatar_url:
        target.avatar_url = donor.avatar_url
    if not target.steam_id and donor.steam_id:
        target.steam_id = donor.steam_id
    if not target.profile_password_hash and donor.profile_password_hash:
        target.profile_password_hash = donor.profile_password_hash
    if (not target.display_name or not target.display_name.strip()) and donor.display_name:
        target.display_name = donor.display_name


async def adopt_matching_memberships(db: AsyncSession, account: Account) -> int:
    """
    Attach other room memberships that belong to this identity.

    Safe rules:
    - same steam_id
    - same nickname + same password hash
    - same nickname + sibling account has no profile password
      (passworded / richer account claims unprotected twin on another map)
    """
    moved = 0
    old_account_ids: set[int] = set()
    my_nicks = await _account_nicks(db, account.id)
    if account.display_name:
        my_nicks.add(account.display_name.strip().lower())

    async def _take(user: User) -> None:
        nonlocal moved
        if user.account_id and user.account_id != account.id:
            old_account_ids.add(user.account_id)
            old = await db.get(Account, user.account_id)
            _absorb_account_fields(account, old)
        sync_membership_profile_fields(user, account)
        moved += 1

    if account.steam_id:
        result = await db.execute(
            select(User)
            .options(selectinload(User.account))
            .where(
                User.steam_id == account.steam_id,
                (User.account_id.is_(None)) | (User.account_id != account.id),
            )
        )
        for user in result.scalars().all():
            await _take(user)

    if account.profile_password_hash:
        result = await db.execute(
            select(User)
            .options(selectinload(User.account))
            .where(
                User.profile_password_hash == account.profile_password_hash,
                (User.account_id.is_(None)) | (User.account_id != account.id),
            )
        )
        for user in result.scalars().all():
            nick = user.nickname.strip().lower()
            if nick not in my_nicks:
                continue
            await _take(user)

    # Claim unprotected same-nick memberships on other maps/rooms.
    if my_nicks:
        result = await db.execute(
            select(User)
            .options(selectinload(User.account))
            .where(
                func.lower(User.nickname).in_(my_nicks),
                (User.account_id.is_(None)) | (User.account_id != account.id),
            )
        )
        for user in result.scalars().all():
            other = user.account
            other_pw = other.profile_password_hash if other else user.profile_password_hash
            other_steam = other.steam_id if other else user.steam_id

            # Protected sibling: only if our password matches (already handled above)
            # or sibling has no password.
            if other_pw:
                if not account.profile_password_hash:
                    continue
                if other_pw != account.profile_password_hash:
                    continue
            if other_steam and account.steam_id and other_steam != account.steam_id:
                continue
            await _take(user)

    if old_account_ids or moved:
        await sync_all_memberships(db, account)
        if old_account_ids:
            await delete_orphan_accounts(db, old_account_ids)

    return moved


async def ensure_user_account(db: AsyncSession, user: User) -> Account:
    if user.account_id:
        account = user.account or await db.get(Account, user.account_id)
        if account:
            # Heal split state: avatar on membership but missing on account.
            if user.avatar_url and not account.avatar_url:
                account.avatar_url = user.avatar_url
            if user.steam_id and not account.steam_id:
                account.steam_id = user.steam_id
            if user.profile_password_hash and not account.profile_password_hash:
                account.profile_password_hash = user.profile_password_hash
            sync_membership_profile_fields(user, account)
            return account

    account = Account(
        display_name=user.nickname,
        steam_id=user.steam_id,
        profile_password_hash=user.profile_password_hash,
        avatar_url=user.avatar_url,
    )
    db.add(account)
    await db.flush()
    sync_membership_profile_fields(user, account)
    user.account = account
    return account


async def find_account_for_new_membership(
    db: AsyncSession,
    *,
    nickname: str,
    profile_password: str | None,
    steam_id: str | None = None,
) -> Account | None:
    """Reuse an existing global account when credentials uniquely match."""
    sid = (steam_id or "").strip() or None
    if sid:
        result = await db.execute(select(Account).where(Account.steam_id == sid).limit(1))
        account = result.scalar_one_or_none()
        if account:
            return account

    password = (profile_password or "").strip() or None
    if not password:
        return None

    nick = nickname.strip()
    result = await db.execute(
        select(Account)
        .join(User, User.account_id == Account.id)
        .where(
            func.lower(User.nickname) == nick.lower(),
            Account.profile_password_hash.is_not(None),
        )
        .distinct()
    )
    candidates = list(result.scalars().all())
    matches = [
        acc
        for acc in candidates
        if acc.profile_password_hash and verify_password(password, acc.profile_password_hash)
    ]
    if len(matches) == 1:
        return matches[0]
    return None


async def create_account_for_user(
    db: AsyncSession,
    *,
    nickname: str,
    profile_password_hash: str | None = None,
    steam_id: str | None = None,
    avatar_url: str | None = None,
) -> Account:
    account = Account(
        display_name=nickname.strip(),
        steam_id=steam_id,
        profile_password_hash=profile_password_hash,
        avatar_url=avatar_url,
    )
    db.add(account)
    await db.flush()
    return account


async def list_memberships_for_account(
    db: AsyncSession,
    account_id: int,
    *,
    current_user_id: int,
) -> list[dict]:
    result = await db.execute(
        select(User)
        .options(selectinload(User.room).selectinload(Room.map))
        .where(User.account_id == account_id)
        .order_by(User.id)
    )
    rows = []
    for member in result.scalars().all():
        game_map: DayZMap = member.room.map
        rows.append(
            {
                "user_id": member.id,
                "nickname": member.nickname,
                "pin": member.room.pin,
                "map_slug": game_map.slug,
                "map_name": game_map.name,
                "role": member.role or "user",
                "is_current": member.id == current_user_id,
            }
        )
    return rows


async def broadcast_avatar_to_memberships(manager, members: list[User], avatar_url: str | None) -> None:
    from app.auth import channel_key

    for member in members:
        room = member.room
        if room is None:
            continue
        await manager.broadcast(
            channel_key(room.map_id, member.room_id),
            {
                "type": "user_profile",
                "data": {"user_id": member.id, "avatar_url": avatar_url},
            },
        )
