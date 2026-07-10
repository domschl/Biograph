"""Tests for the bio CLI."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import httpx
import pytest
import respx
from typer.testing import CliRunner

from biograph_cli.bio import app

runner = CliRunner()

FAKE_URL = "http://biograph.test"
FAKE_CONFIG: dict = {
    "server": {"url": FAKE_URL, "token": "test-token"}
}

# Always patch _load_config so tests don't read ~/.config/biograph/config.toml
pytestmark = pytest.mark.usefixtures("_patch_config")


@pytest.fixture(autouse=True)
def _patch_config(monkeypatch):
    monkeypatch.setattr("biograph_cli.bio._load_config", lambda: FAKE_CONFIG)


# ---------------------------------------------------------------------------
# bio log
# ---------------------------------------------------------------------------


@respx.mock
def test_log_with_inline_message():
    route = respx.post(f"{FAKE_URL}/events/").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 1,
                "ev_type": "note",
                "timestamp": datetime.now(UTC).isoformat(),
                "received_at": datetime.now(UTC).isoformat(),
                "source_host": None,
                "source_app": None,
                "content": {"text": "hello"},
                "tags": [],
                "summary": None,
                "deleted_at": None,
            },
        )
    )
    result = runner.invoke(app, ["log", "hello"])
    assert result.exit_code == 0
    assert "Event #1" in result.output
    assert route.called


@respx.mock
def test_log_with_tags():
    respx.post(f"{FAKE_URL}/events/").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 2,
                "ev_type": "note",
                "timestamp": datetime.now(UTC).isoformat(),
                "received_at": datetime.now(UTC).isoformat(),
                "source_host": None,
                "source_app": None,
                "content": {"text": "hike"},
                "tags": ["outdoor", "health"],
                "summary": None,
                "deleted_at": None,
            },
        )
    )
    result = runner.invoke(app, ["log", "hike", "--tags", "outdoor,health"])
    assert result.exit_code == 0
    request_body = respx.calls.last.request.read()
    import json
    body = json.loads(request_body)
    assert body["tags"] == ["outdoor", "health"]


@respx.mock
def test_log_with_mood():
    respx.post(f"{FAKE_URL}/events/").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 3,
                "ev_type": "note",
                "timestamp": datetime.now(UTC).isoformat(),
                "received_at": datetime.now(UTC).isoformat(),
                "source_host": None,
                "source_app": None,
                "content": {"text": "great day", "mood": "happy"},
                "tags": [],
                "summary": None,
                "deleted_at": None,
            },
        )
    )
    result = runner.invoke(app, ["log", "great day", "--mood", "happy"])
    assert result.exit_code == 0
    import json
    body = json.loads(respx.calls.last.request.read())
    assert body["content"]["mood"] == "happy"


def test_log_opens_editor_when_no_message():
    """bio log with no argument should call _open_editor."""
    with patch("biograph_cli.bio._open_editor", return_value="") as mock_editor:
        result = runner.invoke(app, ["log"])
    mock_editor.assert_called_once()
    assert result.exit_code == 1  # empty message → abort


@respx.mock
def test_log_editor_message_is_sent():
    respx.post(f"{FAKE_URL}/events/").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 4,
                "ev_type": "note",
                "timestamp": datetime.now(UTC).isoformat(),
                "received_at": datetime.now(UTC).isoformat(),
                "source_host": None,
                "source_app": None,
                "content": {"text": "editor text"},
                "tags": [],
                "summary": None,
                "deleted_at": None,
            },
        )
    )
    with patch("biograph_cli.bio._open_editor", return_value="editor text"):
        result = runner.invoke(app, ["log"])
    assert result.exit_code == 0
    assert "Event #4" in result.output


@respx.mock
def test_log_server_error_exits_nonzero():
    respx.post(f"{FAKE_URL}/events/").mock(
        return_value=httpx.Response(401, json={"detail": "Unauthorized"})
    )
    result = runner.invoke(app, ["log", "hello"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# bio search
# ---------------------------------------------------------------------------


@respx.mock
def test_search_returns_table():
    respx.get(f"{FAKE_URL}/events/").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": 1,
                        "ev_type": "note",
                        "timestamp": "2024-06-17T10:00:00+00:00",
                        "received_at": "2024-06-17T10:00:01+00:00",
                        "source_host": None,
                        "source_app": None,
                        "content": {"text": "went hiking"},
                        "tags": ["outdoor"],
                        "summary": None,
                        "deleted_at": None,
                    }
                ],
                "total": 1,
                "limit": 20,
                "offset": 0,
            },
        )
    )
    result = runner.invoke(app, ["search", "hiking"])
    assert result.exit_code == 0
    assert "hiking" in result.output
    assert "note" in result.output


@respx.mock
def test_search_no_results():
    respx.get(f"{FAKE_URL}/events/").mock(
        return_value=httpx.Response(
            200,
            json={"items": [], "total": 0, "limit": 20, "offset": 0},
        )
    )
    result = runner.invoke(app, ["search", "nothing"])
    assert result.exit_code == 0
    assert "No results" in result.output


@respx.mock
def test_export_options(tmp_path):
    output_file = tmp_path / "export.ndjson"
    route = respx.get(f"{FAKE_URL}/events/export").mock(
        return_value=httpx.Response(
            200,
            text='{"id": 1, "ev_type": "note", "timestamp": "2024-06-17T10:00:00+00:00", "content": {"text": "hello"}}\n'
        )
    )
    result = runner.invoke(app, ["export", str(output_file), "--since", "10", "--include-deleted"])
    assert result.exit_code == 0
    assert output_file.exists()
    assert "Successfully exported events" in result.output
    
    # Check that query parameters were sent correctly
    url = route.calls.last.request.url
    assert b"since_update_id=10" in url.query
    assert b"include_deleted=true" in url.query


def test_resolve_resource_uri():
    from biograph_cli.bio import resolve_resource_uri
    config = {
        "resources": {
            "photos": "/home/user/Pictures",
            "ebooks": "/home/user/Books"
        }
    }
    
    assert resolve_resource_uri(None, config) is None
    assert resolve_resource_uri("http://example.com", config) == "http://example.com"
    assert resolve_resource_uri("/absolute/path.jpg", config) == "/absolute/path.jpg"
    assert resolve_resource_uri("{photos}/Album 1/Photo.jpg", config) == "/home/user/Pictures/Album 1/Photo.jpg"
    assert resolve_resource_uri("{ebooks}/Dune.epub", config) == "/home/user/Books/Dune.epub"
    assert resolve_resource_uri("{unknown}/test.txt", config) == "{unknown}/test.txt"
