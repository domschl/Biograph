"""Tests for the unauthenticated /covers/{book_uuid} endpoint."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from biograph.config import Config, ResourcesConfig, ServerConfig


@pytest.mark.asyncio
async def test_get_book_cover_success_and_validation(tmp_path: Path) -> None:
    from biograph.main import app

    covers_dir = tmp_path / "BookCoverIcons"
    covers_dir.mkdir()
    book_uuid = "12345678-1234-5678-1234-567812345678"
    cover_bytes = b"\xff\xd8\xff\xe0fake-jpeg-bytes"
    (covers_dir / f"{book_uuid}.jpg").write_bytes(cover_bytes)

    cfg = Config(
        server=ServerConfig(token="secret-token", db_path=":memory:"),
        resources=ResourcesConfig(book_covers=str(covers_dir)),
    )

    with (
        patch("biograph.api.covers.get_config", return_value=cfg),
        patch("biograph.main.create_db_tables", return_value=None),
    ):
        # Deliberately omit Authorization header
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://test",
        ) as ac:
            r1 = await ac.get(f"/covers/{book_uuid}")
            assert r1.status_code == 200
            assert r1.content == cover_bytes
            assert r1.headers.get("cache-control") == "public, max-age=86400"

            r2 = await ac.get(f"/covers/{book_uuid}.jpg")
            assert r2.status_code == 200
            assert r2.content == cover_bytes

            r_missing = await ac.get("/covers/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
            assert r_missing.status_code == 404

            r_bad = await ac.get("/covers/not-a-uuid")
            assert r_bad.status_code == 400


@pytest.mark.asyncio
async def test_get_book_cover_unconfigured_returns_404() -> None:
    from biograph.main import app

    cfg = Config(
        server=ServerConfig(token="secret-token", db_path=":memory:"),
        resources=ResourcesConfig(book_covers=""),
    )

    with (
        patch("biograph.api.covers.get_config", return_value=cfg),
        patch("biograph.main.create_db_tables", return_value=None),
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=True),
            base_url="http://test",
        ) as ac:
            resp = await ac.get("/covers/12345678-1234-5678-1234-567812345678")
            assert resp.status_code == 404
