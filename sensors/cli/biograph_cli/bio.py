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
import unicodedata
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


def resolve_resource_uri(uri: str | None, config: dict[str, Any]) -> str | None:
    if not uri:
        return None
    if uri.startswith("{") and "}" in uri:
        end_idx = uri.index("}")
        placeholder = uri[1:end_idx]
        base_path = config.get("resources", {}).get(placeholder)
        if base_path:
            relative_part = uri[end_idx + 1:].lstrip("/")
            return str(Path(base_path) / relative_part)
    return uri


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
            
        if item.get("resource_uri"):
            resolved = resolve_resource_uri(item["resource_uri"], config)
            summary += f"\n[dim]Resource: {item['resource_uri']}[/dim]"
            if resolved and resolved != item["resource_uri"]:
                summary += f"\n[dim]↳ Local: {resolved}[/dim]"
                
        table.add_row(str(item["id"]), ts, item["ev_type"], tag_str, summary)

    console.print(table)
    shown = offset + len(items)
    console.print(
        f"\n[dim]Showing {offset + 1}–{shown} of {total} result(s)[/dim]"
    )



# ---------------------------------------------------------------------------
# Kindle clippings parser helper
# ---------------------------------------------------------------------------


MONTH_TO_NUM: dict[str, str] = {
    # English
    "january": "01", "february": "02", "march": "03", "april": "04", "may": "05", "june": "06",
    "july": "07", "august": "08", "september": "09", "october": "10", "november": "11", "december": "12",
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
    
    # German
    "januar": "01", "februar": "02", "märz": "03", "maerz": "03", "mai": "05", "juni": "06",
    "juli": "07", "oktober": "10", "dezember": "12",
    "mär": "03", "maer": "03", "okt": "10", "dez": "12",
    
    # Spanish
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04", "mayo": "05", "junio": "06",
    "julio": "07", "agosto": "08", "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
    "ene": "01", "abr": "04", "ago": "08", "set": "09", "dic": "12",
    
    # French
    "janvier": "01", "février": "02", "fevrier": "02", "mars": "03", "avril": "04", "mai": "05", "juin": "06",
    "juillet": "07", "août": "08", "aout": "08", "septembre": "09", "octobre": "10", "novembre": "11", "décembre": "12", "decembre": "12",
    "janv": "01", "févr": "02", "fevr": "02", "juil": "07", "sept": "09", "déc": "12", "dec": "12",
    
    # Italian
    "gennaio": "01", "febbraio": "02", "aprile": "04", "maggio": "05", "giugno": "06",
    "luglio": "07", "settembre": "09", "ottobre": "10", "dicembre": "12",
    "genn": "01", "febbr": "02", "magg": "05", "giugn": "06", "lugl": "07", "ag": "08", "sett": "09", "ott": "10", "dic": "12",
    
    # Portuguese
    "janeiro": "01", "fevereiro": "02", "março": "03", "marco": "03", "junho": "06",
    "julho": "07", "outubro": "10", "dezembro": "12",
    "fev": "02", "out": "10",
}

WEEKDAYS_REGEX = re.compile(
    r"^(?:"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonnabend|sonntag|"
    r"lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo|"
    r"lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|"
    r"lunedì|lunedi|martedì|martedi|mercoledì|mercoledi|giovedì|giovedi|venerdì|venerdi|"
    r"segunda-feira|terça-feira|quarta-feira|quinta-feira|sexta-feira|"
    r"segunda|terça|terca|quarta|quinta|sexta"
    r")[\s,]*",
    re.IGNORECASE
)


def parse_kindle_date(date_str: str) -> datetime | None:
    date_str = WEEKDAYS_REGEX.sub("", date_str).strip()
    date_str = re.sub(r"\bde\b", "", date_str, flags=re.IGNORECASE)
    date_str = re.sub(r"\s+", " ", date_str).strip()
    
    def replace_month(match: re.Match[str]) -> str:
        w = match.group(0)
        w_lower = w.lower()
        return MONTH_TO_NUM.get(w_lower, w)
    
    date_str = re.sub(r"\b\w+\b", replace_month, date_str)
    
    formats = [
        "%d %m %Y %H:%M:%S",
        "%m %d, %Y %I:%M:%S %p",
        "%d. %m %Y %H:%M:%S",
        "%d %m %Y %I:%M:%S %p",
        "%m %d, %Y %H:%M:%S",
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
        location_match = re.search(r"(?:location|position|posición|posição|emplacement|posizione|loc\.|pos\.)\s+(\d+)", metadata, re.IGNORECASE)
        if location_match:
            location = int(location_match.group(1))
            
        timestamp = datetime.now(UTC).isoformat()
        for part in metadata.split("|"):
            part = part.strip()
            match = re.match(r"^(?:Added on|Hinzugefügt am|Añadido el|Ajouté le|Adicionado em|Aggiunto (?:il|in))\s+(.*)$", part, re.IGNORECASE)
            if match:
                date_str = match.group(1).strip()
                parsed_dt = parse_kindle_date(date_str)
                if parsed_dt:
                    timestamp = parsed_dt.astimezone(UTC).isoformat()
                    
        is_highlight = any(
            kw in metadata.lower()
            for kw in ["highlight", "markierung", "subrayado", "surlign", "evidenziazione", "destaque"]
        )
        
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


def _get_state_path(prefix: str, server_url: str) -> Path:
    normalized = server_url.strip().lower()
    server_hash = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:12]
    filename = f"{prefix}_state_{server_hash}.json"
    return Path.home() / ".local" / "share" / "biograph" / filename


