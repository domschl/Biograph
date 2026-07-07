"""Async SQLite database engine and session management."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel import SQLModel

from biograph.config import get_config


@lru_cache(maxsize=1)
def _engine() -> AsyncEngine:
    config = get_config()
    url = f"sqlite+aiosqlite:///{config.server.db_path}"
    return create_async_engine(
        url,
        echo=False,
        future=True,
        connect_args={"check_same_thread": False},
    )


@lru_cache(maxsize=1)
def _session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(_engine(), expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a database session per request."""
    async with _session_factory()() as session:
        yield session


async def create_db_tables() -> None:
    """Ensure all SQLModel tables exist (idempotent; used on startup)."""
    async with _engine().begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        
        # Ensure alembic_version table is created and stamped with the current migration head
        # so that any future migrations can run out-of-the-box.
        try:
            await conn.execute(
                text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
            )
            # Check if database is already stamped
            res = await conn.execute(text("SELECT version_num FROM alembic_version"))
            if not res.first():
                await conn.execute(
                    text("INSERT INTO alembic_version (version_num) VALUES ('8a72d18ff538')")
                )
        except Exception:
            pass
