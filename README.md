# Biograph

> A personal life-logging tool that journals events from multiple sources into a single searchable timeline.

---

## Project layout

```
biograph/
├── backend/          — FastAPI + SQLite backend
├── sensors/
│   ├── shell/        — unified bash & zsh history sensor (Linux + macOS)
│   ├── kindle/       — Amazon Kindle clippings sensor
│   ├── kodi/         — Kodi movie playback sensor (service add-on)
│   └── cli/          — bio CLI logger and query tool (includes Tolino support)
├── browser-extension/— Chrome/Chromium MV3 extension
├── web-client/       — Vanilla JS + CSS single-page app
└── config.example.toml
```

---

## Backend — quick start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

### Install

```bash
cd backend
uv sync
```

### Configure

```bash
cp ../config.example.toml config.toml
# Edit config.toml — set a strong token and a db_path
```

### Run database migrations

```bash
cd backend
uv run alembic upgrade head
```

### Start the server

```bash
uv run biograph-server
# or
uv run python -m biograph.main
```

### Running as a systemd service (Arch Linux package)

If you installed the `biograph-backend` Arch Linux package, you can run the backend as a system-wide service:

```bash
sudo systemctl enable --now biograph-backend.service
```

Configuration is located at `/etc/biograph/config.toml` (secured with `0640` permissions), and the SQLite database file is located at `/var/lib/biograph/biograph.db`.

The API will be available at `http://127.0.0.1:8000`.
Interactive docs at `http://127.0.0.1:8000/docs`.


---

## API overview

All endpoints (except `GET /health`) require a `Authorization: Bearer <token>` header.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check (no auth) |
| `POST` | `/events/` | Create one event |
| `POST` | `/events/batch` | Bulk insert |
| `GET` | `/events/` | List / search events |
| `GET` | `/events/export` | Stream events in NDJSON format (ordered by `update_id` ASC) |
| `POST` | `/events/import` | Import events (NDJSON stream) performing upserts |
| `GET` | `/events/{id}` | Get a single event |
| `PATCH` | `/events/{id}` | Update tags or summary |
| `DELETE` | `/events/{id}` | Soft-delete an event |
| `GET` | `/stats/` | Aggregate counts by type |

### Query parameters for `GET /events/`

| Param | Type | Description |
|-------|------|-------------|
| `from` | ISO datetime | Start of time range |
| `to` | ISO datetime | End of time range |
| `ev_type` | str (repeatable) | Filter by event type(s) |
| `source_host` | str | Filter by hostname |
| `source_app` | str | Filter by app |
| `q` | str | Full-text search |
| `tags` | str (repeatable) | Events with ALL listed tags |
| `since_update_id` | int | Filter events with `update_id` greater than this value |
| `include_deleted` | bool | Include soft-deleted events (default false) |
| `resource_uri` | str | Filter events by exact resource URI |
| `limit` | int (1–1000, default 100) | Page size |
| `offset` | int (default 0) | Pagination offset |

---

## Running tests

```bash
cd backend
uv run pytest
```

---

## Event types and content schemas

| ev_type | Required content fields |
|---------|------------------------|
| `note` | `text: str`, `mood: str \| null` |
| `shell-cmd` | `cmd: str`, `exit_code: int \| null`, `cwd: str \| null` |
| `web-visit` | `url: str`, `title: str \| null`, `browser: str` |
| `kindle-highlight` | `book_title: str`, `author: str`, `highlight: str`, `location: int \| null` |
| `kindle-book` | `book_title: str`, `author: str`, `asin: str \| null`, `last_read: str \| null` |
| `tolino-highlight` | `book_title: str`, `author: str`, `highlight: str`, `annotation: str \| null`, `bookmark_id: str`, `location: str \| null` |
| `tolino-book` | `book_title: str`, `author: str`, `content_id: str`, `read_status: int`, `percent_read: int \| null`, `last_read: str` |
| `pocketbook-highlight` | `book_title: str`, `author: str`, `highlight: str`, `annotation: str \| null`, `bookmark_id: str`, `location: str \| null` |
| `pocketbook-book` | `book_title: str`, `author: str`, `content_id: str`, `percent_read: int`, `last_read: str` |
| `kodi-movie` | `title: str`, `year: int \| null`, `imdb_id: str \| null`, `db_id: int \| null`, `file: str`, `duration_seconds: int`, `progress_percent: float`, `finished: bool` |
| `kodi-tvshow` | `title: str`, `tvshow_title: str`, `season: int \| null`, `episode: int \| null`, `year: int \| null`, `imdb_id: str \| null`, `db_id: int \| null`, `file: str`, `duration_seconds: int`, `progress_percent: float`, `finished: bool` |
| `photo` | `path: str`, `caption: str \| null`, `lat: float \| null`, `lon: float \| null` |

