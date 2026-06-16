"""Auth domain business logic.

Routers stay thin; the real work (querying users, verifying passwords) lives here.
This keeps endpoints readable and the logic testable in isolation.
"""

import datetime as dt
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import (
    generate_refresh_token,
    hash_refresh_token,
    verify_password_constant_time,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User

settings = get_settings()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    # Match on the canonical (lowercased) email so callers that did not normalize
    # still resolve the right user; emails are stored lowercased at creation.
    result = await session.execute(select(User).where(User.email == email.strip().lower()))
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def authenticate_user(session: AsyncSession, email: str, password: str) -> User | None:
    """Return the user if credentials are valid and the account is active, else None.

    Password verification runs even when the user does not exist (constant-time), so
    response timing cannot be used to enumerate valid accounts.
    """
    user = await get_user_by_email(session, email)
    password_hash = user.password_hash if user is not None and user.is_active else None
    if not verify_password_constant_time(password, password_hash):
        return None
    return user


async def issue_refresh_token(session: AsyncSession, user_id: uuid.UUID) -> str:
    """Create a refresh token for a user, persist its hash, and return the raw token
    (the only time the raw value exists outside the client)."""
    raw_token = generate_refresh_token()
    expires_at = dt.datetime.now(dt.UTC) + dt.timedelta(
        minutes=settings.refresh_token_expire_minutes
    )
    session.add(
        RefreshToken(
            user_id=user_id,
            token_hash=hash_refresh_token(raw_token),
            expires_at=expires_at,
        )
    )
    await session.commit()
    return raw_token


async def rotate_refresh_token(
    session: AsyncSession, raw_token: str
) -> tuple[User, str] | None:
    """Exchange a valid refresh token for a new (access-eligible user, new refresh token)
    pair, single-use: the presented token is revoked and a fresh one issued.

    Returns None when the token is unknown, expired, or belongs to an inactive user.
    If an ALREADY-REVOKED token is replayed, every token for that user is revoked — a
    revoked token reaching us means it was either stolen or the client is buggy; either
    way the safe move is to force a fresh login.
    """
    record = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token))
    )
    if record is None:
        return None

    now = dt.datetime.now(dt.UTC)
    if record.revoked_at is not None:
        await revoke_all_for_user(session, record.user_id)
        return None
    # Postgres returns tz-aware datetimes; SQLite (tests) drops tzinfo on round-trip. The
    # stored value is always UTC, so treat a naive value as UTC to compare safely on both.
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=dt.UTC)
    if expires_at <= now:
        return None

    user = await get_user_by_id(session, record.user_id)
    if user is None or not user.is_active:
        record.revoked_at = now
        await session.commit()
        return None

    record.revoked_at = now
    new_raw_token = generate_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(new_raw_token),
            expires_at=now + dt.timedelta(minutes=settings.refresh_token_expire_minutes),
        )
    )
    await session.commit()
    return user, new_raw_token


async def revoke_refresh_token(session: AsyncSession, raw_token: str) -> None:
    """Revoke a single refresh token (logout). No-op if it is unknown or already revoked."""
    record = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw_token))
    )
    if record is not None and record.revoked_at is None:
        record.revoked_at = dt.datetime.now(dt.UTC)
        await session.commit()


async def revoke_all_for_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Revoke every still-active refresh token for a user (theft response / global logout)."""
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=dt.datetime.now(dt.UTC))
    )
    await session.commit()
