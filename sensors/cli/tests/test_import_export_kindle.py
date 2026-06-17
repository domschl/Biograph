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
    monkeypatch.setattr("biograph_cli.bio._load_kindle_state", lambda: {"sent_hashes": [], "sent_books": []})
    monkeypatch.setattr("biograph_cli.bio._save_kindle_state", lambda s: None)
    
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
    monkeypatch.setattr("biograph_cli.bio._load_kindle_state", lambda: {"sent_hashes": [], "sent_books": []})
    monkeypatch.setattr("biograph_cli.bio._save_kindle_state", lambda s: None)
    
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
