"""Tests for the /events endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event_payload(**overrides: object) -> dict:
    base: dict = {
        "timestamp": datetime.now(UTC).isoformat(),
        "ev_type": "note",
        "content": {"text": "Hello, world!"},
        "tags": [],
    }
    base.update(overrides)
    return base


async def _create(client: AsyncClient, **kwargs: object) -> dict:
    r = await client.post("/events/", json=_event_payload(**kwargs))
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_token_is_rejected(client: AsyncClient) -> None:
    # Explicitly unset the default Authorization header
    r = await client.get("/events/", headers={"Authorization": ""})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_wrong_token_is_rejected(client: AsyncClient) -> None:
    r = await client.get("/events/", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Create — POST /events/
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_event_returns_201(client: AsyncClient) -> None:
    r = await client.post("/events/", json=_event_payload())
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_create_event_fields(client: AsyncClient) -> None:
    payload = _event_payload(
        ev_type="shell-cmd",
        source_host="myhost",
        source_app="zsh",
        content={"cmd": "ls -la", "exit_code": 0, "cwd": "/home/user"},
        tags=["dev", "terminal"],
        summary="listed files",
    )
    data = (await client.post("/events/", json=payload)).json()

    assert data["ev_type"] == "shell-cmd"
    assert data["source_host"] == "myhost"
    assert data["source_app"] == "zsh"
    assert data["content"] == {"cmd": "ls -la", "exit_code": 0, "cwd": "/home/user"}
    assert data["tags"] == ["dev", "terminal"]
    assert data["summary"] == "listed files"
    assert data["deleted_at"] is None
    assert data["id"] is not None
    assert data["received_at"] is not None


# ---------------------------------------------------------------------------
# Batch — POST /events/batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_create(client: AsyncClient) -> None:
    payloads = [_event_payload(ev_type="note", content={"text": f"note {i}"}) for i in range(5)]
    r = await client.post("/events/batch", json=payloads)
    assert r.status_code == 201
    assert len(r.json()) == 5


@pytest.mark.asyncio
async def test_batch_empty(client: AsyncClient) -> None:
    r = await client.post("/events/batch", json=[])
    assert r.status_code == 201
    assert r.json() == []


# ---------------------------------------------------------------------------
# List — GET /events/
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_events_empty(client: AsyncClient) -> None:
    r = await client.get("/events/")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["items"] == []


@pytest.mark.asyncio
async def test_list_events_returns_all(client: AsyncClient) -> None:
    for _ in range(3):
        await _create(client)
    data = (await client.get("/events/")).json()
    assert data["total"] == 3
    assert len(data["items"]) == 3


@pytest.mark.asyncio
async def test_list_events_pagination(client: AsyncClient) -> None:
    for _ in range(5):
        await _create(client)

    page1 = (await client.get("/events/", params={"limit": 2, "offset": 0})).json()
    page2 = (await client.get("/events/", params={"limit": 2, "offset": 2})).json()

    assert len(page1["items"]) == 2
    assert len(page2["items"]) == 2
    assert page1["total"] == 5
    # IDs must not overlap
    ids1 = {e["id"] for e in page1["items"]}
    ids2 = {e["id"] for e in page2["items"]}
    assert ids1.isdisjoint(ids2)


@pytest.mark.asyncio
async def test_list_filter_by_ev_type(client: AsyncClient) -> None:
    await _create(client, ev_type="note")
    await _create(client, ev_type="shell-cmd")
    await _create(client, ev_type="note")

    data = (await client.get("/events/", params={"ev_type": "note"})).json()
    assert data["total"] == 2
    assert all(e["ev_type"] == "note" for e in data["items"])


@pytest.mark.asyncio
async def test_list_filter_by_source(client: AsyncClient) -> None:
    await _create(client, source_host="alpha", source_app="zsh")
    await _create(client, source_host="beta", source_app="chrome")

    data = (await client.get("/events/", params={"source_host": "alpha"})).json()
    assert data["total"] == 1
    assert data["items"][0]["source_host"] == "alpha"


@pytest.mark.asyncio
async def test_list_filter_by_date_range(client: AsyncClient) -> None:
    now = datetime.now(UTC)
    yesterday = now - timedelta(days=1)
    tomorrow = now + timedelta(days=1)

    await _create(client, timestamp=yesterday.isoformat())
    await _create(client, timestamp=now.isoformat())
    await _create(client, timestamp=tomorrow.isoformat())

    data = (await client.get("/events/", params={"from": now.isoformat()})).json()
    assert data["total"] == 2  # now and tomorrow


@pytest.mark.asyncio
async def test_list_search_by_q(client: AsyncClient) -> None:
    await _create(client, content={"text": "went hiking today"})
    await _create(client, content={"text": "grocery shopping"})

    data = (await client.get("/events/", params={"q": "hiking"})).json()
    assert data["total"] == 1


@pytest.mark.asyncio
async def test_list_filter_by_tags(client: AsyncClient) -> None:
    await _create(client, tags=["health", "outdoor"])
    await _create(client, tags=["work"])
    await _create(client, tags=["health", "work"])

    data = (await client.get("/events/", params={"tags": "health"})).json()
    assert data["total"] == 2


# ---------------------------------------------------------------------------
# Get — GET /events/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_event(client: AsyncClient) -> None:
    created = await _create(client, summary="my note")
    r = await client.get(f"/events/{created['id']}")
    assert r.status_code == 200
    assert r.json()["summary"] == "my note"


@pytest.mark.asyncio
async def test_get_nonexistent_event(client: AsyncClient) -> None:
    r = await client.get("/events/99999")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Update — PATCH /events/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_tags(client: AsyncClient) -> None:
    created = await _create(client)
    r = await client.patch(f"/events/{created['id']}", json={"tags": ["updated"]})
    assert r.status_code == 200
    assert r.json()["tags"] == ["updated"]


@pytest.mark.asyncio
async def test_patch_summary(client: AsyncClient) -> None:
    created = await _create(client)
    r = await client.patch(f"/events/{created['id']}", json={"summary": "new summary"})
    assert r.status_code == 200
    assert r.json()["summary"] == "new summary"


# ---------------------------------------------------------------------------
# Delete — DELETE /events/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_event(client: AsyncClient) -> None:
    created = await _create(client)
    r = await client.delete(f"/events/{created['id']}")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_deleted_event_not_in_list(client: AsyncClient) -> None:
    created = await _create(client)
    await client.delete(f"/events/{created['id']}")

    data = (await client.get("/events/")).json()
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_deleted_event_not_retrievable(client: AsyncClient) -> None:
    created = await _create(client)
    await client.delete(f"/events/{created['id']}")
    r = await client.get(f"/events/{created['id']}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_filter_kodi_movie_includes_youtube_movies(client: AsyncClient) -> None:
    # 1. Standard kodi-movie
    await _create(client, ev_type="kodi-movie", content={"title": "Matrix"})
    # 2. Web visit (non-youtube)
    await _create(client, ev_type="web-visit", content={"url": "https://google.com"})
    # 3. Web visit (youtube watch URL)
    await _create(client, ev_type="web-visit", content={"url": "https://www.youtube.com/watch?v=123"})

    # Filter by kodi-movie only
    r = await client.get("/events/", params={"ev_type": "kodi-movie"})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    types = [e["ev_type"] for e in data["items"]]
    assert "kodi-movie" in types
    assert "web-visit" in types
    urls = [e["content"].get("url") for e in data["items"] if e["ev_type"] == "web-visit"]
    assert urls == ["https://www.youtube.com/watch?v=123"]

    # Filter by web-visit only
    r = await client.get("/events/", params={"ev_type": "web-visit"})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    types = [e["ev_type"] for e in data["items"]]
    assert "kodi-movie" not in types
    assert all(t == "web-visit" for t in types)

    # Filter by both
    r = await client.get("/events/", params={"ev_type": ["kodi-movie", "web-visit"]})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 3


@pytest.mark.asyncio
async def test_kodi_tvshow(client: AsyncClient) -> None:
    # Create kodi-tvshow event
    created = await _create(
        client,
        ev_type="kodi-tvshow",
        content={
            "title": "Pilot",
            "tvshow_title": "Breaking Bad",
            "season": 1,
            "episode": 1,
            "year": 2008,
            "imdb_id": "tt0903747",
            "db_id": 42,
            "file": "/path/to/breaking_bad_s01e01.mkv",
            "duration_seconds": 3480,
            "progress_percent": 100.0,
            "finished": True,
        },
        tags=["media", "tvshow", "kodi"],
    )
    assert created["ev_type"] == "kodi-tvshow"
    assert created["content"]["tvshow_title"] == "Breaking Bad"

    # List and filter by kodi-tvshow
    r = await client.get("/events/", params={"ev_type": "kodi-tvshow"})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["ev_type"] == "kodi-tvshow"
    assert data["items"][0]["content"]["title"] == "Pilot"


@pytest.mark.asyncio
async def test_ereader_deduplication_single(client: AsyncClient) -> None:
    ts = "2026-07-01T12:00:00Z"

    # 1. Create first Kindle highlight
    r1 = await client.post(
        "/events/",
        json=_event_payload(
            timestamp=ts,
            ev_type="kindle-highlight",
            content={"highlight": "First snippet", "book_title": "Book A"}
        )
    )
    assert r1.status_code == 201
    data1 = r1.json()
    id1 = data1["id"]

    # 2. Try to create the same highlight again (same timestamp and type, different content)
    r2 = await client.post(
        "/events/",
        json=_event_payload(
            timestamp=ts,
            ev_type="kindle-highlight",
            content={"highlight": "Second snippet (content is ignored for dedup)", "book_title": "Book A"}
        )
    )
    assert r2.status_code == 201
    data2 = r2.json()
    id2 = data2["id"]

    # Assert they returned the same event ID
    assert id1 == id2

    # Verify only one exists in database
    r_list = await client.get("/events/", params={"ev_type": "kindle-highlight"})
    assert r_list.status_code == 200
    assert r_list.json()["total"] == 1


@pytest.mark.asyncio
async def test_non_ereader_no_deduplication(client: AsyncClient) -> None:
    ts = "2026-07-01T12:00:00Z"

    # Create two shell commands with the exact same timestamp
    r1 = await client.post(
        "/events/",
        json=_event_payload(
            timestamp=ts,
            ev_type="shell-cmd",
            content={"cmd": "ls"}
        )
    )
    assert r1.status_code == 201
    id1 = r1.json()["id"]

    r2 = await client.post(
        "/events/",
        json=_event_payload(
            timestamp=ts,
            ev_type="shell-cmd",
            content={"cmd": "pwd"}
        )
    )
    assert r2.status_code == 201
    id2 = r2.json()["id"]

    # They must be separate events with different IDs
    assert id1 != id2

    # Both must exist in the database
    r_list = await client.get("/events/", params={"ev_type": "shell-cmd"})
    assert r_list.status_code == 200
    assert r_list.json()["total"] == 2


@pytest.mark.asyncio
async def test_ereader_deduplication_batch(client: AsyncClient) -> None:
    ts1 = "2026-07-01T12:00:00Z"
    ts2 = "2026-07-01T12:05:00Z"

    # 1. Pre-insert one highlight in DB
    await client.post(
        "/events/",
        json=_event_payload(
            timestamp=ts1,
            ev_type="tolino-highlight",
            content={"highlight": "Existing"}
        )
    )

    # 2. Post a batch containing:
    #    - An event matching the pre-inserted one (should be deduped)
    #    - Two identical new events within the batch (should be deduped to one)
    #    - A non-ereader event with same timestamp (should not be deduped)
    batch = [
        _event_payload(timestamp=ts1, ev_type="tolino-highlight", content={"highlight": "Existing clone"}),
        _event_payload(timestamp=ts2, ev_type="tolino-highlight", content={"highlight": "New highlight 1"}),
        _event_payload(timestamp=ts2, ev_type="tolino-highlight", content={"highlight": "New highlight 2"}),
        _event_payload(timestamp=ts2, ev_type="shell-cmd", content={"cmd": "echo 1"}),
    ]

    r = await client.post("/events/batch", json=batch)
    assert r.status_code == 201
    results = r.json()
    assert len(results) == 4

    # 3. Query all tolino highlights to make sure only 2 exist in total
    r_list = await client.get("/events/", params={"ev_type": "tolino-highlight"})
    assert r_list.status_code == 200
    assert r_list.json()["total"] == 2


@pytest.mark.asyncio
async def test_calibre_deduplication_single(client: AsyncClient) -> None:
    # 1. Create first Calibre book event
    r1 = await client.post(
        "/events/",
        json=_event_payload(
            ev_type="calibre-book",
            content={"uuid": "uuid-123", "title": "Test Book", "authors": ["Author A"]}
        )
    )
    assert r1.status_code == 201
    id1 = r1.json()["id"]

    # 2. Try to create the same book event again (different timestamp and other content, but same uuid)
    r2 = await client.post(
        "/events/",
        json=_event_payload(
            ev_type="calibre-book",
            content={"uuid": "uuid-123", "title": "Test Book (Updated)", "authors": ["Author A"]}
        )
    )
    assert r2.status_code == 201
    id2 = r2.json()["id"]

    # Assert they returned the same event ID (deduplicated)
    assert id1 == id2

    # Verify only one exists in database
    r_list = await client.get("/events/", params={"ev_type": "calibre-book"})
    assert r_list.status_code == 200
    assert r_list.json()["total"] == 1


@pytest.mark.asyncio
async def test_calibre_deduplication_batch(client: AsyncClient) -> None:
    # 1. Pre-insert one calibre book in DB
    await client.post(
        "/events/",
        json=_event_payload(
            ev_type="calibre-book",
            content={"uuid": "uuid-existing", "title": "Existing Book"}
        )
    )

    # 2. Post a batch containing:
    #    - An event matching the pre-inserted uuid (should be deduped)
    #    - Two identical new events within the batch (should be deduped to one)
    batch = [
        _event_payload(ev_type="calibre-book", content={"uuid": "uuid-existing", "title": "Existing Book Clone"}),
        _event_payload(ev_type="calibre-book", content={"uuid": "uuid-new-1", "title": "New Book 1"}),
        _event_payload(ev_type="calibre-book", content={"uuid": "uuid-new-1", "title": "New Book 1 Clone"}),
    ]

    r = await client.post("/events/batch", json=batch)
    assert r.status_code == 201
    results = r.json()
    assert len(results) == 3

    # 3. Query all calibre books to make sure only 2 exist in total
    r_list = await client.get("/events/", params={"ev_type": "calibre-book"})
    assert r_list.status_code == 200
    assert r_list.json()["total"] == 2


@pytest.mark.asyncio
async def test_update_id_assigned_on_create(client: AsyncClient) -> None:
    # Create first event
    ev1 = await _create(client, content={"text": "First"})
    assert ev1["update_id"] is not None
    
    # Create second event
    ev2 = await _create(client, content={"text": "Second"})
    assert ev2["update_id"] > ev1["update_id"]


@pytest.mark.asyncio
async def test_update_id_changed_on_update(client: AsyncClient) -> None:
    ev = await _create(client, content={"text": "Original"})
    orig_update_id = ev["update_id"]
    
    # Modify event via PATCH
    r = await client.patch(f"/events/{ev['id']}", json={"summary": "New Summary"})
    assert r.status_code == 200
    updated = r.json()
    assert updated["update_id"] > orig_update_id
    assert updated["summary"] == "New Summary"


@pytest.mark.asyncio
async def test_update_id_changed_on_delete(client: AsyncClient) -> None:
    ev = await _create(client, content={"text": "To Delete"})
    orig_update_id = ev["update_id"]
    
    # Delete event
    r = await client.delete(f"/events/{ev['id']}")
    assert r.status_code == 204
    
    # Check that query with include_deleted shows the updated update_id
    r_list = await client.get("/events/", params={"include_deleted": True})
    assert r_list.status_code == 200
    events = r_list.json()["items"]
    deleted_ev = next(e for e in events if e["id"] == ev["id"])
    assert deleted_ev["deleted_at"] is not None
    assert deleted_ev["update_id"] > orig_update_id


@pytest.mark.asyncio
async def test_export_since_update_id(client: AsyncClient) -> None:
    import json
    ev1 = await _create(client, content={"text": "One"})
    ev2 = await _create(client, content={"text": "Two"})
    
    # Export without since_update_id
    r = await client.get("/events/export")
    assert r.status_code == 200
    lines = [line for line in r.text.split("\n") if line]
    assert len(lines) >= 2
    
    # Export since ev1's update_id
    r_since = await client.get("/events/export", params={"since_update_id": ev1["update_id"]})
    assert r_since.status_code == 200
    lines_since = [line for line in r_since.text.split("\n") if line]
    # Should contain ev2, but not ev1
    events_since = [json.loads(line) for line in lines_since]
    assert any(e["id"] == ev2["id"] for e in events_since)
    assert not any(e["id"] == ev1["id"] for e in events_since)


@pytest.mark.asyncio
async def test_import_upserts_and_preserves(client: AsyncClient) -> None:
    import json
    # 1. Create a dummy event, then delete it locally to test deletion import
    ev_to_delete = await _create(client, content={"text": "ToDelete"})
    await client.delete(f"/events/{ev_to_delete['id']}")
    
    # Fetch its deleted state
    r_list = await client.get("/events/", params={"include_deleted": True})
    deleted_ev_data = next(e for e in r_list.json()["items"] if e["id"] == ev_to_delete["id"])
    
    # Create another event to test update
    ev_to_update = await _create(client, content={"text": "ToUpdate"})
    
    # Prepare export data (NDJSON lines) representing:
    # - A new event with specific ID
    # - An update to ev_to_update
    # - The deleted status for ev_to_delete
    import_lines = [
        json.dumps({
            "id": 9999,
            "timestamp": datetime.now(UTC).isoformat(),
            "received_at": datetime.now(UTC).isoformat(),
            "ev_type": "note",
            "content": {"text": "Imported New"},
            "tags": ["imported"],
            "summary": "Imported Event",
            "deleted_at": None,
            "remote_id": "remote-9999",
            "update_id": 9999
        }),
        json.dumps({
            "id": ev_to_update["id"],
            "timestamp": ev_to_update["timestamp"],
            "received_at": ev_to_update["received_at"],
            "ev_type": ev_to_update["ev_type"],
            "content": {"text": "Updated Content"},
            "tags": ["updated"],
            "summary": "Updated Summary",
            "deleted_at": None,
            "remote_id": "remote-updated",
            "update_id": ev_to_update["update_id"] + 100
        }),
        json.dumps(deleted_ev_data)
    ]
    
    import_payload = "\n".join(import_lines) + "\n"
    r_import = await client.post("/events/import", content=import_payload)
    assert r_import.status_code == 201
    assert r_import.json() == {"imported": 3}
    
    # Verify new event exists with id 9999 and correct fields
    r_new = await client.get(f"/events/9999")
    assert r_new.status_code == 200
    assert r_new.json()["content"] == {"text": "Imported New"}
    assert r_new.json()["remote_id"] == "remote-9999"
    assert r_new.json()["update_id"] == 9999
    
    # Verify updated event has new content and updated tags
    r_updated = await client.get(f"/events/{ev_to_update['id']}")
    assert r_updated.status_code == 200
    assert r_updated.json()["content"] == {"text": "Updated Content"}
    assert r_updated.json()["tags"] == ["updated"]
    assert r_updated.json()["summary"] == "Updated Summary"
    
    # Verify deleted event is still deleted
    r_deleted_check = await client.get(f"/events/{ev_to_delete['id']}")
    assert r_deleted_check.status_code == 404


@pytest.mark.asyncio
async def test_create_with_resource_uri(client: AsyncClient) -> None:
    payload = _event_payload(
        resource_uri="{photos}/Album 1/Photo 1.jpg"
    )
    r = await client.post("/events/", json=payload)
    assert r.status_code == 201
    data = r.json()
    assert data["resource_uri"] == "{photos}/Album 1/Photo 1.jpg"


@pytest.mark.asyncio
async def test_query_by_resource_uri(client: AsyncClient) -> None:
    uri = "{ebooks}/Dune.epub"
    ev1 = await _create(client, resource_uri=uri)
    ev2 = await _create(client, resource_uri="{photos}/test.jpg")
    
    # Query by resource_uri
    r = await client.get("/events/", params={"resource_uri": uri})
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == ev1["id"]
    assert items[0]["resource_uri"] == uri


@pytest.mark.asyncio
async def test_import_export_resource_uri(client: AsyncClient) -> None:
    import json
    uri = "{ebooks}/Hobbit.epub"
    ev = await _create(client, resource_uri=uri)
    
    # Export
    r_exp = await client.get("/events/export")
    assert r_exp.status_code == 200
    lines = [line for line in r_exp.text.split("\n") if line]
    exported_ev = next(json.loads(line) for line in lines if json.loads(line)["id"] == ev["id"])
    assert exported_ev["resource_uri"] == uri
    
    # Modify locally via import
    exported_ev["resource_uri"] = "{ebooks}/Hobbit_New.epub"
    r_imp = await client.post("/events/import", content=json.dumps(exported_ev) + "\n")
    assert r_imp.status_code == 201
    
    # Verify import update took effect
    r_get = await client.get(f"/events/{ev['id']}")
    assert r_get.status_code == 200
    assert r_get.json()["resource_uri"] == "{ebooks}/Hobbit_New.epub"



