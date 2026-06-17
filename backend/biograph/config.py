"""Configuration loading for the Biograph backend."""

from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    token: str = "change-me"
    db_path: str = "biograph.db"


class TLSConfig(BaseModel):
    enabled: bool = False
    certfile: str = ""
    keyfile: str = ""


class Config(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    tls: TLSConfig = Field(default_factory=TLSConfig)


_DEFAULT_CONFIG_PATHS: list[Path] = [
    Path("config.toml"),
    Path.home() / ".config" / "biograph" / "config.toml",
    Path("/etc/biograph/config.toml"),
]


def load_config(path: Path | None = None) -> Config:
    """Load configuration from a TOML file.

    Resolution order (first found wins):
    1. *path* argument (if supplied)
    2. ``BIOGRAPH_CONFIG`` environment variable
    3. ``config.toml`` in the current directory
    4. ``~/.config/biograph/config.toml``
    5. ``/etc/biograph/config.toml``

    Returns a default :class:`Config` when no file is found.
    """
    if path is not None:
        candidates: list[Path] = [path]
    elif env := os.environ.get("BIOGRAPH_CONFIG"):
        candidates = [Path(env)]
    else:
        candidates = _DEFAULT_CONFIG_PATHS

    for candidate in candidates:
        if candidate.exists():
            with open(candidate, "rb") as fh:
                data = tomllib.load(fh)
            return Config.model_validate(data)

    return Config()


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Return the application-wide :class:`Config` singleton."""
    return load_config()
