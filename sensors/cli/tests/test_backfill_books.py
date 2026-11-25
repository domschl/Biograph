"""Tests for the `bio backfill-books` CLI command."""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

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


@pytest.fixture(autouse=True)
def _patch_config(monkeypatch):
    monkeypatch.setattr("biograph_cli.bio._load_config", lambda: FAKE_CONFIG)


def _write_catalog(path: Path) -> Path:
    catalog_file = path / ".knrs-catalog.json"
    catalog = {
        "version": 1,
        "books": {
            "11111111-1111-1111-1111-111111111111": {
                "uuid": "11111111-1111-1111-1111-111111111111",
                "title": "Dune",
                "authors": ["Frank Herbert"],
                "series": "Science Fiction",
                "files": [
                    {
                        "rel_path": "Science Fiction/Frank Herbert - Dune.epub",
                        "format": "epub",
                        "filename_md5": "hash-fn-dune",
                        "koreader_partial_md5": "hash-content-dune",
                    }
                ],
            },
            "22222222-2222-2222-2222-222222222222": {
                "uuid": "22222222-2222-2222-2222-222222222222",
                "title": "Über Book",
                "authors": ["Jane Doe"],
                "series": "Philosophy",
                "files": [
                    {
                        "rel_path": unicodedata.normalize("NFC", "Philosophy/Jane Doe - Über Book.epub"),
                        "format": "epub",
                        "filename_md5": "hash-fn-uber",
                        "koreader_partial_md5": "hash-content-uber",
                    }
                ],
            },
            "33333333-3333-3333-3333-333333333333": {
                "uuid": "33333333-3333-3333-3333-333333333333",
                "title": "Meditations",
                "authors": ["Marcus Aurelius"],
                "series": "Classics",
                "files": [
                    {
                        "rel_path": "Classics/Marcus Aurelius - Meditations.epub",
                        "format": "epub",
                        "filename_md5": "hash-fn-med",
                        "koreader_partial_md5": "hash-content-med",
                    }
                ],
            },
        },
    }
    catalog_file.write_text(json.dumps(catalog), encoding="utf-8")
    return catalog_file


def _sample_events() -> list[dict]:
    ts = "2026-11-20T10:00:00+00:00"
    return [
        # 1. Match by hash
        {
            "id": 1,
            "timestamp": ts,
            "received_at": ts,
            "ev_type": "koreader-progress",
            "source_host": "nalanda",
            "source_app": "koreader-sync-server",
            "content": {
                "document_hash": "hash-content-dune",
                "filename": None,
                "percentage": 0.42,
            },
            "tags": [],
            "summary": "Reading progress on 'hash-conten': 42.0%",
            "deleted_at": None,
            "remote_id": None,
            "update_id": 10,
            "resource_uri": None,
        },
        # 2. Match by NFD/NFC path
        {
            "id": 2,
            "timestamp": ts,
            "received_at": ts,
            "ev_type": "koreader-progress",
            "source_host": "nalanda",
            "source_app": "koreader-sync-server",
            "content": {
                "document_hash": "other-hash",
                "filename": unicodedata.normalize("NFD", "Philosophy/Jane Doe - Über Book.epub"),
                "percentage": 0.5,
            },
            "tags": ["reading"],
            "summary": "Reading progress on 'Philosophy/Jane Doe - Über Book.epub': 50.0%",
            "deleted_at": None,
            "remote_id": None,
            "update_id": 11,
            "resource_uri": None,
        },
        # 3. Match by unambiguous title (Kindle highlight)
        {
            "id": 3,
            "timestamp": ts,
            "received_at": ts,
            "ev_type": "kindle-highlight",
            "source_host": "laptop",
            "source_app": "kindle",
            "content": {
                "book_title": "Meditations",
                "author": "Marcus Aurelius",
                "highlight": "Waste no more time arguing...",
            },
            "tags": ["highlight"],
            "summary": "Highlight in Meditations",
            "deleted_at": None,
            "remote_id": "hl-3",
            "update_id": 12,
            "resource_uri": None,
        },
        # 4. Already up-to-date (must be skipped)
        {
            "id": 4,
            "timestamp": ts,
            "received_at": ts,
            "ev_type": "koreader-progress",
            "source_host": "nalanda",
            "source_app": "koreader-sync-server",
            "content": {
                "book_uuid": "11111111-1111-1111-1111-111111111111",
                "title": "Dune",
                "authors": ["Frank Herbert"],
                "author": "Frank Herbert",
                "series": "Science Fiction",
                "document_hash": "hash-content-dune",
                "percentage": 0.9,
            },
            "tags": [],
            "summary": "Reading progress on 'Dune': 90.0%",
            "deleted_at": None,
            "remote_id": None,
            "update_id": 13,
            "resource_uri": "knrs://book/11111111-1111-1111-1111-111111111111",
        },
    ]


@respx.mock
def test_backfill_books_dry_run_does_not_import(tmp_path: Path) -> None:
    _write_catalog(tmp_path)
    events = _sample_events()

    respx.get(f"{FAKE_URL}/events/").mock(
        return_value=httpx.Response(200, json={"items": events, "total": len(events), "limit": 500, "offset": 0})
    )
    import_route = respx.post(f"{FAKE_URL}/events/import").mock(
        return_value=httpx.Response(200, json={"imported": 3})
    )

    result = runner.invoke(app, ["backfill-books", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    assert not import_route.called


@respx.mock
def test_backfill_books_imports_ndjson_updates(tmp_path: Path) -> None:
    _write_catalog(tmp_path)
    events = _sample_events()

    respx.get(f"{FAKE_URL}/events/").mock(
        return_value=httpx.Response(200, json={"items": events, "total": len(events), "limit": 500, "offset": 0})
    )
    import_route = respx.post(f"{FAKE_URL}/events/import").mock(
        return_value=httpx.Response(200, json={"imported": 3})
    )

    result = runner.invoke(app, ["backfill-books", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert import_route.called
    assert "Backfilled 3 event(s)" in result.output

    lines = [
        json.loads(line)
        for line in respx.calls.last.request.content.decode("utf-8").strip().splitlines()
    ]
    assert len(lines) == 3

    by_id = {rec["id"]: rec for rec in lines}
    assert by_id[1]["content"]["book_uuid"] == "11111111-1111-1111-1111-111111111111"
    assert by_id[1]["content"]["title"] == "Dune"
    assert by_id[1]["resource_uri"] == "knrs://book/11111111-1111-1111-1111-111111111111"
    assert by_id[1]["summary"] == "Reading progress on 'Dune': 42.0%"
    assert "update_id" not in by_id[1]

    assert by_id[2]["content"]["book_uuid"] == "22222222-2222-2222-2222-222222222222"
    assert by_id[2]["content"]["title"] == "Über Book"
    assert by_id[2]["resource_uri"] == "knrs://book/22222222-2222-2222-2222-222222222222"

    assert by_id[3]["content"]["book_uuid"] == "33333333-3333-3333-3333-333333333333"
    assert by_id[3]["resource_uri"] == "knrs://book/33333333-3333-3333-3333-333333333333"
