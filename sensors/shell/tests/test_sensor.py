"""Tests for the unified shell history sensor (bash & zsh)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from biograph_sensor_shell.sensor import (
    EventBuffer,
    HistoryHandler,
    State,
    _history_files,
    _max_age_days,
    _server_url,
    _state_dir,
    _token,
    parse_bash_history,
    parse_zsh_history,
    send_events,
)

# ---------------------------------------------------------------------------
# parse_zsh_history
# ---------------------------------------------------------------------------

ZSH_HISTORY_CONTENT = """\
: 1000000000:0;ls -la
: 1000000001:0;git status
: 1000000002:0;echo hello \\
world
: 1000000003:5;cat README.md
"""


def _write_file(tmp_path: Path, filename: str, content: str) -> Path:
    p = tmp_path / filename
    p.write_text(content)
    return p


def test_parse_zsh_basic_entries(tmp_path: Path) -> None:
    f = _write_file(tmp_path, ".zsh_history", ZSH_HISTORY_CONTENT)
    events, max_ts = parse_zsh_history(f, since_timestamp=0, hostname="testhost")
    assert len(events) == 4
    cmds = [e["content"]["cmd"] for e in events]
    assert "ls -la" in cmds
    assert "git status" in cmds
    assert "cat README.md" in cmds
    assert max_ts == 1000000003
    assert events[0]["source_app"] == "zsh"
    assert events[0]["source_host"] == "testhost"
    assert events[0]["ev_type"] == "shell-cmd"


def test_parse_zsh_multiline(tmp_path: Path) -> None:
    f = _write_file(tmp_path, ".zsh_history", ZSH_HISTORY_CONTENT)
    events, _ = parse_zsh_history(f, since_timestamp=0)
    multiline = next(e for e in events if "hello" in e["content"]["cmd"])
    assert multiline["content"]["cmd"] == "echo hello \nworld"


def test_parse_zsh_respects_since_timestamp(tmp_path: Path) -> None:
    f = _write_file(tmp_path, ".zsh_history", ZSH_HISTORY_CONTENT)
    events, max_ts = parse_zsh_history(f, since_timestamp=1000000001)
    assert len(events) == 2
    assert max_ts == 1000000003


def test_parse_zsh_empty_and_missing(tmp_path: Path) -> None:
    empty = _write_file(tmp_path, ".zsh_history", "")
    assert parse_zsh_history(empty, 0) == ([], 0)
    assert parse_zsh_history(tmp_path / "missing", 0) == ([], 0)


# ---------------------------------------------------------------------------
# parse_bash_history
# ---------------------------------------------------------------------------

BASH_HISTORY_CONTENT = """\
# un-timestamped command before HISTTIMEFORMAT was turned on
legacy-command
#1000000000
ls -la
#1000000001
git status
#1000000002
echo "multi-line
command here"
#1000000003
cat README.md
"""


def test_parse_bash_basic_entries(tmp_path: Path) -> None:
    f = _write_file(tmp_path, ".bash_history", BASH_HISTORY_CONTENT)
    events, max_ts = parse_bash_history(f, since_timestamp=0, hostname="testhost")
    assert len(events) == 4
    cmds = [e["content"]["cmd"] for e in events]
    assert "ls -la" in cmds
    assert "git status" in cmds
    assert 'echo "multi-line\ncommand here"' in cmds
    assert "cat README.md" in cmds
    assert max_ts == 1000000003
    assert events[0]["source_app"] == "bash"
    assert events[0]["source_host"] == "testhost"
    assert events[0]["ev_type"] == "shell-cmd"


def test_parse_bash_respects_since_timestamp(tmp_path: Path) -> None:
    f = _write_file(tmp_path, ".bash_history", BASH_HISTORY_CONTENT)
    events, max_ts = parse_bash_history(f, since_timestamp=1000000001)
    assert len(events) == 2
    assert max_ts == 1000000003


def test_parse_bash_empty_and_missing(tmp_path: Path) -> None:
    empty = _write_file(tmp_path, ".bash_history", "")
    assert parse_bash_history(empty, 0) == ([], 0)
    assert parse_bash_history(tmp_path / "missing", 0) == ([], 0)


def test_parse_bash_non_timestamp_comments(tmp_path: Path) -> None:
    content = """\
