"""Biograph unified shell history sensor (bash & zsh).

Watches shell history files (~/.bash_history and ~/.zsh_history) for changes
and POSTs new ``shell-cmd`` events to the Biograph backend.

Cross-platform:
  Linux  — inotify via watchdog's default Observer
  macOS  — FSEvents via watchdog's default Observer

State and buffer are stored under ``~/.local/share/biograph/`` by default.
The config file is the same ``config.toml`` as used by the backend and CLI
(sensors read the ``[server]`` and ``[shell]`` sections, with fallback to ``[zsh]``).
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import threading
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

[shell]
# bash_history = "~/.bash_history" # Path to bash history file
# zsh_history  = "~/.zsh_history"  # Path to zsh history file
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


def _history_files(config: dict[str, Any]) -> dict[str, Path]:
    shell_cfg = config.get("shell") or {}
    zsh_cfg = config.get("zsh") or {}

    bash_path = shell_cfg.get("bash_history", "~/.bash_history")
    zsh_path = shell_cfg.get("zsh_history", zsh_cfg.get("history_file", "~/.zsh_history"))

    return {
        "bash": Path(bash_path).expanduser(),
        "zsh": Path(zsh_path).expanduser(),
    }


def _state_dir(config: dict[str, Any]) -> Path:
    shell_cfg = config.get("shell") or {}
    zsh_cfg = config.get("zsh") or {}
    raw = shell_cfg.get("state_dir", zsh_cfg.get("state_dir", str(_DEFAULT_STATE_DIR)))
    p = Path(raw).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _max_age_days(config: dict[str, Any]) -> int:
    shell_cfg = config.get("shell") or {}
    zsh_cfg = config.get("zsh") or {}
    val = shell_cfg.get("max_age_days", zsh_cfg.get("max_age_days", _DEFAULT_MAX_AGE_DAYS))
    return int(val)


# ---------------------------------------------------------------------------
# Persistent state
# ---------------------------------------------------------------------------


class State:
    """Persists the last-seen history timestamps per shell to disk."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, Any] = self._load_and_migrate()

    def _load_and_migrate(self) -> dict[str, Any]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError):
                return {}

        # Migration from legacy zsh-state.json
        legacy_path = self._path.parent / "zsh-state.json"
        if legacy_path.exists():
            try:
                legacy_data = json.loads(legacy_path.read_text())
                last_ts = int(legacy_data.get("last_timestamp", 0))
                if last_ts > 0:
                    logger.info(
                        "Migrated legacy zsh-state.json (last_timestamp=%d) to shell-state.json",
                        last_ts,
                    )
                    migrated = {"zsh": last_ts}
                    self._path.write_text(json.dumps(migrated, indent=2))
                    return migrated
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not migrate legacy zsh-state.json: %s", exc)

        return {}

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._data, indent=2))

    def get_last_timestamp(self, shell: str) -> int:
        return int(self._data.get(shell, 0))

    def set_last_timestamp(self, shell: str, value: int) -> None:
        self._data[shell] = value
        self._save()


# ---------------------------------------------------------------------------
# Offline event buffer
# ---------------------------------------------------------------------------


