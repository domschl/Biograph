"""Biograph zsh history sensor.

Watches ``~/.zsh_history`` (EXTENDED_HISTORY format) for changes and POSTs
new ``shell-cmd`` events to the Biograph backend.

Cross-platform:
  Linux  — inotify via watchdog's default Observer
  macOS  — FSEvents via watchdog's default Observer

State and buffer are stored under ``~/.local/share/biograph/`` by default.
The config file is the same ``config.toml`` as used by the backend (sensors
only read ``[server]`` and ``[zsh]`` sections).
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import time
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_PATHS: list[Path] = [
    Path("config.toml"),
    Path.home() / ".config" / "biograph" / "config.toml",
    Path("/etc/biograph/config.toml"),
]
_DEFAULT_STATE_DIR = Path.home() / ".local" / "share" / "biograph"
_DEFAULT_MAX_AGE_DAYS = 30  # on first run, only import the last N days


def _ensure_user_config_dir() -> None:
    user_dir = Path.home() / ".config" / "biograph"
    user_example = user_dir / "config.example.toml"
    if not user_example.exists():
        try:
            user_dir.mkdir(parents=True, exist_ok=True)
            example_content = """# Biograph Configuration

[server]
url   = "http://127.0.0.1:8000"  # URL of the Biograph backend
token = "change-me"              # Authorization token

[cli]
# source_host = "my-hostname"    # Optional override for the hostname reported by bio CLI

[zsh]
# history_file = "~/.zsh_history" # Path to zsh history file
# state_dir    = "~/.local/share/biograph" # Directory for sensor state and buffer
# max_age_days = 30              # On first run, import history from last N days
"""
            user_example.write_text(example_content, encoding="utf-8")
        except OSError:
            pass


def _load_config() -> dict[str, Any]:
    _ensure_user_config_dir()
    if env := os.environ.get("BIOGRAPH_CONFIG"):
        candidates: list[Path] = [Path(env)]
    else:
        candidates = _DEFAULT_CONFIG_PATHS
    for c in candidates:
        if c.exists():
            with open(c, "rb") as fh:
                return tomllib.load(fh)
    return {}



def _server_url(config: dict[str, Any]) -> str:
    server = config.get("server", {})
    if url := server.get("url"):
        return url.rstrip("/")
    host = server.get("host", "127.0.0.1")
    port = server.get("port", 8000)
    return f"http://{host}:{port}"


def _token(config: dict[str, Any]) -> str:
    return config.get("server", {}).get("token", "change-me")


def _history_file(config: dict[str, Any]) -> Path:
    raw = config.get("zsh", {}).get("history_file", "~/.zsh_history")
    return Path(raw).expanduser()


def _state_dir(config: dict[str, Any]) -> Path:
    raw = config.get("zsh", {}).get("state_dir", str(_DEFAULT_STATE_DIR))
    p = Path(raw).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _max_age_days(config: dict[str, Any]) -> int:
    return int(config.get("zsh", {}).get("max_age_days", _DEFAULT_MAX_AGE_DAYS))


# ---------------------------------------------------------------------------
# Persistent state
# ---------------------------------------------------------------------------


class State:
    """Persists the last-seen zsh history timestamp to disk."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._data, indent=2))

    @property
    def last_timestamp(self) -> int:
        return int(self._data.get("last_timestamp", 0))

    @last_timestamp.setter
    def last_timestamp(self, value: int) -> None:
        self._data["last_timestamp"] = value
        self._save()


# ---------------------------------------------------------------------------
# Offline event buffer
# ---------------------------------------------------------------------------


class EventBuffer:
    """Stores unsent events on disk so they survive process restarts."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._events: list[dict[str, Any]] = self._load()

    def _load(self) -> list[dict[str, Any]]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return []

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._events, indent=2))

    def add(self, events: list[dict[str, Any]]) -> None:
        self._events.extend(events)
        self._save()

    def flush(self) -> list[dict[str, Any]]:
        """Remove and return all buffered events."""
        evts = list(self._events)
        self._events.clear()
        self._save()
        return evts

    def __len__(self) -> int:
        return len(self._events)


# ---------------------------------------------------------------------------
# zsh EXTENDED_HISTORY parser
# ---------------------------------------------------------------------------


def parse_history(
    history_file: Path,
    since_timestamp: int,
    *,
    hostname: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Parse zsh EXTENDED_HISTORY entries newer than *since_timestamp*.

    Format::

        : <unix_ts>:<elapsed>;<command>

    Multi-line commands have continuation lines ending with ``\\``.

    Returns ``(events, max_timestamp)`` where *max_timestamp* is the highest
    timestamp seen in this batch (or *since_timestamp* if nothing new).
    """
    try:
        text = history_file.read_bytes().decode("utf-8", errors="replace")
    except OSError as exc:
        logger.error("Cannot read history file: %s", exc)
        return [], since_timestamp

    if hostname is None:
        hostname = socket.gethostname()

    events: list[dict[str, Any]] = []
    max_ts = since_timestamp
    lines = text.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i]

        # EXTENDED_HISTORY lines start with ": "
        if not line.startswith(": "):
            i += 1
            continue

        try:
            meta, _, cmd_start = line[2:].partition(";")
            ts_str, _, _ = meta.partition(":")
            ts = int(ts_str)
        except (ValueError, AttributeError):
            i += 1
            continue

        # Collect backslash-newline continuations
        parts = [cmd_start]
        while parts[-1].endswith("\\") and i + 1 < len(lines):
            parts[-1] = parts[-1][:-1]  # strip trailing backslash
            i += 1
            parts.append(lines[i])

        cmd = "\n".join(parts).strip()

        if ts > since_timestamp and cmd:
            events.append(
                {
                    "timestamp": datetime.fromtimestamp(ts, UTC).isoformat(),
                    "ev_type": "shell-cmd",
                    "source_host": hostname,
                    "source_app": "zsh",
                    "content": {"cmd": cmd},
                    "tags": [],
                }
            )
            max_ts = max(max_ts, ts)

        i += 1

    return events, max_ts