def _load_kindle_state(server_url: str) -> dict[str, Any]:
    state_file = _get_state_path("kindle", server_url)
    if state_file.exists():
        try:
            with open(state_file, "r") as f:
                return json.load(f)
        except Exception:
            pass
    # Migration check
    legacy_file = Path.home() / ".local" / "share" / "biograph" / "kindle_state.json"
    if legacy_file.exists():
        try:
            with open(legacy_file, "r") as f:
                data = json.load(f)
            _save_kindle_state(server_url, data)
            return data
        except Exception:
            pass
    return {"sent_hashes": [], "sent_books": []}


def _save_kindle_state(server_url: str, state: dict[str, Any]) -> None:
    state_file = _get_state_path("kindle", server_url)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)


# ---------------------------------------------------------------------------
# Kindle import command
# ---------------------------------------------------------------------------


@app.command()
def kindle(
    path: Path | None = typer.Argument(
        None,
        help="Path to Kindle mountpoint directory or directly to the clippings file (e.g. My Clippings.txt). If omitted, it will try to auto-detect.",
    ),
) -> None:
    """Import books and highlights from a mounted Kindle device or local clippings file."""
    paths_to_process = []
    if path is not None:
        paths_to_process.append(path)
    else:
        # Auto-detect Kindle mount points
        detected = []
        # Linux
        run_media = Path("/run/media")
        if run_media.exists():
            for user_dir in run_media.iterdir():
                if user_dir.is_dir():
                    for mount_dir in user_dir.iterdir():
                        if mount_dir.is_dir():
                            if (mount_dir / "documents" / "My Clippings.txt").exists() or (mount_dir / "My Clippings.txt").exists():
                                detected.append(mount_dir)
        # macOS
        volumes = Path("/Volumes")
        if volumes.exists():
            for mount_dir in volumes.iterdir():
                if mount_dir.is_dir():
                    if (mount_dir / "documents" / "My Clippings.txt").exists() or (mount_dir / "My Clippings.txt").exists():
                        detected.append(mount_dir)

        if not detected:
            err.print(
                "[red]Error:[/red] No mount point specified and could not auto-detect any Kindle."
            )
            err.print("Please specify the path: [bold]bio kindle <path>[/bold]")
            raise typer.Exit(1)
        paths_to_process.extend(detected)

    config = _load_config()
    server_url = _server_url(config)
    state = _load_kindle_state(server_url)
    sent_hashes = set(state.get("sent_hashes", []))
    sent_books = set(state.get("sent_books", []))

    events_to_send = []
    new_books_to_track = []
    new_hashes_to_track = []

    for current_path in paths_to_process:
        console.print(f"[dim]Processing Kindle mount point: {current_path}[/dim]")
        
        clippings_file = None
        if current_path.is_file():
            clippings_file = current_path
        elif current_path.is_dir():
            clippings_file = current_path / "documents" / "My Clippings.txt"
            if not clippings_file.exists():
                clippings_file = current_path / "My Clippings.txt"
        else:
            err.print(f"[yellow]Warning:[/yellow] '{current_path}' is neither a file nor a directory. Skipping.")
            continue
            
        if not clippings_file or not clippings_file.exists():
            err.print(f"[yellow]Warning:[/yellow] Could not find clippings file at '{current_path}'. Skipping.")
            continue
            
        try:
            content = clippings_file.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            try:
                content = clippings_file.read_text(encoding="latin-1")
            except Exception as e:
                err.print(f"[red]Error reading clippings file from {clippings_file}:[/red] {e}")
                continue

        items = parse_clippings(content)
        if not items:
            continue

        for item in items:
            book_key = item["book_title"]
            if book_key not in sent_books and book_key not in new_books_to_track:
                new_books_to_track.append(book_key)
                events_to_send.append({
                    "timestamp": item["timestamp"],
                    "ev_type": "kindle-book",
                    "source_host": "kindle",
                    "source_app": "kindle-clippings",
                    "remote_id": f"kindle-book:{book_key}",
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
                        "remote_id": f"kindle-highlight:{clipping_hash}",
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
    _save_kindle_state(server_url, {
        "sent_hashes": list(sent_hashes),
        "sent_books": list(sent_books)
    })
    
    console.print(f"[green]✓[/green] Successfully imported {len(events_to_send)} events.")


def _load_tolino_state(server_url: str) -> dict[str, Any]:
    state_file = _get_state_path("tolino", server_url)
    if state_file.exists():
        try:
            with open(state_file, "r") as f:
                return json.load(f)
        except Exception:
            pass
    # Migration check
    legacy_file = Path.home() / ".local" / "share" / "biograph" / "tolino_state.json"
    if legacy_file.exists():
        try:
            with open(legacy_file, "r") as f:
                data = json.load(f)
            _save_tolino_state(server_url, data)
            return data
        except Exception:
            pass
    return {"sent_bookmark_ids": [], "sent_book_progress": {}}


def _save_tolino_state(server_url: str, state: dict[str, Any]) -> None:
    state_file = _get_state_path("tolino", server_url)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)


@app.command()
def tolino(
    path: Path | None = typer.Argument(
        None,
        help="Path to Tolino mountpoint directory or directly to KoboReader.sqlite database. If omitted, it will try to auto-detect the mount point in /run/media.",
    ),
) -> None:
    """Import books and highlights from a mounted Tolino/Kobo ereader."""
    import sqlite3
    import tempfile
    import shutil

    paths_to_process = []
    if path is not None:
        paths_to_process.append(path)
    else:
        # Auto-detect Tolino mount points
        detected = []
        # Linux
        run_media = Path("/run/media")
        if run_media.exists():
            for user_dir in run_media.iterdir():
                if user_dir.is_dir():
                    for mount_dir in user_dir.iterdir():
                        if mount_dir.is_dir():
                            if (mount_dir / ".kobo" / "KoboReader.sqlite").exists() or (mount_dir / "KoboReader.sqlite").exists():
                                detected.append(mount_dir)
        # macOS
        volumes = Path("/Volumes")
        if volumes.exists():
            for mount_dir in volumes.iterdir():
                if mount_dir.is_dir():
                    if (mount_dir / ".kobo" / "KoboReader.sqlite").exists() or (mount_dir / "KoboReader.sqlite").exists():
                        detected.append(mount_dir)

        if not detected:
            err.print(
                "[red]Error:[/red] No mount point specified and could not auto-detect Tolino at '/run/media/*/eReader'."
            )
            err.print("Please specify the path: [bold]bio tolino <path>[/bold]")
            raise typer.Exit(1)
        paths_to_process.extend(detected)

    config = _load_config()
    server_url = _server_url(config)
    state = _load_tolino_state(server_url)
    sent_bookmark_ids = set(state.get("sent_bookmark_ids", []))
    sent_book_progress = state.get("sent_book_progress", {})

    events_to_send = []
    new_bookmark_ids = []
    updated_book_progress = dict(sent_book_progress)

    for current_path in paths_to_process:
        console.print(f"[dim]Processing Tolino/Kobo mount point: {current_path}[/dim]")
        
        db_file = None
        if current_path.is_file():
            db_file = current_path
        elif current_path.is_dir():
            db_file = current_path / ".kobo" / "KoboReader.sqlite"
            if not db_file.exists():
                db_file = current_path / "KoboReader.sqlite"
        else:
            err.print(f"[yellow]Warning:[/yellow] '{current_path}' is neither a file nor a directory. Skipping.")
            continue

        if not db_file.exists():
            err.print(f"[yellow]Warning:[/yellow] Could not find SQLite database at '{db_file}'. Skipping.")
            continue

        temp_dir = tempfile.mkdtemp()
        temp_db = Path(temp_dir) / "KoboReader.sqlite"
        try:
            shutil.copy2(db_file, temp_db)
        except Exception as e:
            err.print(f"[red]Error copying database file from {db_file}:[/red] {e}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            continue

        try:
            conn = sqlite3.connect(str(temp_db))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 1. Fetch books and progress
            cursor.execute(
                """
                SELECT Title, Attribution, ContentID, ReadStatus, ___PercentRead, DateLastRead, DateCreated
                FROM content
                WHERE ContentType = '6' AND Title IS NOT NULL AND Title != ''
                """
            )
            books = cursor.fetchall()
            for book in books:
                content_id = book["ContentID"]
                title = book["Title"]
                author = book["Attribution"] or "Unknown"
                read_status = book["ReadStatus"]
                percent_read = book["___PercentRead"]
                last_read = book["DateLastRead"]

                if last_read and (read_status > 0 or (percent_read is not None and percent_read > 0)):
                    prev_last_read = sent_book_progress.get(content_id)
                    if not prev_last_read or last_read > prev_last_read:
                        updated_book_progress[content_id] = last_read
                        events_to_send.append({
                            "timestamp": last_read,
                            "ev_type": "tolino-book",
                            "source_host": "tolino",
                            "source_app": "tolino-db",
                            "remote_id": f"tolino-book:{content_id}:{last_read}",
                            "content": {
                                "book_title": title,
                                "author": author,
                                "content_id": content_id,
                                "read_status": read_status,
                                "percent_read": percent_read,
                                "last_read": last_read
                            },
                            "tags": ["reading", "tolino"],
                        })

            # 2. Fetch highlights/bookmarks
            cursor.execute(
                """
                SELECT b.BookmarkID, b.VolumeID, b.Text, b.Annotation, b.DateCreated, b.StartContainerPath,
                       c.Title, c.Attribution
                FROM Bookmark b
                LEFT JOIN content c ON b.VolumeID = c.ContentID
                WHERE b.Text IS NOT NULL AND b.Text != '' AND b.Hidden = 0
                """
            )
            bookmarks = cursor.fetchall()
            for bm in bookmarks:
                bookmark_id = bm["BookmarkID"]
                text = bm["Text"]
                annotation = bm["Annotation"]
                date_created = bm["DateCreated"]
                location = bm["StartContainerPath"]
                book_title = bm["Title"] or "Unknown Book"
                author = bm["Attribution"] or "Unknown"

                if bookmark_id not in sent_bookmark_ids:
                    new_bookmark_ids.append(bookmark_id)
                    timestamp = date_created if date_created else datetime.now(UTC).isoformat()
                    events_to_send.append({
                        "timestamp": timestamp,
                        "ev_type": "tolino-highlight",
                        "source_host": "tolino",
                        "source_app": "tolino-db",
                        "remote_id": f"tolino-highlight:{bookmark_id}",
                        "content": {
                            "book_title": book_title,
                            "author": author,
                            "highlight": text,
                            "annotation": annotation,
                            "bookmark_id": bookmark_id,
                            "location": location
                        },
                        "tags": ["quotes", "tolino"],
                    })

            conn.close()
        except Exception as e:
            err.print(f"[red]Database error processing {db_file}:[/red] {e}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    if not events_to_send:
        console.print("[green]No new books read or highlights to import.[/green]")
        return

    books_count = sum(1 for e in events_to_send if e["ev_type"] == "tolino-book")
    highlights_count = sum(1 for e in events_to_send if e["ev_type"] == "tolino-highlight")

    console.print(
        f"Found {len(events_to_send)} new events to send ({books_count} books progress updates, {highlights_count} highlights). Sending batch..."
    )

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

    sent_bookmark_ids.update(new_bookmark_ids)
    _save_tolino_state(server_url, {
        "sent_bookmark_ids": list(sent_bookmark_ids),
        "sent_book_progress": updated_book_progress
    })

    console.print(f"[green]✓[/green] Successfully imported {len(events_to_send)} events.")


def _load_pocketbook_state(server_url: str) -> dict[str, Any]:
    state_file = _get_state_path("pocketbook", server_url)
    if state_file.exists():
        try:
            with open(state_file, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"sent_bookmark_ids": [], "sent_book_progress": {}}


def _save_pocketbook_state(server_url: str, state: dict[str, Any]) -> None:
    state_file = _get_state_path("pocketbook", server_url)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)


@app.command()
def pocketbook(
    path: Path | None = typer.Argument(
        None,
        help="Path to PocketBook mountpoint directory or directly to books.db database. If omitted, it will try to auto-detect.",
    ),
) -> None:
    """Import books and highlights from a mounted PocketBook eReader."""
    import sqlite3
    import tempfile
    import shutil

    paths_to_process = []
    if path is not None:
        paths_to_process.append(path)
    else:
        # Auto-detect PocketBook mount points
        detected = []
        # Linux
        run_media = Path("/run/media")
        if run_media.exists():
            for user_dir in run_media.iterdir():
                if user_dir.is_dir():
                    for mount_dir in user_dir.iterdir():
                        if mount_dir.is_dir() and mount_dir.name.upper().startswith("PB"):
                            if (mount_dir / "system" / "config" / "books.db").exists():
                                detected.append(mount_dir)
        # macOS
        volumes = Path("/Volumes")
        if volumes.exists():
            for mount_dir in volumes.iterdir():
                if mount_dir.is_dir() and mount_dir.name.upper().startswith("PB"):
                    if (mount_dir / "system" / "config" / "books.db").exists():
                        detected.append(mount_dir)

        if not detected:
            err.print(
                "[red]Error:[/red] No mount point specified and could not auto-detect any PocketBook eReader at '/run/media/*/PB*'."
            )
            err.print("Please specify the path: [bold]bio pocketbook <path>[/bold]")
            raise typer.Exit(1)
        paths_to_process.extend(detected)

    config = _load_config()
    server_url = _server_url(config)
    state = _load_pocketbook_state(server_url)
    sent_bookmark_ids = set(state.get("sent_bookmark_ids", []))
    sent_book_progress = state.get("sent_book_progress", {})

    events_to_send = []
    new_bookmark_ids = []
    updated_book_progress = dict(sent_book_progress)

    for current_path in paths_to_process:
        console.print(f"[dim]Processing PocketBook mount point: {current_path}[/dim]")
        
        db_file = None
        if current_path.is_file():
            db_file = current_path
        elif current_path.is_dir():
            db_file = current_path / "system" / "config" / "books.db"
        else:
            err.print(f"[yellow]Warning:[/yellow] '{current_path}' is neither a file nor a directory. Skipping.")
            continue

        if not db_file.exists():
            err.print(f"[yellow]Warning:[/yellow] Could not find SQLite database at '{db_file}'. Skipping.")
            continue

        temp_dir = tempfile.mkdtemp()
        temp_db = Path(temp_dir) / "books.db"
        try:
            shutil.copy2(db_file, temp_db)
        except Exception as e:
            err.print(f"[red]Error copying database file from {db_file}:[/red] {e}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            continue

        try:
            conn = sqlite3.connect(str(temp_db))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 1. Fetch books progress
            cursor.execute(
                """
                SELECT b.Title, b.Authors, b.OID as BookOID, t_prog.Val as ReadProgress, t_prog.TimeEdt as LastReadTime
                FROM Books b
                JOIN Tags t_prog ON b.OID = t_prog.ItemID AND t_prog.TagID = 80
                WHERE b.Title IS NOT NULL AND b.Title != ''
                """
            )
            books = cursor.fetchall()
            for book in books:
                book_oid = str(book["BookOID"])
                title = book["Title"]
                author = book["Authors"] or "Unknown"
                
                try:
                    progress_val = float(book["ReadProgress"])
                    percent_read = int(round(progress_val * 100))
                    percent_read = max(0, min(100, percent_read))
                except (ValueError, TypeError):
                    percent_read = 0
                
                last_read_time = book["LastReadTime"]

                if last_read_time > 0 and percent_read > 0:
                    prev_last_read = sent_book_progress.get(book_oid)
                    if not prev_last_read or last_read_time > prev_last_read:
                        updated_book_progress[book_oid] = last_read_time
                        
                        timestamp = datetime.fromtimestamp(last_read_time, UTC).isoformat()
                        events_to_send.append({
                            "timestamp": timestamp,
                            "ev_type": "pocketbook-book",
                            "source_host": "pocketbook",
                            "source_app": "pocketbook-db",
                            "remote_id": f"pocketbook-book:{book_oid}:{last_read_time}",
                            "content": {
                                "book_title": title,
                                "author": author,
                                "content_id": book_oid,
                                "percent_read": percent_read,
                                "last_read": timestamp
                            },
                            "tags": ["reading", "pocketbook"],
                        })

            # 2. Fetch highlights/bookmarks
            cursor.execute(
                """
                SELECT 
                    b.Title, 
                    b.Authors, 
                    i.OID as BookmarkOID, 
                    i.ParentID as BookOID,
                    t_type.Val as BookmarkType,
                    t_quote.Val as BookmarkQuotation,
                    t_note.Val as BookmarkNote,
                    t_bm.Val as BookmarkMark
                FROM Items i
                JOIN Books b ON i.ParentID = b.OID
                LEFT JOIN Tags t_type ON i.OID = t_type.ItemID AND t_type.TagID = 102
                LEFT JOIN Tags t_quote ON i.OID = t_quote.ItemID AND t_quote.TagID = 104
                LEFT JOIN Tags t_note ON i.OID = t_note.ItemID AND t_note.TagID = 105
                LEFT JOIN Tags t_bm ON i.OID = t_bm.ItemID AND t_bm.TagID = 101
                WHERE i.TypeID = 4
                """
            )
            bookmarks = cursor.fetchall()
            for bm in bookmarks:
                bookmark_id = str(bm["BookmarkOID"])
                book_title = bm["Title"] or "Unknown Book"
                author = bm["Authors"] or "Unknown"
                
                # Extract quotation text
                quote_text = ""
                quote_updated_str = None
                if bm["BookmarkQuotation"]:
                    try:
                        quote_data = json.loads(bm["BookmarkQuotation"])
                        quote_text = quote_data.get("text", "")
                        quote_updated_str = quote_data.get("updated")
                    except Exception:
                        pass
                
                # Extract note (annotation)
                note_text = None
                if bm["BookmarkNote"]:
                    try:
                        note_data = json.loads(bm["BookmarkNote"])
                        note_text = note_data.get("text")
                    except Exception:
                        pass

                # Extract location and timestamp from bookmark mark (created/updated)
                location = None
                created_timestamp = None
                if bm["BookmarkMark"]:
                    try:
                        mark_data = json.loads(bm["BookmarkMark"])
                        location = mark_data.get("anchor")
                        created_timestamp = mark_data.get("created")
                    except Exception:
                        pass

                if bookmark_id not in sent_bookmark_ids:
                    new_bookmark_ids.append(bookmark_id)
                    
                    # Resolve timestamp
                    if created_timestamp:
                        timestamp = datetime.fromtimestamp(created_timestamp, UTC).isoformat()
                    elif quote_updated_str:
                        timestamp = quote_updated_str
                    else:
                        timestamp = datetime.now(UTC).isoformat()
                        
                    events_to_send.append({
                        "timestamp": timestamp,
                        "ev_type": "pocketbook-highlight",
                        "source_host": "pocketbook",
                        "source_app": "pocketbook-db",
                        "remote_id": f"pocketbook-highlight:{bookmark_id}",
                        "content": {
                            "book_title": book_title,
                            "author": author,
                            "highlight": quote_text or "[Bookmark]",
                            "annotation": note_text,
                            "bookmark_id": bookmark_id,
                            "location": location
                        },
                        "tags": ["quotes", "pocketbook"],
                    })

            conn.close()
        except Exception as e:
            err.print(f"[red]Database error processing {db_file}:[/red] {e}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    if not events_to_send:
        console.print("[green]No new books read or highlights to import.[/green]")
        return

    books_count = sum(1 for e in events_to_send if e["ev_type"] == "pocketbook-book")
    highlights_count = sum(1 for e in events_to_send if e["ev_type"] == "pocketbook-highlight")

    console.print(
        f"Found {len(events_to_send)} new events to send ({books_count} books progress updates, {highlights_count} highlights). Sending batch..."
    )

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

    sent_bookmark_ids.update(new_bookmark_ids)
    _save_pocketbook_state(server_url, {
        "sent_bookmark_ids": list(sent_bookmark_ids),
        "sent_book_progress": updated_book_progress
    })

    console.print(f"[green]✓[/green] Successfully imported {len(events_to_send)} events.")


# ---------------------------------------------------------------------------
# Calibre import command
# ---------------------------------------------------------------------------


def _load_calibre_state(server_url: str) -> dict[str, Any]:
    state_file = _get_state_path("calibre", server_url)
    if state_file.exists():
        try:
            with open(state_file, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"sent_uuids": []}


def _save_calibre_state(server_url: str, state: dict[str, Any]) -> None:
    state_file = _get_state_path("calibre", server_url)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)


def _detect_calibre_library() -> Path | None:
    default_path = Path.home() / "Calibre Library"
    if (default_path / "metadata.db").exists():
        return default_path
    return None


def query_calibre_library(db_path: Path) -> list[dict[str, Any]]:
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Query books
    cursor.execute("""
        SELECT 
            b.id,
            b.title,
            b.timestamp,
            b.pubdate,
            b.uuid,
            b.path,
            b.series_index,
            s.name AS series
        FROM books b
        LEFT JOIN books_series_link bsl ON bsl.book = b.id
        LEFT JOIN series s ON s.id = bsl.series
    """)
    books = [dict(row) for row in cursor.fetchall()]

    # Query authors
    cursor.execute("""
        SELECT ba.book, a.name
        FROM books_authors_link ba
        JOIN authors a ON a.id = ba.author
    """)
    authors_map = {}
    for row in cursor.fetchall():
        authors_map.setdefault(row["book"], []).append(row["name"])

    # Query tags
    cursor.execute("""
        SELECT bt.book, t.name
        FROM books_tags_link bt
        JOIN tags t ON t.id = bt.tag
    """)
    tags_map = {}
    for row in cursor.fetchall():
        tags_map.setdefault(row["book"], []).append(row["name"])

    # Query formats
    cursor.execute("""
        SELECT d.book, d.format
        FROM data d
    """)
    formats_map = {}
    for row in cursor.fetchall():
        formats_map.setdefault(row["book"], []).append(row["format"])

    # Query identifiers
    cursor.execute("""
        SELECT i.book, i.type, i.val
        FROM identifiers i
    """)
    identifiers_map = {}
    for row in cursor.fetchall():
        identifiers_map.setdefault(row["book"], {})[row["type"]] = row["val"]

    conn.close()

    parsed_books = []
    for b in books:
        book_id = b["id"]
        raw_ts = b["timestamp"]
        try:
            if raw_ts.endswith("+00:00"):
                ts = datetime.fromisoformat(raw_ts)
            else:
                ts = datetime.fromisoformat(raw_ts).replace(tzinfo=UTC)
        except Exception:
            ts = datetime.now(UTC)

        raw_pub = b["pubdate"]
        pubdate_iso = None
        if raw_pub:
            try:
                if raw_pub.endswith("+00:00"):
                    pubdate_iso = datetime.fromisoformat(raw_pub).isoformat()
                else:
                    pubdate_iso = datetime.fromisoformat(raw_pub).replace(tzinfo=UTC).isoformat()
            except Exception:
                pass

        ids = identifiers_map.get(book_id, {})
        isbn = ids.get("isbn")

        parsed_books.append({
            "timestamp": ts.isoformat(),
            "ev_type": "calibre-book",
            "source_host": socket.gethostname(),
            "source_app": "calibre",
            "remote_id": b["uuid"],
            "content": {
                "uuid": b["uuid"],
                "title": b["title"],
                "authors": authors_map.get(book_id, []),
                "series": b["series"],
                "series_index": b["series_index"],
                "isbn": isbn,
                "path": b["path"],
                "pubdate": pubdate_iso,
                "formats": formats_map.get(book_id, []),
                "tags": tags_map.get(book_id, [])
            },
            "tags": ["reading", "book", "calibre"]
        })
    return parsed_books


@app.command()
def calibre(
    path: Path | None = typer.Argument(
        None,
        help="Path to Calibre Library directory or directly to metadata.db. If omitted, it will try to auto-detect.",
    ),
) -> None:
    """Import books added to Calibre library."""
    if path is not None:
        lib_path = path
    else:
        lib_path = _detect_calibre_library()
        if lib_path is None:
            err.print(
                "[red]Error:[/red] No Calibre library path specified and could not auto-detect."
            )
            err.print("Please specify the path: [bold]bio calibre <path>[/bold]")
            raise typer.Exit(1)

    db_file = lib_path if lib_path.name == "metadata.db" else lib_path / "metadata.db"
    if not db_file.exists():
        err.print(f"[red]Error:[/red] Calibre database not found at '{db_file}'")
        raise typer.Exit(1)

    config = _load_config()
    server_url = _server_url(config)
    state = _load_calibre_state(server_url)
    sent_uuids = set(state.get("sent_uuids", []))

    console.print(f"[dim]Processing Calibre library at: {db_file.parent}[/dim]")

    try:
        books = query_calibre_library(db_file)
    except Exception as e:
        err.print(f"[red]Error querying Calibre database:[/red] {e}")
        raise typer.Exit(1)

    events_to_send = []
    new_uuids_to_track = []

    for book in books:
        uuid = book["content"]["uuid"]
        if uuid not in sent_uuids:
            new_uuids_to_track.append(uuid)
            events_to_send.append(book)

    if not events_to_send:
        console.print("[green]No new books to import from Calibre.[/green]")
        return

    console.print(f"Found {len(events_to_send)} new books to import. Sending batch...")

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

    sent_uuids.update(new_uuids_to_track)
    _save_calibre_state(server_url, {
        "sent_uuids": list(sent_uuids)
    })

    console.print(f"[green]✓[/green] Successfully imported {len(events_to_send)} Calibre books.")


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
    since_update_id: int | None = typer.Option(
        None, "--since",
        help="Export events with an update_id greater than this value.",
    ),
    include_deleted: bool = typer.Option(
        False, "--include-deleted",
        help="Include soft-deleted events in the export.",
    ),
) -> None:
    """Export events to an NDJSON file."""
    params = {}
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    if since_update_id is not None:
        params["since_update_id"] = since_update_id
    if include_deleted:
        params["include_deleted"] = "true"
        
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


# ---------------------------------------------------------------------------
# backfill-books
# ---------------------------------------------------------------------------

_BOOK_EVENT_TYPES: tuple[str, ...] = (
    "koreader-progress",
    "koreader-book",
    "kosync-progress",
    "kindle-book",
    "tolino-book",
    "pocketbook-book",
    "kindle-highlight",
    "tolino-highlight",
    "pocketbook-highlight",
    "calibre-book",
)


def _norm_nfc_posix(raw: str) -> str:
    return unicodedata.normalize("NFC", raw.replace("\\", "/")).strip()


def _norm_book_title_key(raw: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKC", raw).lower()).strip()


def _strip_book_ext(raw: str) -> str:
    name = Path(raw.replace("\\", "/")).name
    return re.sub(r"\.(epub|pdf|mobi|azw3|fb2|djvu|cbz|txt|html?)$", "", name, flags=re.IGNORECASE).strip()


def _build_catalog_indexes(catalog_data: dict[str, Any]) -> dict[str, Any]:
    books_raw = catalog_data.get("books")
    if not isinstance(books_raw, dict):
        raise ValueError("Invalid catalog: missing 'books' mapping")

    by_uuid: dict[str, dict[str, Any]] = {}
    by_hash: dict[str, dict[str, Any]] = {}
    by_rel_path: dict[str, dict[str, Any]] = {}
    by_basename: dict[str, dict[str, Any] | None] = {}
    by_title: dict[str, dict[str, Any] | None] = {}

    def _add_unique(target: dict[str, dict[str, Any] | None], key: str, book: dict[str, Any]) -> None:
        if not key:
            return
        if key not in target:
            target[key] = book
        elif target[key] is not None and target[key]["uuid"] != book["uuid"]:
            target[key] = None  # ambiguous

    for uuid_key, raw_entry in books_raw.items():
        if not isinstance(raw_entry, dict):
            continue
        book_uuid = str(raw_entry.get("uuid") or uuid_key)
        authors_raw = raw_entry.get("authors")
        authors = [str(a) for a in authors_raw] if isinstance(authors_raw, list) else []
        book = {
            "uuid": book_uuid,
            "title": str(raw_entry.get("title") or "").strip(),
            "authors": authors,
            "series": str(raw_entry.get("series") or "").strip(),
            "files": raw_entry.get("files") or [],
        }
        by_uuid[book_uuid] = book

        if book["title"]:
            t_key = _norm_book_title_key(book["title"])
            _add_unique(by_title, t_key, book)
            if authors:
                _add_unique(by_title, _norm_book_title_key(f"{authors[0]} {book['title']}"), book)
                _add_unique(by_title, _norm_book_title_key(f"{' '.join(authors)} {book['title']}"), book)

        for fentry in book["files"]:
            if not isinstance(fentry, dict):
                continue
            for hkey in ("filename_md5", "koreader_partial_md5"):
                hval = fentry.get(hkey)
                if hval:
                    by_hash[str(hval)] = book
            rel_raw = fentry.get("rel_path")
            if rel_raw:
                norm_rel = _norm_nfc_posix(str(rel_raw))
                by_rel_path[norm_rel] = book
                bname = _norm_nfc_posix(Path(norm_rel).name)
                _add_unique(by_basename, bname, book)

    return {
        "by_uuid": by_uuid,
        "by_hash": by_hash,
        "by_rel_path": by_rel_path,
        "by_basename": by_basename,
        "by_title": by_title,
    }


def _match_event_to_book(ev: dict[str, Any], indexes: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    content = ev.get("content") or {}
    if not isinstance(content, dict):
        return None, ""

    existing_uuid = str(content.get("book_uuid") or content.get("uuid") or "").strip()
    if existing_uuid and existing_uuid in indexes["by_uuid"]:
        return indexes["by_uuid"][existing_uuid], "uuid"

    doc_hash = str(content.get("document_hash") or "").strip()
    if doc_hash and doc_hash in indexes["by_hash"]:
        return indexes["by_hash"][doc_hash], "hash"

    filename = str(content.get("filename") or "").strip()
    if filename:
        norm_rel = _norm_nfc_posix(filename)
        if norm_rel in indexes["by_rel_path"]:
            return indexes["by_rel_path"][norm_rel], "path"
        bname = _norm_nfc_posix(Path(norm_rel).name)
        matched = indexes["by_basename"].get(bname)
        if matched is not None:
            return matched, "path"

    candidates: list[str] = []
    for key_name in ("title", "book_title"):
        val = str(content.get(key_name) or "").strip()
        if val:
            candidates.append(val)
    if filename:
        cleaned = _strip_book_ext(filename)
        if cleaned:
            candidates.append(cleaned)
            if " - " in cleaned:
                candidates.append(cleaned.split(" - ", 1)[1].strip())

    for cand in candidates:
        tkey = _norm_book_title_key(cand)
        matched = indexes["by_title"].get(tkey)
        if matched is not None:
            return matched, "title"

    return None, ""


def _compute_backfill_record(
    ev: dict[str, Any],
    book: dict[str, Any],
) -> dict[str, Any] | None:
    """Return an updated event dict for /events/import, or None if already up to date."""
    ev_type = ev.get("ev_type", "")
    content = dict(ev.get("content") or {})
    book_uuid = book["uuid"]
    expected_uri = f"knrs://book/{book_uuid}"

    new_summary = ev.get("summary")
    new_uri = ev.get("resource_uri")

    if ev_type == "calibre-book":
        if not content.get("uuid"):
            content["uuid"] = book_uuid
        if new_uri != expected_uri:
            new_uri = expected_uri
    else:
        content["book_uuid"] = book_uuid
        if book["title"] and not content.get("title"):
            content["title"] = book["title"]
        if book["authors"]:
            if not content.get("authors"):
                content["authors"] = list(book["authors"])
            if not content.get("author"):
                content["author"] = ", ".join(book["authors"])
        if book["series"] and not content.get("series"):
            content["series"] = book["series"]
        new_uri = expected_uri

        if ev_type == "koreader-progress" and book["title"]:
            pct_raw = content.get("percentage")
            if pct_raw is not None:
                try:
                    pct_val = float(pct_raw)
                    pct_display = f"{pct_val * 100:.1f}%" if pct_val <= 1.0 else f"{pct_val:.1f}%"
                    expected_summary = f"Reading progress on '{book['title']}': {pct_display}"
                    if not new_summary or (
                        new_summary.startswith("Reading progress on '")
                        and book["title"] not in new_summary
                    ):
                        new_summary = expected_summary
                except (TypeError, ValueError):
                    pass

    if (
        content == (ev.get("content") or {})
        and new_uri == ev.get("resource_uri")
        and new_summary == ev.get("summary")
    ):
        return None

    return {
        "id": ev["id"],
        "timestamp": ev["timestamp"],
        "received_at": ev["received_at"],
        "ev_type": ev_type,
        "source_host": ev.get("source_host"),
        "source_app": ev.get("source_app"),
        "content": content,
        "tags": ev.get("tags") or [],
        "summary": new_summary,
        "deleted_at": ev.get("deleted_at"),
        "remote_id": ev.get("remote_id"),
        "resource_uri": new_uri,
    }


@app.command(name="backfill-books")
def backfill_books(
    catalog_path: Path = typer.Argument(
        ...,
        help="Path to .knrs-catalog.json or directory containing it (e.g. ~/MetaLibrary).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run/--no-dry-run",
        help="Preview matched updates without modifying the Biograph database.",
    ),
    batch_size: int = typer.Option(
        200,
        "--batch-size",
        min=1,
        max=1000,
        help="Number of updated events to import per request.",
    ),
) -> None:
    """Backfill book_uuid, metadata, and resource_uri on existing Biograph reading events."""
    resolved = catalog_path.expanduser()
    if resolved.is_dir():
        resolved = resolved / ".knrs-catalog.json"

    if not resolved.is_file():
        err.print(f"[red]Error:[/red] Catalog file not found: {resolved}")
        raise typer.Exit(1)

    try:
        catalog_data = json.loads(resolved.read_text(encoding="utf-8"))
        indexes = _build_catalog_indexes(catalog_data)
    except Exception as exc:
        err.print(f"[red]Error loading catalog {resolved}:[/red] {exc}")
        raise typer.Exit(1)

    config = _load_config()
    all_events: list[dict[str, Any]] = []
    page_size = 500
    offset = 0

    with _http_client(config) as http:
        try:
            while True:
                params: list[tuple[str, str | int]] = [
                    ("ev_type", t) for t in _BOOK_EVENT_TYPES
                ]
                params.extend([("limit", page_size), ("offset", offset)])
                resp = http.get("/events/", params=params)
                resp.raise_for_status()
                payload = resp.json()
                items = payload.get("items") or []
                total = int(payload.get("total") or 0)
                all_events.extend(items)
                offset += len(items)
                if not items or offset >= total:
                    break
        except httpx.HTTPStatusError as exc:
            err.print(f"[red]Server error {exc.response.status_code}:[/red] {exc.response.text}")
            raise typer.Exit(1)
        except httpx.RequestError as exc:
            err.print(f"[red]Connection error:[/red] {exc}")
            raise typer.Exit(1)

        match_counts = {"uuid": 0, "hash": 0, "path": 0, "title": 0}
        already_uptodate = 0
        unmatched = 0
        updates: list[dict[str, Any]] = []

        for ev in all_events:
            matched_book, via = _match_event_to_book(ev, indexes)
            if not matched_book:
                unmatched += 1
                continue

            updated_rec = _compute_backfill_record(ev, matched_book)
            if updated_rec is None:
                already_uptodate += 1
                continue

            match_counts[via] += 1
            updates.append(updated_rec)

        table = Table(title="Biograph Book Backfill Summary")
        table.add_column("Metric", style="bold cyan")
        table.add_column("Count", justify="right")
        table.add_row("Catalog books", str(len(indexes["by_uuid"])))
        table.add_row("Events scanned", str(len(all_events)))
        table.add_row("Already up-to-date", str(already_uptodate))
        table.add_row("Matched (total to update)", str(len(updates)))
        table.add_row("  via uuid", str(match_counts["uuid"]))
        table.add_row("  via hash", str(match_counts["hash"]))
        table.add_row("  via path", str(match_counts["path"]))
        table.add_row("  via title", str(match_counts["title"]))
        table.add_row("Unmatched", str(unmatched))
        console.print(table)

        if not updates:
            console.print("[green]✓[/green] Nothing to update.")
            return

        if dry_run:
            console.print(f"[yellow]Dry run:[/yellow] {len(updates)} event(s) would be updated.")
            return

        imported_total = 0
        try:
            for start in range(0, len(updates), batch_size):
                chunk = updates[start : start + batch_size]
                ndjson_body = "\n".join(json.dumps(item, ensure_ascii=False) for item in chunk) + "\n"
                resp = http.post(
                    "/events/import",
                    content=ndjson_body.encode("utf-8"),
                    headers={"Content-Type": "application/x-ndjson"},
                )
                resp.raise_for_status()
                imported_total += int(resp.json().get("imported", 0))
        except httpx.HTTPStatusError as exc:
            err.print(f"[red]Import error {exc.response.status_code}:[/red] {exc.response.text}")
            raise typer.Exit(1)
        except httpx.RequestError as exc:
            err.print(f"[red]Connection error during import:[/red] {exc}")
            raise typer.Exit(1)

    console.print(f"[green]✓[/green] Backfilled [bold]{imported_total}[/bold] event(s) in Biograph.")


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
