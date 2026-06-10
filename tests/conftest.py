"""Test fixtures.

Tests run against an in-memory SQLite database (via dependency override), so they
need neither Postgres nor any secret. This is exactly why `get_session` is a
dependency: it can be swapped out for tests. Required env vars are set here before
the app is imported, so settings load without a real .env.
"""

import os

os.environ.setdefault("JWT_SECRET", "test-secret-not-for-prod-0123456789abcdef")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("SAP_BASE_URL", "http://sap.example/")
os.environ.setdefault("SAP_USER", "test")
os.environ.setdefault("CORS_ORIGINS", "http://localhost")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.models.user  # noqa: E402,F401 — register the model on Base.metadata
from app.core.database import Base, get_session  # noqa: E402
from app.core.rate_limit import reset_login_rate_limit  # noqa: E402
from app.main import app  # noqa: E402

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    # The login rate limiter is in-process module state; reset it so per-IP counters
    # never leak between tests.
    reset_login_rate_limit()
    yield


@pytest_asyncio.fixture
async def session():
    # StaticPool keeps a single in-memory connection so created tables stay visible.
    engine = create_async_engine(
        TEST_DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as test_session:
            yield test_session
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client(session):
    async def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()
