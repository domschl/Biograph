"""Tests for calibre CLI command."""

from __future__ import annotations

import json
import sqlite3
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


def create_fake_calibre_db(db_path: Path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create calibre tables
    cursor.execute("""
        CREATE TABLE books (
            id INTEGER PRIMARY KEY,
            title TEXT,
            timestamp TEXT,
            pubdate TEXT,
            uuid TEXT,
            path TEXT,
            series_index REAL
        )
    """)
    cursor.execute("""
        CREATE TABLE authors (
            id INTEGER PRIMARY KEY,
            name TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE books_authors_link (
            id INTEGER PRIMARY KEY,
            book INTEGER,
            author INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE series (
            id INTEGER PRIMARY KEY,
            name TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE books_series_link (
            id INTEGER PRIMARY KEY,
            book INTEGER,
            series INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE tags (
            id INTEGER PRIMARY KEY,
            name TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE books_tags_link (
            id INTEGER PRIMARY KEY,
            book INTEGER,
            tag INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE data (
            id INTEGER PRIMARY KEY,
            book INTEGER,
            format TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE identifiers (
            id INTEGER PRIMARY KEY,
            book INTEGER,
            type TEXT,
            val TEXT
        )
    """)

    # Insert a book
    cursor.execute("""
        INSERT INTO books (id, title, timestamp, pubdate, uuid, path, series_index)
        VALUES (1, 'The Hobbit', '2026-07-06 18:40:13.874000+00:00', '1937-09-21 00:00:00+00:00', 'hobbit-uuid-123', 'Tolkien/Hobbit', 1.0)
    """)
    cursor.execute("INSERT INTO authors (id, name) VALUES (1, 'J.R.R. Tolkien')")
    cursor.execute("INSERT INTO books_authors_link (book, author) VALUES (1, 1)")
    cursor.execute("INSERT INTO series (id, name) VALUES (1, 'Middle-earth')")
    cursor.execute("INSERT INTO books_series_link (book, series) VALUES (1, 1)")
    cursor.execute("INSERT INTO tags (id, name) VALUES (1, 'Fantasy')")
    cursor.execute("INSERT INTO books_tags_link (book, tag) VALUES (1, 1)")
    cursor.execute("INSERT INTO data (book, format) VALUES (1, 'EPUB')")
    cursor.execute("INSERT INTO identifiers (book, type, val) VALUES (1, 'isbn', '9780261102217')")

    conn.commit()
    conn.close()


@respx.mock
def test_cli_calibre(tmp_path: Path, monkeypatch):
    # Mock state path load/save so we do not read/write to ~/.local/share/
    monkeypatch.setattr("biograph_cli.bio._load_calibre_state", lambda url: {"sent_uuids": []})
    monkeypatch.setattr("biograph_cli.bio._save_calibre_state", lambda url, s: None)

    db_file = tmp_path / "metadata.db"
    create_fake_calibre_db(db_file)

    route = respx.post(f"{FAKE_URL}/events/batch").mock(
        return_value=httpx.Response(201, json=[{"id": 1}])
    )

    result = runner.invoke(app, ["calibre", str(tmp_path)])
    assert result.exit_code == 0
    assert "Successfully imported 1 Calibre books" in result.output
    assert route.called

    # Check sent payload
    payload = json.loads(respx.calls.last.request.read())
    assert len(payload) == 1
    book = payload[0]
    assert book["ev_type"] == "calibre-book"
    assert book["content"]["uuid"] == "hobbit-uuid-123"
    assert book["content"]["title"] == "The Hobbit"
    assert book["content"]["authors"] == ["J.R.R. Tolkien"]
    assert book["content"]["series"] == "Middle-earth"
    assert book["content"]["series_index"] == 1.0
    assert book["content"]["isbn"] == "9780261102217"
    assert book["content"]["formats"] == ["EPUB"]
    assert book["content"]["tags"] == ["Fantasy"]
