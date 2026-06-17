"""Tests for the zsh history sensor."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
import respx
import httpx

from biograph_sensor_zsh.sensor import (
    EventBuffer,
    State,
    parse_history,
    send_events,
)


# ---------------------------------------------------------------------------
# parse_history
# ---------------------------------------------------------------------------

HISTORY_CONTENT = """\
: 1000000000:0;ls -la
: 1000000001:0;git status
: 1000000002:0;echo hello \\
world
: 1000000003:5;cat README.md
"""


def _write_history(tmp_path: Path, content: str) -> Path:
    p = tmp_path / ".zsh_history"
    p.write_text(content)
    return p


def test_parse_basic_entries(tmp_path: Path) -> None:
    f = _write_history(tmp_path, HISTORY_CONTENT)
    events, max_ts = parse_history(f, since_timestamp=0, hostname="testhost")
    assert len(events) == 4
    cmds = [e["content"]["cmd"] for e in events]
    assert "ls -la" in cmds
    assert "git status" in cmds
    assert "cat README.md" in cmds
    assert max_ts == 1000000003


def test_parse_multiline_command(tmp_path: Path) -> None:
    f = _write_history(tmp_path, HISTORY_CONTENT)
    events, _ = parse_history(f, since_timestamp=0, hostname="testhost")
    multiline = next(e for e in events if "hello" in e["content"]["cmd"])
    assert multiline["content"]["cmd"] == "echo hello \nworld"


def test_parse_respects_since_timestamp(tmp_path: Path) -> None:
    f = _write_history(tmp_path, HISTORY_CONTENT)
    events, max_ts = parse_history(f, since_timestamp=1000000001, hostname="testhost")
    # Only entries with ts > 1000000001 should be included
    assert len(events) == 2
    tss = {int(e["content"]["cmd"] != "") for e in events}  # just check count
    assert max_ts == 1000000003


def test_parse_empty_file(tmp_path: Path) -> None:
    f = _write_history(tmp_path, "")
    events, max_ts = parse_history(f, since_timestamp=0)
    assert events == []
    assert max_ts == 0


def test_parse_nonexistent_file(tmp_path: Path) -> None:
    events, max_ts = parse_history(tmp_path / "missing.txt", since_timestamp=0)
    assert events == []
    assert max_ts == 0


def test_parse_skips_non_extended_lines(tmp_path: Path) -> None:
    content = "plain-command-no-timestamp\n: 1000000099:0;real-cmd\n"
    f = _write_history(tmp_path, content)
    events, _ = parse_history(f, since_timestamp=0)
    assert len(events) == 1
    assert events[0]["content"]["cmd"] == "real-cmd"


def test_parse_sets_ev_type_and_source(tmp_path: Path) -> None:
    f = _write_history(tmp_path, ": 1000000000:0;ls\n")
    events, _ = parse_history(f, since_timestamp=0, hostname="myhost")
    assert events[0]["ev_type"] == "shell-cmd"
    assert events[0]["source_host"] == "myhost"
    assert events[0]["source_app"] == "zsh"


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def test_state_default_zero(tmp_path: Path) -> None:
    s = State(tmp_path / "state.json")
    assert s.last_timestamp == 0


def test_state_persists(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    s = State(path)
    s.last_timestamp = 12345
    # Reload from disk
    s2 = State(path)
    assert s2.last_timestamp == 12345


def test_state_survives_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("NOT JSON{{{")
    s = State(path)
    assert s.last_timestamp == 0


# ---------------------------------------------------------------------------
# EventBuffer
# ---------------------------------------------------------------------------


def test_buffer_add_and_flush(tmp_path: Path) -> None:
    buf = EventBuffer(tmp_path / "buffer.json")
    buf.add([{"a": 1}, {"b": 2}])
    buf.add([{"c": 3}])
    assert len(buf) == 3
    flushed = buf.flush()
    assert len(flushed) == 3
    assert len(buf) == 0


def test_buffer_persists_to_disk(tmp_path: Path) -> None:
    path = tmp_path / "buffer.json"
    buf = EventBuffer(path)
    buf.add([{"x": 42}])
    buf2 = EventBuffer(path)
    assert len(buf2) == 1
    assert buf2.flush()[0] == {"x": 42}


def test_buffer_flush_clears(tmp_path: Path) -> None:
    buf = EventBuffer(tmp_path / "buffer.json")
    buf.add([{"a": 1}])
    buf.flush()
    buf2 = EventBuffer(tmp_path / "buffer.json")
    assert len(buf2) == 0


# ---------------------------------------------------------------------------
# send_events (mocked HTTP)
# ---------------------------------------------------------------------------

FAKE_URL = "http://localhost:9999"
FAKE_TOKEN = "tok"
SAMPLE_EVENTS = [
    {
        "timestamp": "2024-01-01T00:00:00+00:00",
        "ev_type": "shell-cmd",
        "source_host": "host",
        "source_app": "zsh",
        "content": {"cmd": "ls"},
        "tags": [],
    }
]


@respx.mock
def test_send_events_success() -> None:
    respx.post(f"{FAKE_URL}/events/batch").mock(
        return_value=httpx.Response(201, json=[])
    )
    assert send_events(SAMPLE_EVENTS, FAKE_URL, FAKE_TOKEN) is True


@respx.mock
def test_send_empty_events() -> None:
    # No HTTP call should be made for an empty list
    assert send_events([], FAKE_URL, FAKE_TOKEN) is True
    assert not respx.calls


@respx.mock
def test_send_events_failure_exhausts_retries() -> None:
    respx.post(f"{FAKE_URL}/events/batch").mock(
        return_value=httpx.Response(500)
    )
    result = send_events(SAMPLE_EVENTS, FAKE_URL, FAKE_TOKEN, max_retries=2)
    assert result is False
    assert len(respx.calls) == 2


@respx.mock
def test_send_events_connection_error() -> None:
    respx.post(f"{FAKE_URL}/events/batch").mock(
        side_effect=httpx.ConnectError("refused")
    )
    result = send_events(SAMPLE_EVENTS, FAKE_URL, FAKE_TOKEN, max_retries=1)
    assert result is False