---

## Client and Sensor Configuration

All clients (`bio` CLI) and sensors (like the unified shell history sensor) search for their settings in the following paths (first found wins):
1. The file pointed to by the `BIOGRAPH_CONFIG` environment variable.
2. `config.toml` in the current working directory.
3. `~/.config/biograph/config.toml` (recommended for user-level installations).
4. `/etc/biograph/config.toml` (recommended for system-wide service installations).

### Structure of `~/.config/biograph/config.toml`

When any client or sensor is run for the first time, a default template is automatically created at `~/.config/biograph/config.example.toml`. You can copy it to `config.toml` in the same directory:

```bash
cp ~/.config/biograph/config.example.toml ~/.config/biograph/config.toml
```

The configuration structure supports the following options:

```toml
[server]
url   = "http://127.0.0.1:8000"  # URL of the Biograph backend
token = "change-me"              # Authorization token to connect to the backend

[cli]
# source_host = "laptop"         # Optional override for the hostname reported by bio CLI

[shell]
# bash_history = "~/.bash_history" # Path to bash history file
# zsh_history  = "~/.zsh_history"  # Path to zsh history file
# state_dir    = "~/.local/share/biograph" # Directory to save sensor state and buffer
# max_age_days = 30              # On first run, import history from last N days (default: 30)

[resources]
# photos = "/home/user/Pictures"  # Local path to resolve {photos}/... URIs
# ebooks = "/home/user/Books"     # Local path to resolve {ebooks}/... URIs
```

### Resource URIs & Placeholders

Events can link to local files using machine-independent relative URIs (e.g. `{photos}/Album 1/Photo.jpg`). Local clients resolve these dynamically by replacing the placeholder key (`photos`) with the absolute path defined in the `[resources]` section of `config.toml`.

---

## Unified Shell History Sensor (Bash & Zsh)

Automatically journals shell commands from `~/.bash_history` and `~/.zsh_history` as `shell-cmd` events to the Biograph backend.

The sensor auto-detects whichever shell history files exist on your machine and watches them simultaneously in a single process.

### Shell Configuration

To enable accurate timestamps and immediate history logging:

**For Bash** (`~/.bashrc`):
```bash
# Record timestamps in bash history
export HISTTIMEFORMAT="%F %T "

# Append history instead of overwriting
shopt -s histappend

# Append commands immediately so the sensor sees them live
PROMPT_COMMAND="history -a; ${PROMPT_COMMAND:-}"
```

**For Zsh** (`~/.zshrc`):
```zsh
# Save timestamp and duration in EXTENDED_HISTORY format
setopt EXTENDED_HISTORY

# Append new history lines immediately to the history file
setopt INC_APPEND_HISTORY
```

### Install

```bash
cd sensors/shell
uv sync
```

*Note: `uv sync` installs the `biograph-sensor-shell` executable (and compatibility alias `biograph-sensor-zsh`) into `.venv/bin/` within the `sensors/shell` directory.*

### Run as a service

**Linux (systemd user service)**
1. Copy the service unit:
   ```bash
   cp biograph-shell.service ~/.config/systemd/user/
   ```
