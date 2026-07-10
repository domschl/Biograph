"""SQLModel table definition and Pydantic request/response schemas."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel
from sqlmodel import Field, SQLModel


# ---------------------------------------------------------------------------
# Database table
# ---------------------------------------------------------------------------


class Event(SQLModel, table=True):
    """Immutable life-event record persisted in SQLite.

    Mutable fields (editable via PATCH): *tags*, *summary*.
    All other fields are set at creation time and never changed.
    Deletion is soft: ``deleted_at`` is set instead of removing the row.
    """

    __tablename__ = "events"

    id: int | None = Field(default=None, primary_key=True)
    timestamp: datetime = Field(index=True)
    received_at: datetime = Field(index=True)
    ev_type: str = Field(index=True, max_length=64)
    source_host: str | None = Field(default=None, index=True)
    source_app: str | None = Field(default=None, index=True)
    content: str = Field(default="{}")   # JSON-encoded dict[str, Any]
    tags: str = Field(default="[]")      # JSON-encoded list[str]
    summary: str | None = Field(default=None)
    deleted_at: datetime | None = Field(default=None)
    remote_id: str | None = Field(default=None, index=True)
    update_id: int | None = Field(default=None, index=True)
    resource_uri: str | None = Field(default=None, index=True)


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class EventCreate(BaseModel):
    timestamp: datetime
    ev_type: str
    source_host: str | None = None
    source_app: str | None = None
    content: dict[str, Any] = {}
    tags: list[str] = []
    summary: str | None = None
    remote_id: str | None = None
    resource_uri: str | None = None


class EventUpdate(BaseModel):
    """Only the two mutable fields are exposed here."""

    tags: list[str] | None = None
    summary: str | None = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class EventRead(BaseModel):
    id: int
    timestamp: datetime
    received_at: datetime
    ev_type: str
    source_host: str | None
    source_app: str | None
    content: dict[str, Any]
    tags: list[str]
    summary: str | None
    deleted_at: datetime | None
    remote_id: str | None
    update_id: int | None
    resource_uri: str | None

    @classmethod
    def from_event(cls, event: Event) -> EventRead:
        """Deserialize JSON-encoded fields from the ORM object."""
        return cls(
            id=event.id,  # type: ignore[arg-type]
            timestamp=event.timestamp.replace(tzinfo=timezone.utc) if event.timestamp.tzinfo is None else event.timestamp,
            received_at=event.received_at.replace(tzinfo=timezone.utc) if event.received_at.tzinfo is None else event.received_at,
            ev_type=event.ev_type,
            source_host=event.source_host,
            source_app=event.source_app,
            content=json.loads(event.content),
            tags=json.loads(event.tags),
            summary=event.summary,
            deleted_at=event.deleted_at.replace(tzinfo=timezone.utc) if event.deleted_at and event.deleted_at.tzinfo is None else event.deleted_at,
            remote_id=event.remote_id,
            update_id=event.update_id,
            resource_uri=event.resource_uri,
        )


class EventList(BaseModel):
    items: list[EventRead]
    total: int
    limit: int
    offset: int