# ---------------------------------------------------------------------------
# HTTP sender with exponential backoff
# ---------------------------------------------------------------------------


def send_events(
    events: list[dict[str, Any]],
    server_url: str,
    token: str,
    *,
    max_retries: int = 5,
) -> bool:
    """POST *events* to ``/events/batch``.  Returns ``True`` on success."""
    if not events:
        return True

    headers = {"Authorization": f"Bearer {token}"}
    endpoint = f"{server_url}/events/batch"
    delay = 1.0

    for attempt in range(max_retries):
        try:
            resp = httpx.post(endpoint, json=events, headers=headers, timeout=15)
            resp.raise_for_status()
            return True
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.warning(
                "Send attempt %d/%d failed: %s", attempt + 1, max_retries, exc
            )
            if attempt < max_retries - 1:
                time.sleep(delay)
                delay = min(delay * 2, 60)

    return False


# ---------------------------------------------------------------------------
# File-system event handler
# ---------------------------------------------------------------------------


class HistoryHandler(FileSystemEventHandler):
    def __init__(
        self,
        history_file: Path,
        state: State,
        buffer: EventBuffer,
        server_url: str,
        token: str,
        hostname: str | None = None,
    ) -> None:
        super().__init__()
        self._history_file = history_file.resolve()
        self._state = state
        self._buffer = buffer
        self._server_url = server_url
        self._token = token
        self._hostname = hostname

    def on_modified(self, event: FileSystemEvent) -> None:
        # watchdog may emit directory events too — filter to our file
        if Path(str(event.src_path)).resolve() != self._history_file:
            return
        self._process()

    def process_initial(self) -> None:
        """Called once at startup to catch up on history written while offline."""
        self._process()

    def _process(self) -> None:
        new_events, max_ts = parse_history(
            self._history_file, self._state.last_timestamp, self._hostname
        )

        if not new_events and not self._buffer:
            return

        # Prepend any buffered events, then try to send everything
        buffered = self._buffer.flush()
        all_events = buffered + new_events

        if send_events(all_events, self._server_url, self._token):
            if max_ts > self._state.last_timestamp:
                self._state.last_timestamp = max_ts
            logger.info("Sent %d event(s) (%d buffered)", len(new_events), len(buffered))
        else:
            # Put everything back
            self._buffer.add(all_events)
            logger.warning(
                "Backend unreachable — buffered %d event(s) (total: %d)",
                len(all_events),
                len(self._buffer),
            )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [biograph-zsh] %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stderr,
    )

    config = _load_config()
    server_url = _server_url(config)
    token = _token(config)
    history_file = _history_file(config)
    state_dir = _state_dir(config)
    max_age = _max_age_days(config)

    if not history_file.exists():
        logger.error("History file not found: %s", history_file)
        logger.error("Enable zsh EXTENDED_HISTORY and ensure the file exists.")
        sys.exit(1)

    state = State(state_dir / "zsh-state.json")
    buffer = EventBuffer(state_dir / "zsh-buffer.json")

    # On first run, limit history import to the last N days so we don't flood
    # the backend with years of history.
    if state.last_timestamp == 0:
        cutoff = int((datetime.now(UTC) - timedelta(days=max_age)).timestamp())
        logger.info(
            "First run: importing history from the last %d days (since %s)",
            max_age,
            datetime.fromtimestamp(cutoff, UTC).date(),
        )
        state.last_timestamp = cutoff

    hostname = config.get("zsh", {}).get("source_host") or config.get("zsh", {}).get("hostname")
    handler = HistoryHandler(history_file, state, buffer, server_url, token, hostname)

    # Initial catch-up pass
    handler.process_initial()

    # Start file-system watcher (inotify on Linux, FSEvents on macOS)
    observer = Observer()
    observer.schedule(handler, str(history_file.parent), recursive=False)
    observer.start()
    logger.info(
        "Watching %s → %s  (buffered: %d)",
        history_file,
        server_url,
        len(buffer),
    )

    try:
        while observer.is_alive():
            observer.join(timeout=1)
    except KeyboardInterrupt:
        logger.info("Shutting down.")
    finally:
        observer.stop()
        observer.join()

