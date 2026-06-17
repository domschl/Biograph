"""Tests for kindle and import/export CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import respx
import httpx
from typer.testing import CliRunner
from biograph_cli.bio import app

runner = CliRunner()
FAKE_URL = "http://biograph.test"
FAKE_CONFIG = {"server": {"url": FAKE_URL, "token": "test-token"}}


@pytest.fixture(autouse=True)
def _patch_config(monkeypatch):
    monkeypatch.setattr("biograph_cli.bio._load_config", lambda: FAKE_CONFIG)


@respx.mock
def test_cli_export(tmp_path: Path):
    route = respx.get(f"{FAKE_URL}/events/export").mock(
        return_value=httpx.Response(200, text='{"timestamp":"2026-06-17T00:00:00","ev_type":"note","content":{"text":"Export Test"}}\n')
    )
    
    out_file = tmp_path / "export.ndjson"
    result = runner.invoke(app, ["export", str(out_file)])
    assert result.exit_code == 0
    assert "Successfully exported" in result.output
    assert out_file.exists()
    assert "Export Test" in out_file.read_text()
    assert route.called


@respx.mock
def test_cli_import(tmp_path: Path):
    route = respx.post(f"{FAKE_URL}/events/import").mock(
        return_value=httpx.Response(201, json={"imported": 5})
    )
    
    in_file = tmp_path / "import.ndjson"
    in_file.write_text('{"timestamp":"2026-06-17T00:00:00","ev_type":"note","content":{"text":"Import Test"}}\n')
    
    result = runner.invoke(app, ["import", str(in_file)])
    assert result.exit_code == 0
    assert "Successfully imported 5 events" in result.output
    assert route.called


@respx.mock
def test_cli_kindle(tmp_path: Path, monkeypatch):
    # Mock storage state path so we don't write to ~/.local/share/
    monkeypatch.setattr("biograph_cli.bio._load_kindle_state", lambda url: {"sent_hashes": [], "sent_books": []})
    monkeypatch.setattr("biograph_cli.bio._save_kindle_state", lambda url, s: None)
    
    # Create fake mount structure
    mount = tmp_path / "kindle_mount"
    docs = mount / "documents"
    docs.mkdir(parents=True)
    clippings = docs / "My Clippings.txt"
    
    clippings_content = (
        "The Hobbit (J.R.R. Tolkien)\n"
        "- Your Highlight on page 23 | Location 340-341 | Added on Saturday, 15 October 2022 13:45:22\n"
        "\n"
        "Here is the highlighted text.\n"
        "==========\n"
    )
    clippings.write_text(clippings_content, encoding="utf-8")
    
    route = respx.post(f"{FAKE_URL}/events/batch").mock(
        return_value=httpx.Response(201, json=[{"id": 1}, {"id": 2}])
    )
    
    result = runner.invoke(app, ["kindle", str(mount)])
    assert result.exit_code == 0
    assert "Successfully imported" in result.output
    assert route.called


@respx.mock
def test_cli_kindle_direct_file(tmp_path: Path, monkeypatch):
    # Mock storage state path so we don't write to ~/.local/share/
    monkeypatch.setattr("biograph_cli.bio._load_kindle_state", lambda url: {"sent_hashes": [], "sent_books": []})
    monkeypatch.setattr("biograph_cli.bio._save_kindle_state", lambda url, s: None)
    
    clippings = tmp_path / "custom_clippings.txt"
    clippings_content = (
        "The Hobbit (J.R.R. Tolkien)\n"
        "- Your Highlight on page 23 | Location 340-341 | Added on Saturday, 15 October 2022 13:45:22\n"
        "\n"
        "Here is the highlighted text.\n"
        "==========\n"
    )
    clippings.write_text(clippings_content, encoding="utf-8")
    
    route = respx.post(f"{FAKE_URL}/events/batch").mock(
        return_value=httpx.Response(201, json=[{"id": 1}, {"id": 2}])
    )
    
    result = runner.invoke(app, ["kindle", str(clippings)])
    assert result.exit_code == 0
    assert "Successfully imported" in result.output
    assert route.called


@respx.mock
def test_cli_tolino(tmp_path: Path, monkeypatch):
    # Mock storage state path so we don't write to ~/.local/share/
    monkeypatch.setattr("biograph_cli.bio._load_tolino_state", lambda url: {"sent_bookmark_ids": [], "sent_book_progress": {}})
    monkeypatch.setattr("biograph_cli.bio._save_tolino_state", lambda url, s: None)
    
    # Create fake mount structure
    mount = tmp_path / "tolino_mount"
    kobo_dir = mount / ".kobo"
    kobo_dir.mkdir(parents=True)
    db_file = kobo_dir / "KoboReader.sqlite"
    
    import sqlite3
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    
    # Create content table
    cursor.execute("""
        CREATE TABLE content (
            ContentID TEXT PRIMARY KEY,
            ContentType TEXT,
            Title TEXT,
            Attribution TEXT,
            ReadStatus INTEGER,
            ___PercentRead INTEGER,
            DateLastRead TEXT,
            DateCreated TEXT
        )
    """)
    
    # Create Bookmark table
    cursor.execute("""
        CREATE TABLE Bookmark (
            BookmarkID TEXT PRIMARY KEY,
            VolumeID TEXT,
            ContentID TEXT,
            StartContainerPath TEXT,
            Text TEXT,
            Annotation TEXT,
            DateCreated TEXT,
            Hidden INTEGER
        )
    """)
    
    # Insert a book
    cursor.execute("""
        INSERT INTO content (ContentID, ContentType, Title, Attribution, ReadStatus, ___PercentRead, DateLastRead, DateCreated)
        VALUES ('book1', '6', 'The Hobbit', 'J.R.R. Tolkien', 1, 50, '2026-06-17T12:00:00.000Z', '2026-06-17T10:00:00.000Z')
    """)
    
    # Insert a bookmark
    cursor.execute("""
        INSERT INTO Bookmark (BookmarkID, VolumeID, ContentID, StartContainerPath, Text, Annotation, DateCreated, Hidden)
        VALUES ('bm1', 'book1', 'book1', 'OEBPS/chapter1.xhtml', 'Here is the highlighted text.', 'My annotation', '2026-06-17T11:00:00.000Z', 0)
    """)
    
    conn.commit()
    conn.close()
    
    route = respx.post(f"{FAKE_URL}/events/batch").mock(
        return_value=httpx.Response(201, json=[{"id": 1}, {"id": 2}])
    )
    
    result = runner.invoke(app, ["tolino", str(mount)])
    assert result.exit_code == 0
    assert "Successfully imported 2 events" in result.output
    assert route.called