2. Edit `~/.config/systemd/user/biograph-shell.service` to set `ExecStart` to the absolute path of the executable (e.g. `/home/user/Biograph/sensors/shell/.venv/bin/biograph-sensor-shell`).
3. Enable and start the service:
   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now biograph-shell
   journalctl --user -fu biograph-shell   # follow logs
   ```

**macOS (launchd user agent)**
1. Copy the plist:
   ```bash
   cp biograph-shell.plist ~/Library/LaunchAgents/io.biograph.sensor.shell.plist
   ```
2. Edit the plist file to set the absolute path of the executable (e.g. `/Users/user/Biograph/sensors/shell/.venv/bin/biograph-sensor-shell`).
3. Load the agent:
   ```bash
   launchctl load -w ~/Library/LaunchAgents/io.biograph.sensor.shell.plist
   tail -f /tmp/biograph-shell.log        # follow logs
   ```

### Config

Add a `[shell]` section to `config.toml` (optional, defaults shown):

```toml
[shell]
bash_history = "~/.bash_history"          # default
zsh_history  = "~/.zsh_history"           # default
state_dir    = "~/.local/share/biograph"  # default
max_age_days = 30                         # on first run, import history from last N days
```

*(Note: If you have an existing `[zsh]` section in your `config.toml`, it is still read for backwards compatibility if `[shell]` is omitted.)*

### Upgrading from the zsh sensor to the unified shell sensor

If you were running the older `biograph-sensor-zsh` service:

1. **Stop and disable the old service**:
   * *Linux (systemd)*:
     ```bash
     systemctl --user stop biograph-zsh
     systemctl --user disable biograph-zsh
     rm -f ~/.config/systemd/user/biograph-zsh.service
     ```
   * *macOS (launchd)*:
     ```bash
     launchctl unload -w ~/Library/LaunchAgents/io.biograph.sensor.zsh.plist
     rm -f ~/Library/LaunchAgents/io.biograph.sensor.zsh.plist
     ```

2. **Deploy the new unified service**:
   * Install dependencies in `sensors/shell`:
     ```bash
     cd sensors/shell
     uv sync
     ```
   * Set up systemd or launchd as shown above using `biograph-shell.service` or `biograph-shell.plist`.

3. **Automatic State & Buffer Migration**:
   * When `biograph-sensor-shell` starts, it automatically detects any existing `~/.local/share/biograph/zsh-state.json` and `zsh-buffer.json` and migrates them into `shell-state.json` and `shell-buffer.json`. No shell history positions or queued offline events are lost.

4. **Update `config.toml` (optional)**:
   * Rename `[zsh]` to `[shell]` in `~/.config/biograph/config.toml`.

---

## bio CLI

Log notes and query your timeline from the terminal.

### Install

```bash
cd sensors/cli
uv sync
# add .venv/bin to PATH or use: uv run bio
```

### Usage

```bash
bio log "Had a great hike" --tags outdoor,health
bio log --mood happy "Finished reading Dune"
bio log                          # opens $EDITOR (fallback: nano)
bio search "hiking" --limit 10
bio search "git" --type shell-cmd --from 2024-01-01
```

---

## Chrome/Chromium Browser Sensor

Automatically logs visited webpage URLs and titles to your Biograph timeline.

### Install

1. Open Chrome or any Chromium-based browser (Brave, Edge, Vivaldi).
2. Navigate to `chrome://extensions/`.
3. Enable **Developer mode** (toggle in the top-right corner).
4. Click **Load unpacked** (top-left button).
5. Select the `browser-extension` directory from the root of this project.

### Configure

1. Once loaded, click the extension's icon (or open `chrome://extensions` and click **Details** -> **Extension options**).
2. Provide your connection settings:
   - **Server URL**: The URL of your running Biograph backend (e.g., `http://127.0.0.1:8000`).
   - **Access Token**: The bearer token configured in your server's `config.toml`.
   - **Device Name**: A label to identify this browser (e.g., `laptop-chrome`).
3. Click **Save Settings**.
4. Click **Test Connection** to verify connection health and credentials authentication.

---

## Kindle Clippings Sensor

Automatically parses and journals books (`kindle-book` events) and highlights (`kindle-highlight` events) when your Amazon Kindle is connected over USB. Supports importing from multiple Kindle devices.

### Manual & Auto-detect Usage

Import clippings by providing the mount path to your Kindle, or omit the path to auto-detect and import from all connected Kindles:

```bash
bio kindle /run/media/user/Kindle   # Linux manual
# or
bio kindle /Volumes/Kindle           # macOS manual
# or
bio kindle                           # Auto-detect all connected devices
```

### USB Automount Service

**Linux (systemd user service)**
1. Copy the path and service units:
   ```bash
   cp sensors/kindle/biograph-kindle.path ~/.config/systemd/user/
   cp sensors/kindle/biograph-kindle.service ~/.config/systemd/user/
   ```
