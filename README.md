# Biograph

> A personal life-logging tool that journals events from multiple sources into a single searchable timeline.

---

## Project layout

```
biograph/
├── backend/          — FastAPI + SQLite backend
├── sensors/
│   ├── zsh/          — zsh history sensor (Linux + macOS)
│   ├── kindle/       — Amazon Kindle clippings sensor
│   └── cli/          — bio CLI logger and query tool
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
| `photo` | `path: str`, `caption: str \| null`, `lat: float \| null`, `lon: float \| null` |

---

## zsh History Sensor

Automatically journals shell commands from `~/.zsh_history` (EXTENDED_HISTORY
format) as `shell-cmd` events.

### Install

```bash
cd sensors/zsh
uv sync
```

### Run as a service

**Linux (systemd user service)**
```bash
cp biograph-zsh.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now biograph-zsh
journalctl --user -fu biograph-zsh   # follow logs
```

**macOS (launchd user agent)**
```bash
cp biograph-zsh.plist ~/Library/LaunchAgents/io.biograph.sensor.zsh.plist
# Edit the plist to set the full path of biograph-sensor-zsh if needed
launchctl load -w ~/Library/LaunchAgents/io.biograph.sensor.zsh.plist
tail -f /tmp/biograph-zsh.log        # follow logs
```

### Config

Add a `[zsh]` section to `config.toml`:

```toml
[zsh]
history_file  = "~/.zsh_history"  # default
state_dir     = "~/.local/share/biograph"  # default
max_age_days  = 30   # on first run, import history from the last N days
```

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

```toml
[tls]
enabled  = true
certfile = "/path/to/cert.pem"
keyfile  = "/path/to/key.pem"
```

Sensors must be configured to trust your self-signed CA.

---

## Implementation status

- [x] **Phase 1** — Core backend (FastAPI, SQLite, auth, events API, stats, tests)
- [x] **Phase 2** — zsh sensor (EXTENDED_HISTORY parser, buffer, retry, systemd/launchd) + `bio log` / `bio search` CLI
- [x] **Phase 3** — Web client v1 (Timeline, Search, Settings)
- [x] **Phase 4** — Chrome/Chromium browser extension
- [ ] Phase 5 — Kindle sensor + export/import
- [ ] Phase 6 — Web client v2 (Stats, Tag Manager, virtual scroll)
