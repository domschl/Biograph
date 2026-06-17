"""Biograph FastAPI application entry point."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from fastapi.middleware.cors import CORSMiddleware
from biograph.api.events import router as events_router
from biograph.api.stats import router as stats_router
from biograph.config import get_config
from biograph.database import create_db_tables


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Create database tables on startup (idempotent)."""
    await create_db_tables()
    yield


app = FastAPI(
    title="Biograph",
    description="Personal life-logging backend",
    version="0.1.0",
    lifespan=lifespan,
)

# Enable CORS for cross-origin client and extension connections
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(events_router)
app.include_router(stats_router)



@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Unauthenticated liveness check."""
    return {"status": "ok"}


# Serve the web client as static files from the same process.
# The mount must be last so it doesn't shadow API routes.
_web_client_dir = Path(__file__).parent.parent.parent / "web-client"
if not _web_client_dir.exists():
    _web_client_dir = Path("/usr/share/biograph/web-client")

if _web_client_dir.exists():
    app.mount(
        "/",
        StaticFiles(directory=str(_web_client_dir), html=True),
        name="web-client",
    )


def main() -> None:
    """Entry point for the ``biograph-server`` CLI script."""
    config = get_config()
    ssl_kwargs: dict[str, str] = {}
    if config.tls.enabled:
        ssl_kwargs = {
            "ssl_certfile": config.tls.certfile,
            "ssl_keyfile": config.tls.keyfile,
        }
    uvicorn.run(
        "biograph.main:app",
        host=config.server.host,
        port=config.server.port,
        reload=False,
        **ssl_kwargs,  # type: ignore[arg-type]
    )


if __name__ == "__main__":
    main()
