"""bio — Biograph command-line logger and query tool.

Usage examples::

    bio log "Had a great hike" --tags outdoor,health
    bio log --mood happy "Finished reading Dune"
    bio log                         # opens $EDITOR (fallback: nano)
    bio search "hiking" --limit 10
    bio search "git" --type shell-cmd --from 2024-01-01

Config is read from (first found):
  1. $BIOGRAPH_CONFIG environment variable
  2. ./config.toml
  3. ~/.config/biograph/config.toml
  4. /etc/biograph/config.toml
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import typer
from rich.console import Console
from rich.table import Table

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="bio",
    help="Biograph life-logger — record and query life events.",
    no_args_is_help=True,
)
console = Console()
err = Console(stderr=True)

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_PATHS: list[Path] = [
    Path("config.toml"),
    Path.home() / ".config" / "biograph" / "config.toml",
    Path("/etc/biograph/config.toml"),
]


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


def _source_host(config: dict[str, Any]) -> str:
    return (
        config.get("cli", {}).get("source_host")
        or config.get("source_host")
        or socket.gethostname()
    )


def _server_url(config: dict[str, Any]) -> str:
    server = config.get("server", {})
    if url := server.get("url"):
        return url.rstrip("/")
    host = server.get("host", "127.0.0.1")
    port = server.get("port", 8000)
    return f"http://{host}:{port}"


def _token(config: dict[str, Any]) -> str:
    return config.get("server", {}).get("token", "change-me")


def _http_client(config: dict[str, Any]) -> httpx.Client:
    return httpx.Client(
        base_url=_server_url(config),
        headers={"Authorization": f"Bearer {_token(config)}"},
        timeout=15,
    )


# ---------------------------------------------------------------------------
# Editor helper
# ---------------------------------------------------------------------------

_EDITOR_PLACEHOLDER = "# bio log — write your note below, save and exit editor\n\n"


def _open_editor() -> str:
    """Open $EDITOR (or nano) and return the text the user saved."""
    editor = (
        os.environ.get("EDITOR")
        or os.environ.get("VISUAL")
        or "nano"
    )
    with tempfile.NamedTemporaryFile(
        suffix=".md", mode="w", delete=False, encoding="utf-8"
    ) as fh:
        tmp = Path(fh.name)
        fh.write(_EDITOR_PLACEHOLDER)

    try:
        result = subprocess.run([editor, str(tmp)])
        if result.returncode != 0:
            err.print(f"[yellow]Editor exited with code {result.returncode}.[/yellow]")
            return ""
        raw = tmp.read_text(encoding="utf-8")
        # Strip the placeholder comment lines
        lines = [
            ln for ln in raw.splitlines()
            if not ln.startswith("# bio log")
        ]
        return "\n".join(lines).strip()
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# log
# ---------------------------------------------------------------------------


@app.command()
def log(
    message: str | None = typer.Argument(
        default=None,
        help="Note text. Omit to open $EDITOR.",
    ),
    tags: str | None = typer.Option(
        None, "--tags", "-t",
        help="Comma-separated tags, e.g. health,outdoor.",
    ),
    mood: str | None = typer.Option(
        None, "--mood", "-m",
        help="Optional mood annotation (any string).",
    ),
    ev_type: str = typer.Option(
        "note", "--type",
        help="Event type (default: note).",
    ),
) -> None:
    """Create a new event.

    If MESSAGE is omitted the default editor ($EDITOR or nano) is opened;
    the saved buffer becomes the note text.
    """
    if message is None:
        message = _open_editor()

    if not message:
        err.print("[yellow]Empty message — nothing recorded.[/yellow]")
        raise typer.Exit(1)

    tag_list = [t.strip() for t in tags.split(",")] if tags else []

    content: dict[str, Any] = {"text": message}
    if mood:
        content["mood"] = mood

    config = _load_config()
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "ev_type": ev_type,
        "source_host": _source_host(config),
        "source_app": "bio",
        "content": content,
        "tags": tag_list,
    }
    with _http_client(config) as http:
        try:
            resp = http.post("/events/", json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            err.print(f"[red]Server error {exc.response.status_code}:[/red] {exc.response.text}")
            raise typer.Exit(1)
        except httpx.RequestError as exc:
            err.print(f"[red]Connection error:[/red] {exc}")
            raise typer.Exit(1)

    data = resp.json()
    console.print(
        f"[green]✓[/green] Event [bold]#{data['id']}[/bold] recorded "
        f"([dim]{data['ev_type']}[/dim])"
    )


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


@app.command()
def search(
    query: str = typer.Argument(help="Full-text search query."),
    from_date: str | None = typer.Option(
        None, "--from",
        help="Start date/time (ISO 8601).",
    ),
    to_date: str | None = typer.Option(
        None, "--to",
        help="End date/time (ISO 8601).",
    ),
    ev_type: list[str] | None = typer.Option(
        None, "--type",
        help="Filter by event type (repeatable).",
    ),
    tag: list[str] | None = typer.Option(
        None, "--tag",
        help="Filter by tag (repeatable, AND semantics).",
    ),
    limit: int = typer.Option(
        20, "--limit", "-n",
        help="Max results to show.",
    ),
    offset: int = typer.Option(
        0, "--offset",
        help="Pagination offset.",
    ),
) -> None:
    """Search events by full-text query with optional filters."""
    params: dict[str, Any] = {"q": query, "limit": limit, "offset": offset}
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    if ev_type:
        params["ev_type"] = ev_type
    if tag:
        params["tags"] = tag

    config = _load_config()
    with _http_client(config) as http:
        try:
            resp = http.get("/events/", params=params)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            err.print(f"[red]Server error {exc.response.status_code}:[/red] {exc.response.text}")
            raise typer.Exit(1)
        except httpx.RequestError as exc:
            err.print(f"[red]Connection error:[/red] {exc}")
            raise typer.Exit(1)

    data = resp.json()
    items = data["items"]
    total = data["total"]

    if not items:
        console.print("[yellow]No results.[/yellow]")
        return

    table = Table(show_header=True, header_style="bold cyan", expand=True)
    table.add_column("ID", style="dim", width=6, no_wrap=True)
    table.add_column("Timestamp", width=19, no_wrap=True)
    table.add_column("Type", width=14, no_wrap=True)
    table.add_column("Tags", width=18)
    table.add_column("Content / Summary")

    for item in items:
        ts = item["timestamp"][:19].replace("T", " ")
        tag_str = ", ".join(item.get("tags") or []) or "[dim]—[/dim]"
        summary = (
            item.get("summary")
            or item["content"].get("text")
            or item["content"].get("cmd")
            or str(item["content"])
        )
        if len(summary) > 70:
            summary = summary[:67] + "…"
        table.add_row(str(item["id"]), ts, item["ev_type"], tag_str, summary)

    console.print(table)
    shown = offset + len(items)
    console.print(
        f"\n[dim]Showing {offset + 1}–{shown} of {total} result(s)[/dim]"
    )



# ---------------------------------------------------------------------------
# Kindle clippings parser helper
# ---------------------------------------------------------------------------


def parse_kindle_date(date_str: str) -> datetime | None:
    date_str = re.sub(r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*", "", date_str)
    date_str = re.sub(r"\bde\b", "", date_str)
    date_str = re.sub(r"\s+", " ", date_str).strip()
    
    formats = [
        "%d %B %Y %H:%M:%S",      # 15 October 2022 13:45:22
        "%B %d, %Y %I:%M:%S %p",  # October 15, 2022 1:45:22 PM
        "%d %b %Y %H:%M:%S",      # 15 Oct 2022 13:45:22
        "%d. %B %Y %H:%M:%S",     # 15. Oktober 2022 13:45:22
        "%d %B %Y %I:%M:%S %p",
        "%B %d, %Y %H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def parse_clippings(content: str) -> list[dict[str, Any]]:
    raw_blocks = content.split("==========")
    parsed_items = []
    
    for raw_block in raw_blocks:
        lines = [line.strip() for line in raw_block.splitlines() if line.strip()]
        if len(lines) < 3:
            continue
            
        title_author = lines[0]
        metadata = lines[1]
        content_lines = lines[2:]
        highlight_text = " ".join(content_lines)
        
        if title_author.endswith(")"):
            idx = title_author.rfind("(")
            if idx != -1:
                book_title = title_author[:idx].strip()
                author = title_author[idx+1:-1].strip()
            else:
                book_title = title_author
                author = "Unknown"
        else:
            book_title = title_author
            author = "Unknown"
            
        location = None
        location_match = re.search(r"Location (\d+)", metadata)
        if location_match:
            location = int(location_match.group(1))
            
        timestamp = datetime.now(UTC).isoformat()
        for part in metadata.split("|"):
            part = part.strip()
            if part.startswith("Added on "):
                date_str = part.replace("Added on ", "").strip()
                parsed_dt = parse_kindle_date(date_str)
                if parsed_dt:
                    timestamp = parsed_dt.astimezone(UTC).isoformat()
                    
        is_highlight = "Highlight" in metadata
        
        parsed_items.append({
            "book_title": book_title,
            "author": author,
            "highlight": highlight_text,
            "location": location,
            "timestamp": timestamp,
            "is_highlight": is_highlight
        })
        
    return parsed_items


def calculate_clipping_hash(book_title: str, author: str, highlight: str, location: int | None) -> str:
    hasher = hashlib.sha256()
    hasher.update(book_title.encode("utf-8"))
    hasher.update(author.encode("utf-8"))
    hasher.update(highlight.encode("utf-8"))
    hasher.update(str(location).encode("utf-8"))
    return hasher.hexdigest()


def _load_kindle_state() -> dict[str, Any]:
    state_file = Path.home() / ".local" / "share" / "biograph" / "kindle_state.json"
    if state_file.exists():
        try:
            with open(state_file, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"sent_hashes": [], "sent_books": []}


def _save_kindle_state(state: dict[str, Any]) -> None:
    state_file = Path.home() / ".local" / "share" / "biograph" / "kindle_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)


# ---------------------------------------------------------------------------
# Kindle import command
# ---------------------------------------------------------------------------


@app.command()
def kindle(
    path: Path = typer.Argument(
        ...,
        help="Path to Kindle mountpoint directory or directly to the clippings file (e.g. My Clippings.txt).",
    ),
) -> None:
    """Import books and highlights from a mounted Kindle device or local clippings file."""
    clippings_file = None
    if path.is_file():
        clippings_file = path
    elif path.is_dir():
        clippings_file = path / "documents" / "My Clippings.txt"
        if not clippings_file.exists():
            clippings_file = path / "My Clippings.txt"
    else:
        err.print(f"[red]Error:[/red] '{path}' is neither a file nor a directory.")
        raise typer.Exit(1)
        
    if not clippings_file or not clippings_file.exists():
        err.print(f"[red]Error:[/red] Could not find clippings file at '{path}'.")
        raise typer.Exit(1)
        
    try:
        content = clippings_file.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        try:
            content = clippings_file.read_text(encoding="latin-1")
        except Exception as e:
            err.print(f"[red]Error reading clippings file:[/red] {e}")
            raise typer.Exit(1)
            
    items = parse_clippings(content)
    if not items:
        console.print("[yellow]No valid clippings found in the file.[/yellow]")
        return
        
    state = _load_kindle_state()
    sent_hashes = set(state.get("sent_hashes", []))
    sent_books = set(state.get("sent_books", []))
    
    events_to_send = []
    new_books_to_track = []
    new_hashes_to_track = []
    
    for item in items:
        book_key = item["book_title"]
        if book_key not in sent_books and book_key not in new_books_to_track:
            new_books_to_track.append(book_key)
            events_to_send.append({
                "timestamp": item["timestamp"],
                "ev_type": "kindle-book",
                "source_host": "kindle",
                "source_app": "kindle-clippings",
                "content": {
                    "book_title": item["book_title"],
                    "author": item["author"],
                    "asin": None,
                    "last_read": item["timestamp"]
                },
                "tags": ["reading", "kindle"],
            })
            
        if item["is_highlight"]:
            clipping_hash = calculate_clipping_hash(
                item["book_title"],
                item["author"],
                item["highlight"],
                item["location"]
            )
            
            if clipping_hash not in sent_hashes and clipping_hash not in new_hashes_to_track:
                new_hashes_to_track.append(clipping_hash)
                events_to_send.append({
                    "timestamp": item["timestamp"],
                    "ev_type": "kindle-highlight",
                    "source_host": "kindle",
                    "source_app": "kindle-clippings",
                    "content": {
                        "book_title": item["book_title"],
                        "author": item["author"],
                        "highlight": item["highlight"],
                        "location": item["location"]
                    },
                    "tags": ["quotes", "kindle"],
                })
                
    if not events_to_send:
        console.print("[green]No new books or highlights to import.[/green]")
        return
        
    console.print(f"Found {len(events_to_send)} new events to send ({len(new_books_to_track)} books, {len(new_hashes_to_track)} highlights). Sending batch...")
    
    config = _load_config()
    with _http_client(config) as http:
        try:
            resp = http.post("/events/batch", json=events_to_send)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            err.print(f"[red]Server error {exc.response.status_code}:[/red] {exc.response.text}")
            raise typer.Exit(1)
        except httpx.RequestError as exc:
            err.print(f"[red]Connection error:[/red] {exc}")
            raise typer.Exit(1)
            
    sent_hashes.update(new_hashes_to_track)
    sent_books.update(new_books_to_track)
    _save_kindle_state({
        "sent_hashes": list(sent_hashes),
        "sent_books": list(sent_books)
    })
    
    console.print(f"[green]✓[/green] Successfully imported {len(events_to_send)} events.")


# ---------------------------------------------------------------------------
# Import / Export / Backup commands
# ---------------------------------------------------------------------------


@app.command()
def export(
    output_file: Path = typer.Argument(
        ...,
        help="Path to save the exported NDJSON file.",
    ),
    from_date: str | None = typer.Option(
        None, "--from",
        help="Start date/time (ISO 8601).",
    ),
    to_date: str | None = typer.Option(
        None, "--to",
        help="End date/time (ISO 8601).",
    ),
) -> None:
    """Export all events to an NDJSON file."""
    params = {}
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
        
    config = _load_config()
    with _http_client(config) as http:
        try:
            with http.stream("GET", "/events/export", params=params) as resp:
                resp.raise_for_status()
                with open(output_file, "wb") as f:
                    for chunk in resp.iter_bytes():
                        f.write(chunk)
        except httpx.HTTPStatusError as exc:
            err.print(f"[red]Server error {exc.response.status_code}:[/red] {exc.response.text}")
            raise typer.Exit(1)
        except httpx.RequestError as exc:
            err.print(f"[red]Connection error:[/red] {exc}")
            raise typer.Exit(1)
            
    console.print(f"[green]✓[/green] Successfully exported events to [bold]{output_file}[/bold]")


@app.command(name="import")
def import_cmd(
    input_file: Path = typer.Argument(
        ...,
        help="Path to the NDJSON file to import.",
    ),
) -> None:
    """Import events from an NDJSON file."""
    if not input_file.exists():
        err.print(f"[red]Error:[/red] File '{input_file}' does not exist.")
        raise typer.Exit(1)
        
    config = _load_config()
    with _http_client(config) as http:
        try:
            with open(input_file, "rb") as f:
                resp = http.post("/events/import", content=f)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            err.print(f"[red]Server error {exc.response.status_code}:[/red] {exc.response.text}")
            raise typer.Exit(1)
        except httpx.RequestError as exc:
            err.print(f"[red]Connection error:[/red] {exc}")
            raise typer.Exit(1)
            
    data = resp.json()
    console.print(f"[green]✓[/green] Successfully imported [bold]{data.get('imported', 0)}[/bold] events.")


@app.command()
def backup() -> None:
    """Create a backup of the SQLite database by querying the server's db_path or downloading an export."""
    config = _load_config()
    db_path_str = config.get("server", {}).get("db_path", "biograph.db")
    db_path = Path(db_path_str)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = Path(f"biograph_backup_{timestamp}.db")
    
    if db_path.exists():
        try:
            shutil.copy2(db_path, backup_file)
            console.print(f"[green]✓[/green] Local database backed up to [bold]{backup_file}[/bold]")
            return
        except Exception as e:
            err.print(f"[yellow]Warning: Local database copy failed ({e}). Trying API export...[/yellow]")
            
    backup_ndjson = Path(f"biograph_backup_{timestamp}.ndjson")
    with _http_client(config) as http:
        try:
            with http.stream("GET", "/events/export") as resp:
                resp.raise_for_status()
                with open(backup_ndjson, "wb") as f:
                    for chunk in resp.iter_bytes():
                        f.write(chunk)
            console.print(f"[green]✓[/green] Server events backed up to [bold]{backup_ndjson}[/bold]")
        except Exception as ex:
            err.print(f"[red]Backup failed:[/red] {ex}")
            raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    app()


if __name__ == "__main__":
    main()
