"""Auth domain business logic.

Routers stay thin; the real work (querying users, verifying passwords) lives here.
This keeps endpoints readable and the logic testable in isolation.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_password_constant_time
from app.models.user import User


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
