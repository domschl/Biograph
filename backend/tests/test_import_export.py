"""Tests for import/export API endpoints."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_import_and_export(client: AsyncClient) -> None:
    # 1. Create some events
    e1 = {
        "timestamp": datetime.now(UTC).isoformat(),
        "ev_type": "note",
        "content": {"text": "Import/Export Test Event 1"},
        "tags": ["test"],
    }
    e2 = {
        "timestamp": datetime.now(UTC).isoformat(),
        "ev_type": "shell-cmd",
        "content": {"cmd": "ls"},
        "tags": ["test", "cmd"],
    }
    
    await client.post("/events/", json=e1)
    await client.post("/events/", json=e2)
    
    # 2. Export them
    resp_export = await client.get("/events/export")
    assert resp_export.status_code == 200
    
    lines = resp_export.text.strip().split("\n")
    events = [json.loads(line) for line in lines if line.strip()]
    assert len(events) >= 2
    
    test_events = [e for e in events if "test" in e.get("tags", [])]
    assert len(test_events) == 2
    
    n1 = next(e for e in test_events if e["ev_type"] == "note")
    n2 = next(e for e in test_events if e["ev_type"] == "shell-cmd")
    
    assert n1["content"]["text"] == "Import/Export Test Event 1"
    assert n2["content"]["cmd"] == "ls"
    
    # 3. Import new event via NDJSON stream
    import_payload = (
        json.dumps({
            "timestamp": datetime.now(UTC).isoformat(),
            "ev_type": "note",
            "source_host": "import-test",
            "source_app": "pytest",
            "content": {"text": "Imported Event"},
            "tags": ["imported"],
            "summary": "Import check"
        }) + "\n"
    )
    
    resp_import = await client.post("/events/import", content=import_payload)
    assert resp_import.status_code == 201
    assert resp_import.json() == {"imported": 1}
    
    # Verify the imported event is in the DB
    resp_list = await client.get("/events/?tags=imported")
    assert resp_list.status_code == 200
    items = resp_list.json()["items"]
    assert len(items) == 1
    assert items[0]["content"]["text"] == "Imported Event"
