"""Tests for GET /stats."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_stats_empty(client: AsyncClient) -> None:
    r = await client.get("/stats/")
    assert r.status_code == 200
    data = r.json()
    assert data["total_events"] == 0
    assert data["by_type"] == []


@pytest.mark.asyncio
async def test_stats_counts(client: AsyncClient) -> None:
    now = datetime.now(UTC).isoformat()
    for _ in range(3):
        await client.post("/events/", json={"timestamp": now, "ev_type": "note", "content": {}})
    for _ in range(2):
        await client.post("/events/", json={"timestamp": now, "ev_type": "shell-cmd", "content": {}})

    data = (await client.get("/stats/")).json()
    assert data["total_events"] == 5
    by_type = {row["ev_type"]: row["count"] for row in data["by_type"]}
    assert by_type["note"] == 3
    assert by_type["shell-cmd"] == 2


@pytest.mark.asyncio
async def test_stats_excludes_deleted(client: AsyncClient) -> None:
    now = datetime.now(UTC).isoformat()
    r = await client.post("/events/", json={"timestamp": now, "ev_type": "note", "content": {}})
    event_id = r.json()["id"]
    await client.delete(f"/events/{event_id}")

    data = (await client.get("/stats/")).json()
    assert data["total_events"] == 0
