"""Events API router — /events."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from biograph.auth import require_token
from biograph.database import get_session
from biograph.models import Event, EventCreate, EventList, EventRead, EventUpdate

router = APIRouter(prefix="/events", tags=["events"])

# Reusable dependency aliases
Authenticated = Annotated[None, Depends(require_token)]
Session = Annotated[AsyncSession, Depends(get_session)]


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@router.post("/", response_model=EventRead, status_code=status.HTTP_201_CREATED)
async def create_event(
    body: EventCreate,
    _: Authenticated,
    session: Session,
) -> EventRead:
    """Create a single event."""
    event = Event(
        timestamp=body.timestamp,
        received_at=datetime.now(UTC),
        ev_type=body.ev_type,
        source_host=body.source_host,
        source_app=body.source_app,
        content=json.dumps(body.content),
        tags=json.dumps(body.tags),
        summary=body.summary,
    )
    session.add(event)
    await session.commit()
    await session.refresh(event)
    return EventRead.from_event(event)


@router.post(
    "/batch",
    response_model=list[EventRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_events_batch(
    body: list[EventCreate],
    _: Authenticated,
    session: Session,
) -> list[EventRead]:
    """Bulk-insert events (used by sensors sending offline batches)."""
    if not body:
        return []
    now = datetime.now(UTC)
    events = [
        Event(
            timestamp=e.timestamp,
            received_at=now,
            ev_type=e.ev_type,
            source_host=e.source_host,
            source_app=e.source_app,
            content=json.dumps(e.content),
            tags=json.dumps(e.tags),
            summary=e.summary,
        )
        for e in body
    ]
    session.add_all(events)
    await session.commit()
    for ev in events:
        await session.refresh(ev)
    return [EventRead.from_event(ev) for ev in events]


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


@router.get("/", response_model=EventList)
async def list_events(
    _: Authenticated,
    session: Session,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    ev_type: list[str] | None = Query(default=None),
    source_host: str | None = Query(default=None),
    source_app: str | None = Query(default=None),
    q: str | None = Query(default=None),
    tags: list[str] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> EventList:
    """List / search events with optional filters.

    Results are ordered newest-first (``timestamp DESC``).
    Pagination is offset-based via ``limit`` and ``offset``.
    """
    base = select(Event).where(Event.deleted_at.is_(None))

    if from_:
        base = base.where(Event.timestamp >= from_)
    if to:
        base = base.where(Event.timestamp <= to)
    if ev_type:
        if "kodi-movie" in ev_type:
            if "web-visit" in ev_type:
                base = base.where(Event.ev_type.in_(ev_type))
            else:
                other_types = [t for t in ev_type if t != "kodi-movie"]
                conditions = [
                    Event.ev_type == "kodi-movie",
                    (Event.ev_type == "web-visit")
                    & Event.content.like("%youtube.com/watch?v=%"),
                ]
                if other_types:
                    conditions.append(Event.ev_type.in_(other_types))
                base = base.where(or_(*conditions))
        else:
            base = base.where(Event.ev_type.in_(ev_type))
    if source_host:
        base = base.where(Event.source_host == source_host)
    if source_app:
        base = base.where(Event.source_app == source_app)
    if q:
        pattern = f"%{q}%"
        base = base.where(
            Event.content.like(pattern)
            | Event.summary.like(pattern)
            | Event.tags.like(pattern)
        )
    if tags:
        # All listed tags must be present (AND semantics)
        for tag in tags:
            base = base.where(Event.tags.like(f'%"{tag}"%'))

    # Total count (before pagination)
    count_stmt = select(func.count()).select_from(base.subquery())
    total: int = (await session.execute(count_stmt)).scalar_one()

    # Paginated results
    stmt = base.order_by(Event.timestamp.desc()).offset(offset).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()

    return EventList(
        items=[EventRead.from_event(e) for e in rows],
        total=total,
        limit=limit,
        offset=offset,
    )

# ---------------------------------------------------------------------------
# Import / Export
# ---------------------------------------------------------------------------


@router.get("/export", response_class=StreamingResponse)
async def export_events(
    _: Authenticated,
    session: Session,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
) -> StreamingResponse:
    """Stream all non-deleted events in NDJSON format (ordered oldest-first)."""
    async def event_generator():
        stmt = select(Event).where(Event.deleted_at.is_(None)).order_by(Event.timestamp.asc())
        if from_:
            stmt = stmt.where(Event.timestamp >= from_)
        if to:
            stmt = stmt.where(Event.timestamp <= to)
            
        result = await session.execute(stmt)
        for row in result.scalars():
            event_read = EventRead.from_event(row)
            yield json.dumps(event_read.model_dump(mode="json")) + "\n"
            
    return StreamingResponse(event_generator(), media_type="application/x-ndjson")


@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_events(
    request: Request,
    _: Authenticated,
    session: Session,
) -> dict[str, int]:
    """Import events from an NDJSON stream."""
    count = 0
    now = datetime.now(UTC)
    buffer = ""
    
    async for chunk in request.stream():
        buffer += chunk.decode("utf-8")
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                ts = datetime.fromisoformat(data["timestamp"])
                tags_list = data.get("tags") or []
                if not isinstance(tags_list, list):
                    tags_list = [tags_list]
                
                event = Event(
                    timestamp=ts,
                    received_at=now,
                    ev_type=data["ev_type"],
                    source_host=data.get("source_host"),
                    source_app=data.get("source_app"),
                    content=json.dumps(data.get("content") or {}),
                    tags=json.dumps(tags_list),
                    summary=data.get("summary"),
                )
                session.add(event)
                count += 1
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to parse or save NDJSON line: {e}"
                )
                
    if count > 0:
        await session.commit()
        
    return {"imported": count}


@router.get("/{event_id}", response_model=EventRead)
async def get_event(
    event_id: int,
    _: Authenticated,
    session: Session,
) -> EventRead:
    """Fetch a single event by its ID."""
    event = await session.get(Event, event_id)
    if event is None or event.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return EventRead.from_event(event)


# ---------------------------------------------------------------------------
# Update / Delete
# ---------------------------------------------------------------------------


@router.patch("/{event_id}", response_model=EventRead)
async def update_event(
    event_id: int,
    body: EventUpdate,
    _: Authenticated,
    session: Session,
) -> EventRead:
    """Update the mutable fields of an event (tags and/or summary)."""
    event = await session.get(Event, event_id)
    if event is None or event.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

    if body.tags is not None:
        event.tags = json.dumps(body.tags)
    if body.summary is not None:
        event.summary = body.summary

    session.add(event)
    await session.commit()
    await session.refresh(event)
    return EventRead.from_event(event)


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: int,
    _: Authenticated,
    session: Session,
) -> None:
    """Soft-delete an event (sets ``deleted_at``; row is retained)."""
    event = await session.get(Event, event_id)
    if event is None or event.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

    event.deleted_at = datetime.now(UTC)
    session.add(event)
    await session.commit()