2. Enable and start the path watcher:
   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now biograph-kindle.path
   ```
   *The service will trigger automatically whenever your Kindle mounts at `/run/media/$USER/Kindle`.*

**macOS (launchd user agent)**
1. Copy the plist:
   ```bash
   cp sensors/kindle/biograph-kindle.plist ~/Library/LaunchAgents/io.biograph.sensor.kindle.plist
   ```
2. Load the agent:
   ```bash
   launchctl load -w ~/Library/LaunchAgents/io.biograph.sensor.kindle.plist
   ```

---

## Tolino eReader Sensor

Integrated directly into the `bio` CLI, this sensor imports book progress (`tolino-book` events) and highlights (`tolino-highlight` events) from Tolino/Kobo eReader devices running 5.x firmware. Supports importing from multiple Tolino devices.

### Manual & Auto-detect Usage

Import book stats and highlights by mounting your Tolino eReader over USB and specifying the path, or omit the path to auto-detect and import from all connected Tolino eReaders:

```bash
bio tolino /run/media/user/eReader   # Linux manual
# or
bio tolino /Volumes/eReader          # macOS manual
# or
bio tolino                           # Auto-detect all connected devices
```

### State Partitioning

Sync state is stored locally inside `~/.local/share/biograph/tolino_state_<hash>.json`, where `<hash>` is derived from the server URL. This ensures your progress isn't missed or duplicated when switching between different backend targets (e.g., local development vs. remote server).

---

## PocketBook eReader Sensor

Integrated directly into the `bio` CLI, this sensor imports book progress (`pocketbook-book` events) and highlights (`pocketbook-highlight` events) from PocketBook devices. Supports importing from multiple PocketBook devices.

### Manual & Auto-detect Usage

Import book progress and highlights by mounting your PocketBook eReader over USB (PC-Link mode) and specifying the path, or omit the path to auto-detect and import from all connected PocketBooks (looks for mount folders starting with `PB`, e.g., `/run/media/user/PB634`):

```bash
bio pocketbook /run/media/user/PB634 # Linux manual
# or
bio pocketbook /Volumes/PB634        # macOS manual
# or
bio pocketbook                       # Auto-detect all connected devices
```

### State Partitioning

Sync state is stored locally inside `~/.local/share/biograph/pocketbook_state_<hash>.json`, where `<hash>` is derived from the server URL. This ensures your progress isn't missed or duplicated when switching between different backend targets (e.g., local development vs. remote server).

---

## Kodi Media Logger

A background service add-on for Kodi that automatically logs movie (`kodi-movie`) and TV series (`kodi-tvshow`) playback events to your Biograph timeline.

### Features

- **Automatic Logging:** Watches playback in the background. Logs an event as soon as a movie finishes naturally or when manually stopped after watching 85% or more of the runtime.
- **Zero Config:** Automatically reads your server URL and token from your system's existing Biograph configuration files (e.g. `~/.config/biograph/config.toml`).
- **Rich Metadata:** Captures movie Title, Release Year, IMDb ID, duration (in seconds), play progress (%), and watch status.

### Installation

For detailed installation options (including zip files and service configuration), refer to the **[Kodi Sensor README](sensors/kodi/README.md)**.

---

## Import, Export, and Backup

Manage database state, migrations, and backups directly from the command line:

```bash
# Export all events in NDJSON format
bio export backup.ndjson

# Export events in a specific time range
bio export backup.ndjson --from 2026-01-01T00:00:00 --to 2026-06-30T23:59:59

# Export incrementally since a specific update_id mark, including deleted events
bio export diff.ndjson --since 123 --include-deleted

# Ingest an NDJSON dump (performs upserts for existing IDs/remote_ids)
bio import backup.ndjson

# Create a timestamped backup copy of your database
bio backup
```

---

## TLS & HTTPS Configuration

To secure communication between your sensors and the backend over local networks, you can enable HTTPS. 

Refer to the detailed **[TLS & HTTPS Setup Guide](docs/TLS.md)** for step-by-step instructions on generating certificates and configuring root CA trust on your devices.

---

## Implementation status

- [x] **Phase 1** — Core backend (FastAPI, SQLite, auth, events API, stats, tests)
- [x] **Phase 2** — Unified shell sensor (bash & zsh history parser, buffer, retry, systemd/launchd) + `bio log` / `bio search` CLI
- [x] **Phase 3** — Web client v1 (Timeline, Search, Settings)
- [x] **Phase 4** — Chrome/Chromium browser extension
- [x] **Phase 5** — Kindle sensor + export/import
- [x] **Phase 6** — Web client v2 (Stats, Tag Manager, virtual scroll)
- [x] **Phase 7** — Tolino eReader support & Kodi service logger
- [x] **Phase 8** — PocketBook eReader support & multi-device imports
