"""Database engine, session factory and the FastAPI session dependency.

Uses SQLAlchemy 2.0 in async mode (asyncpg driver). The engine is created lazily:
no connection is opened until the first query, so importing this module never
touches Postgres.

Django equivalent: the ORM configuration that `models.py` relies on.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

# echo logs every statement WITH bound parameters (emails, password hashes). Gate it to
# dev so a stray SQL_ECHO=true in another environment cannot leak PII to stdout/logs.
_echo = settings.sql_echo and settings.app_env == "dev"

engine = create_async_engine(settings.database_url, echo=_echo, future=True)

SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base. Every model inherits from this; Alembic reads its metadata."""


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields a session and always closes it.

    Use it in routes with `Depends(get_session)` (see `app/api/deps.py`).
    """
    async with SessionFactory() as session:
        yield session