#1000000000
# this is a code comment line
cargo check
#1000000001
pwd
"""
    f = _write_file(tmp_path, ".bash_history", content)
    events, max_ts = parse_bash_history(f, since_timestamp=0)
    assert len(events) == 2
    assert events[0]["content"]["cmd"] == "# this is a code comment line\ncargo check"
    assert events[1]["content"]["cmd"] == "pwd"
    assert max_ts == 1000000001


# ---------------------------------------------------------------------------
# State & Legacy Migration
# ---------------------------------------------------------------------------


def test_state_roundtrip(tmp_path: Path) -> None:
    state_file = tmp_path / "shell-state.json"
    state = State(state_file)
    assert state.get_last_timestamp("bash") == 0
    assert state.get_last_timestamp("zsh") == 0

    state.set_last_timestamp("bash", 12345)
    state.set_last_timestamp("zsh", 67890)

    # Re-read
    state2 = State(state_file)
    assert state2.get_last_timestamp("bash") == 12345
    assert state2.get_last_timestamp("zsh") == 67890


def test_state_migrates_legacy_zsh_state(tmp_path: Path) -> None:
    # Setup legacy zsh-state.json
    legacy_file = tmp_path / "zsh-state.json"
    legacy_file.write_text(json.dumps({"last_timestamp": 987654321}))

    shell_state_file = tmp_path / "shell-state.json"
    state = State(shell_state_file)

    assert state.get_last_timestamp("zsh") == 987654321
    assert state.get_last_timestamp("bash") == 0
    assert shell_state_file.exists()


# ---------------------------------------------------------------------------
# EventBuffer & Legacy Migration
# ---------------------------------------------------------------------------


def test_buffer_add_and_flush(tmp_path: Path) -> None:
    buf_file = tmp_path / "shell-buffer.json"
    buf = EventBuffer(buf_file)
    assert len(buf) == 0

    buf.add([{"content": {"cmd": "foo"}}])
    assert len(buf) == 1

    # Reload from disk
    buf2 = EventBuffer(buf_file)
    assert len(buf2) == 1
    events = buf2.flush()
    assert len(events) == 1
    assert events[0]["content"]["cmd"] == "foo"
    assert len(buf2) == 0


def test_buffer_migrates_legacy_zsh_buffer(tmp_path: Path) -> None:
    legacy_file = tmp_path / "zsh-buffer.json"
    legacy_file.write_text(json.dumps([{"content": {"cmd": "buffered_zsh_cmd"}}]))

    buf_file = tmp_path / "shell-buffer.json"
    buf = EventBuffer(buf_file)
    assert len(buf) == 1
    events = buf.flush()
    assert events[0]["content"]["cmd"] == "buffered_zsh_cmd"


# ---------------------------------------------------------------------------
# send_events
# ---------------------------------------------------------------------------


@respx.mock
def test_send_events_success(respx_mock: respx.MockRouter) -> None:
    respx_mock.post("http://testserver/events/batch").respond(status_code=200, json={"status": "ok"})
    ev = [{"content": {"cmd": "ls"}}]
    assert send_events(ev, "http://testserver", "test-token") is True


@respx.mock
def test_send_events_retries_on_failure(respx_mock: respx.MockRouter) -> None:
    respx_mock.post("http://testserver/events/batch").respond(status_code=500)
    ev = [{"content": {"cmd": "ls"}}]
    assert send_events(ev, "http://testserver", "test-token", max_retries=2) is False


def test_send_events_empty() -> None:
    assert send_events([], "http://testserver", "tok") is True


# ---------------------------------------------------------------------------
# HistoryHandler integration
# ---------------------------------------------------------------------------


@respx.mock
def test_history_handler_processes_both_shells(
    respx_mock: respx.MockRouter, tmp_path: Path
) -> None:
    respx_mock.post("http://testserver/events/batch").respond(status_code=200, json={"status": "ok"})

    bash_hist = _write_file(tmp_path, ".bash_history", "#1000000010\necho bash_cmd\n")
    zsh_hist = _write_file(tmp_path, ".zsh_history", ": 1000000020:0;echo zsh_cmd\n")

    state = State(tmp_path / "shell-state.json")
    buffer = EventBuffer(tmp_path / "shell-buffer.json")

    handler = HistoryHandler(
        {"bash": bash_hist, "zsh": zsh_hist},
        state,
        buffer,
        "http://testserver",
        "secret",
        hostname="my-host",
    )

    handler.process_initial()

    assert state.get_last_timestamp("bash") == 1000000010
    assert state.get_last_timestamp("zsh") == 1000000020
    assert len(buffer) == 0


# ---------------------------------------------------------------------------
# Config helpers & legacy fallback
# ---------------------------------------------------------------------------


def test_config_helpers_with_shell_section() -> None:
    cfg = {
        "server": {"url": "http://127.0.0.1:9000/", "token": "abc"},
        "shell": {
            "bash_history": "~/custom_bash",
            "zsh_history": "~/custom_zsh",
            "state_dir": "/tmp/state",
            "max_age_days": 14,
        },
    }
    assert _server_url(cfg) == "http://127.0.0.1:9000"
    assert _token(cfg) == "abc"
    files = _history_files(cfg)
    assert files["bash"] == Path("~/custom_bash").expanduser()
    assert files["zsh"] == Path("~/custom_zsh").expanduser()
    assert _state_dir(cfg) == Path("/tmp/state")
    assert _max_age_days(cfg) == 14


def test_config_helpers_fallback_to_zsh_section() -> None:
    cfg = {
        "zsh": {
            "history_file": "~/legacy_zsh",
            "state_dir": "/tmp/legacy_state",
            "max_age_days": 7,
        }
    }
    files = _history_files(cfg)
    assert files["zsh"] == Path("~/legacy_zsh").expanduser()
    assert files["bash"] == Path("~/.bash_history").expanduser()
    assert _state_dir(cfg) == Path("/tmp/legacy_state")
    assert _max_age_days(cfg) == 7
