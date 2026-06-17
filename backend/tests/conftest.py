"""Pytest fixtures for the Biograph backend test suite.

Strategy
--------
* Each test function gets its own in-memory SQLite database (StaticPool so
  all async connections see the same schema).
* The ``get_session`` FastAPI dependency is overridden to use that database.
* ``biograph.auth.get_config`` is monkey-patched so auth checks use the
  fixed test token ``"test-token"``.
* The engine / session-factory lru_caches in ``biograph.database`` are
  cleared before and after each test so they are re-initialised fresh.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from biograph.config import Config, ServerConfig

TEST_TOKEN = "test-token"
_TEST_CONFIG = Config(server=ServerConfig(token=TEST_TOKEN, db_path=":memory:"))

# ---------------------------------------------------------------------------
# Database fixture — fresh in-memory SQLite per test
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await engine.dispose()


# ---------------------------------------------------------------------------
# HTTP client fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def client(session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Async test client with auth token pre-set and DB wired up."""
    from biograph.database import get_session
    from biograph.main import app

    async def _override_session() -> AsyncGenerator[AsyncSession, None]:
        yield session

    app.dependency_overrides[get_session] = _override_session

    # Patch get_config in every module that calls it directly (not via DI)
    with (
        patch("biograph.auth.get_config", return_value=_TEST_CONFIG),
        patch("biograph.database.get_config", return_value=_TEST_CONFIG),
        # Prevent the lifespan from running create_db_tables against the
        # real engine; the session fixture already built the schema.
        patch("biograph.main.create_db_tables", return_value=None),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://test",
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        ) as ac:
            yield ac

    app.dependency_overrides.clear()