class EventBuffer:
    """Stores unsent events on disk so they survive process restarts."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._events: list[dict[str, Any]] = self._load_and_migrate()

    def _load_and_migrate(self) -> list[dict[str, Any]]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except (json.JSONDecodeError, OSError):
                return []

        # Migration from legacy zsh-buffer.json
        legacy_path = self._path.parent / "zsh-buffer.json"
        if legacy_path.exists():
            try:
                legacy_events = json.loads(legacy_path.read_text())
                if isinstance(legacy_events, list) and legacy_events:
                    logger.info(
                        "Migrated %d buffered events from legacy zsh-buffer.json to shell-buffer.json",
                        len(legacy_events),
                    )
                    self._path.write_text(json.dumps(legacy_events, indent=2))
                    return legacy_events
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not migrate legacy zsh-buffer.json: %s", exc)

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
# History parsers
# ---------------------------------------------------------------------------


def parse_zsh_history(
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
        logger.error("Cannot read zsh history file: %s", exc)
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


def parse_bash_history(
    history_file: Path,
    since_timestamp: int,
    *,
    hostname: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Parse bash history entries with timestamps newer than *since_timestamp*.

    Format::

        #<unix_ts>
        <command line 1>
        <command line 2...>

    Returns ``(events, max_timestamp)``.
    """
    try:
        text = history_file.read_bytes().decode("utf-8", errors="replace")
    except OSError as exc:
        logger.error("Cannot read bash history file: %s", exc)
        return [], since_timestamp

    if hostname is None:
        hostname = socket.gethostname()

    events: list[dict[str, Any]] = []
    max_ts = since_timestamp
    lines = text.splitlines()

    current_ts: int | None = None
    current_lines: list[str] = []

    def commit_entry() -> None:
        nonlocal max_ts
        if current_ts is None:
            return
        cmd = "\n".join(current_lines).strip()
        if current_ts > since_timestamp and cmd:
            events.append(
                {
                    "timestamp": datetime.fromtimestamp(current_ts, UTC).isoformat(),
                    "ev_type": "shell-cmd",
                    "source_host": hostname,
                    "source_app": "bash",
                    "content": {"cmd": cmd},
                    "tags": [],
                }
            )
            max_ts = max(max_ts, current_ts)

    for line in lines:
        stripped = line.strip()
        # Bash timestamp comment: line starts with '#' followed by digits (valid unix timestamp)
        if stripped.startswith("#") and stripped[1:].isdigit() and len(stripped[1:]) >= 9:
            commit_entry()
            current_ts = int(stripped[1:])
            current_lines = []
        elif current_ts is not None:
            current_lines.append(line)

    # Commit any trailing command
    commit_entry()

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
    """POST *events* to ``/events/batch``. Returns ``True`` on success."""
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
        history_files: dict[str, Path],
        state: State,
        buffer: EventBuffer,
        server_url: str,
        token: str,
        hostname: str | None = None,
    ) -> None:
        super().__init__()
        self._history_files = {k: v.resolve() for k, v in history_files.items()}
        self._state = state
        self._buffer = buffer
        self._server_url = server_url
        self._token = token
        self._hostname = hostname
        self._lock = threading.Lock()

    def on_modified(self, event: FileSystemEvent) -> None:
        try:
            src = Path(str(event.src_path)).resolve()
        except OSError:
            return

        for shell, path in self._history_files.items():
            if src == path:
                self.process_shell(shell)

    def process_initial(self) -> None:
        """Called once at startup to catch up on history written while offline."""
        for shell in self._history_files:
            self.process_shell(shell)

    def process_shell(self, shell: str) -> None:
        history_file = self._history_files.get(shell)
        if not history_file or not history_file.exists():
            return

        with self._lock:
            last_ts = self._state.get_last_timestamp(shell)
            if shell == "bash":
                new_events, max_ts = parse_bash_history(
                    history_file, last_ts, hostname=self._hostname
                )
            elif shell == "zsh":
                new_events, max_ts = parse_zsh_history(
                    history_file, last_ts, hostname=self._hostname
                )
            else:
                logger.warning("Unknown shell type: %s", shell)
                return

            if not new_events and not self._buffer:
                return

            # Prepend any buffered events, then try to send everything
            buffered = self._buffer.flush()
            all_events = buffered + new_events

            if send_events(all_events, self._server_url, self._token):
                if max_ts > last_ts:
                    self._state.set_last_timestamp(shell, max_ts)
                logger.info(
                    "[%s] Sent %d event(s) (%d buffered)",
                    shell,
                    len(new_events),
                    len(buffered),
                )
            else:
                # Put everything back into local persistent buffer
                self._buffer.add(all_events)
                if max_ts > last_ts:
                    self._state.set_last_timestamp(shell, max_ts)
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
        format="%(asctime)s [biograph-shell] %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stderr,
    )

    config = _load_config()
    server_url = _server_url(config)
    token = _token(config)
    history_files = _history_files(config)
    state_dir = _state_dir(config)
    max_age = _max_age_days(config)

    active_files = {
        shell: path for shell, path in history_files.items() if path.exists()
    }

    if not active_files:
        logger.warning(
            "Neither bash history (%s) nor zsh history (%s) found.",
            history_files.get("bash"),
            history_files.get("zsh"),
        )
        logger.info(
            "The sensor will monitor parent directories and activate when history files are created."
        )

    state = State(state_dir / "shell-state.json")
    buffer = EventBuffer(state_dir / "shell-buffer.json")

    # On first run for a shell, limit history import to the last N days so we don't
    # flood the backend with years of history.
    cutoff = int((datetime.now(UTC) - timedelta(days=max_age)).timestamp())
    for shell, path in history_files.items():
        if path.exists() and state.get_last_timestamp(shell) == 0:
            logger.info(
                "First run for %s: importing history from the last %d days (since %s)",
                shell,
                max_age,
                datetime.fromtimestamp(cutoff, UTC).date(),
            )
            state.set_last_timestamp(shell, cutoff)

    hostname = (
        config.get("shell", {}).get("source_host")
        or config.get("shell", {}).get("hostname")
        or config.get("zsh", {}).get("source_host")
        or config.get("zsh", {}).get("hostname")
        or config.get("source_host")
    )
    handler = HistoryHandler(history_files, state, buffer, server_url, token, hostname)

    # Initial catch-up pass
    handler.process_initial()

    # Start file-system watcher (inotify on Linux, FSEvents on macOS)
    observer = Observer()
    watched_dirs: set[Path] = set()
    for path in history_files.values():
        parent = path.parent.resolve()
        if parent.exists() and parent not in watched_dirs:
            observer.schedule(handler, str(parent), recursive=False)
            watched_dirs.add(parent)

    observer.start()
    shells_desc = ", ".join(
        f"{s}: {p} ({'active' if p.exists() else 'not found'})"
        for s, p in history_files.items()
    )
    logger.info(
        "Watching [%s] → %s  (buffered: %d)",
        shells_desc,
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


if __name__ == "__main__":
    main()
