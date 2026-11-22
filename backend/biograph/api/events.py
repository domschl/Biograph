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


def is_ereader_event(ev_type: str) -> bool:
    """Check if the event type belongs to an EReader."""
    return any(
        ev_type.startswith(prefix)
        for prefix in ("kindle-", "tolino-", "pocketbook-", "koreader-", "kosync-")
    )


def _normalize_dt(dt: datetime) -> datetime:
    """Normalize datetime to timezone-aware UTC for consistent storage and comparison."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


async def _get_next_update_id(session: AsyncSession) -> int:
    """Query the database for the current maximum update_id and return the next sequential integer."""
    stmt = select(func.max(Event.update_id))
    result = await session.execute(stmt)
    max_id = result.scalar()
    return (max_id or 0) + 1


@router.post("/", response_model=EventRead, status_code=status.HTTP_201_CREATED)
async def create_event(
    body: EventCreate,
    _: Authenticated,
    session: Session,
) -> EventRead:
    """Create a single event."""
    if body.remote_id:
        stmt = select(Event).where(
            Event.deleted_at.is_(None),
            Event.ev_type == body.ev_type,
            Event.remote_id == body.remote_id,
        )
        existing = (await session.execute(stmt)).scalars().first()
        if existing:
            return EventRead.from_event(existing)

    normalized_ts = _normalize_dt(body.timestamp)

    if is_ereader_event(body.ev_type):
        stmt = select(Event).where(
            Event.deleted_at.is_(None),
            Event.timestamp == normalized_ts,
            Event.ev_type == body.ev_type,
        )
        existing = (await session.execute(stmt)).scalars().first()
        if existing:
            return EventRead.from_event(existing)

    if body.ev_type == "calibre-book":
        uuid = body.content.get("uuid")
        if uuid:
            stmt = select(Event).where(
                Event.deleted_at.is_(None),
                Event.ev_type == "calibre-book",
                Event.content.like(f'%"uuid": "{uuid}"%'),
            )
            existing = (await session.execute(stmt)).scalars().first()
            if existing:
                return EventRead.from_event(existing)

    next_update_id = await _get_next_update_id(session)
    event = Event(
        timestamp=normalized_ts,
        received_at=datetime.now(UTC),
        ev_type=body.ev_type,
        source_host=body.source_host,
        source_app=body.source_app,
        content=json.dumps(body.content),
        tags=json.dumps(body.tags),
        summary=body.summary,
        remote_id=body.remote_id,
        update_id=next_update_id,
        resource_uri=body.resource_uri,
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

    # Separate events with remote_id for deduplication pre-fetching
    remote_id_events = [e for e in body if e.remote_id]
    existing_remote_id_map = {}
    if remote_id_events:
        remote_ids = [e.remote_id for e in remote_id_events]
        ev_types = list({e.ev_type for e in remote_id_events})
        stmt = select(Event).where(
            Event.deleted_at.is_(None),
            Event.remote_id.in_(remote_ids),
            Event.ev_type.in_(ev_types),
        )
        db_existing = (await session.execute(stmt)).scalars().all()
        for ex in db_existing:
            existing_remote_id_map[(ex.remote_id, ex.ev_type)] = ex

    # Separate EReader events for deduplication pre-fetching
    ereader_events = [e for e in body if is_ereader_event(e.ev_type) and not e.remote_id]
    existing_ereader_map = {}
    if ereader_events:
        timestamps = [_normalize_dt(e.timestamp) for e in ereader_events]
        ev_types = list({e.ev_type for e in ereader_events})

        # Batch query matching existing ereader events
        stmt = select(Event).where(
            Event.deleted_at.is_(None),
            Event.timestamp.in_(timestamps),
            Event.ev_type.in_(ev_types),
        )
        db_existing = (await session.execute(stmt)).scalars().all()
        for ex in db_existing:
            existing_ereader_map[(_normalize_dt(ex.timestamp), ex.ev_type)] = ex

    # Separate calibre-book events for deduplication pre-fetching (fallback for items without remote_id)
    calibre_events = [e for e in body if e.ev_type == "calibre-book" and not e.remote_id]
    existing_calibre_map = {}
    if calibre_events:
        conditions = []
        for e in calibre_events:
            if uuid := e.content.get("uuid"):
                conditions.append(Event.content.like(f'%"uuid": "{uuid}"%'))
        if conditions:
            stmt = select(Event).where(
                Event.deleted_at.is_(None),
                Event.ev_type == "calibre-book",
                or_(*conditions),
            )
            db_existing = (await session.execute(stmt)).scalars().all()
            for ex in db_existing:
                try:
                    ex_content = json.loads(ex.content)
                    if ex_uuid := ex_content.get("uuid"):
                        existing_calibre_map[ex_uuid] = ex
                except Exception:
                    pass

    next_update_id = await _get_next_update_id(session)
    events_to_insert = []
    response_events = []

    for e in body:
        ts = _normalize_dt(e.timestamp)
        if e.remote_id:
            key = (e.remote_id, e.ev_type)
            dup = existing_remote_id_map.get(key)

            # Also check for duplicates within the incoming batch itself
            if not dup:
                for inserted in events_to_insert:
                    if inserted.remote_id == key[0] and inserted.ev_type == key[1]:
                        dup = inserted
                        break

            if dup:
                response_events.append(dup)
            else:
                new_event = Event(
                    timestamp=ts,
                    received_at=now,
                    ev_type=e.ev_type,
                    source_host=e.source_host,
                    source_app=e.source_app,
                    content=json.dumps(e.content),
                    tags=json.dumps(e.tags),
                    summary=e.summary,
                    remote_id=e.remote_id,
                    update_id=next_update_id + len(events_to_insert),
                    resource_uri=e.resource_uri,
                )
                events_to_insert.append(new_event)
                response_events.append(new_event)
        elif is_ereader_event(e.ev_type):
            key = (ts, e.ev_type)
            dup = existing_ereader_map.get(key)

            # Also check for duplicates within the incoming batch itself
            if not dup:
                for inserted in events_to_insert:
                    if _normalize_dt(inserted.timestamp) == key[0] and inserted.ev_type == key[1]:
                        dup = inserted
                        break

            if dup:
                response_events.append(dup)
            else:
                new_event = Event(
                    timestamp=ts,
                    received_at=now,
                    ev_type=e.ev_type,
                    source_host=e.source_host,
                    source_app=e.source_app,
                    content=json.dumps(e.content),
                    tags=json.dumps(e.tags),
                    summary=e.summary,
                    remote_id=e.remote_id,
                    update_id=next_update_id + len(events_to_insert),
                    resource_uri=e.resource_uri,
                )
                events_to_insert.append(new_event)
                response_events.append(new_event)
        elif e.ev_type == "calibre-book":
            uuid = e.content.get("uuid")
            dup = existing_calibre_map.get(uuid) if uuid else None

            # Also check for duplicates within the incoming batch itself
            if not dup and uuid:
                for inserted in events_to_insert:
                    if inserted.ev_type == "calibre-book":
                        try:
                            ins_content = json.loads(inserted.content)
                            if ins_content.get("uuid") == uuid:
                                dup = inserted
                                break
                        except Exception:
                            pass

            if dup:
                response_events.append(dup)
            else:
                new_event = Event(
                    timestamp=ts,
                    received_at=now,
                    ev_type=e.ev_type,
                    source_host=e.source_host,
                    source_app=e.source_app,
                    content=json.dumps(e.content),
                    tags=json.dumps(e.tags),
                    summary=e.summary,
                    remote_id=e.remote_id,
                    update_id=next_update_id + len(events_to_insert),
                    resource_uri=e.resource_uri,
                )
                events_to_insert.append(new_event)
                response_events.append(new_event)
        else:
            new_event = Event(
                timestamp=ts,
                received_at=now,
                ev_type=e.ev_type,
                source_host=e.source_host,
                source_app=e.source_app,
                content=json.dumps(e.content),
                tags=json.dumps(e.tags),
                summary=e.summary,
                remote_id=e.remote_id,
                update_id=next_update_id + len(events_to_insert),
                resource_uri=e.resource_uri,
            )
            events_to_insert.append(new_event)
            response_events.append(new_event)

    if events_to_insert:
        session.add_all(events_to_insert)
        await session.commit()
        for ev in events_to_insert:
            await session.refresh(ev)

    return [EventRead.from_event(ev) for ev in response_events]


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
    since_update_id: int | None = Query(default=None),
    include_deleted: bool = Query(default=False),
    resource_uri: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> EventList:
    """List / search events with optional filters.

    Results are ordered newest-first (``timestamp DESC``).
    Pagination is offset-based via ``limit`` and ``offset``.
    """
    base = select(Event)
    if not include_deleted:
        base = base.where(Event.deleted_at.is_(None))

    if from_:
        base = base.where(Event.timestamp >= _normalize_dt(from_))
    if to:
        base = base.where(Event.timestamp <= _normalize_dt(to))
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
    if since_update_id is not None:
        base = base.where(Event.update_id > since_update_id)
    if resource_uri:
        base = base.where(Event.resource_uri == resource_uri)

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
    since_update_id: int | None = Query(default=None),
    include_deleted: bool = Query(default=False),
) -> StreamingResponse:
    """Stream events in NDJSON format (ordered by update_id asc)."""
    async def event_generator():
        stmt = select(Event).order_by(Event.update_id.asc())
        if not include_deleted:
            stmt = stmt.where(Event.deleted_at.is_(None))
        if from_:
            stmt = stmt.where(Event.timestamp >= _normalize_dt(from_))
        if to:
            stmt = stmt.where(Event.timestamp <= _normalize_dt(to))
        if since_update_id is not None:
            stmt = stmt.where(Event.update_id > since_update_id)
            
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
    """Import events from an NDJSON stream, performing upsert by ID or remote_id."""
    count = 0
    now = datetime.now(UTC)
    buffer = ""
    next_update_id = await _get_next_update_id(session)
    
    async for chunk in request.stream():
        buffer += chunk.decode("utf-8")
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                ts = _normalize_dt(datetime.fromisoformat(data["timestamp"]))
                tags_list = data.get("tags") or []
                if not isinstance(tags_list, list):
                    tags_list = [tags_list]
                
                # Try finding existing record by ID or remote_id
                existing = None
                if "id" in data and data["id"] is not None:
                    existing = await session.get(Event, data["id"])
                
                if not existing and data.get("remote_id"):
                    stmt = select(Event).where(
                        Event.remote_id == data["remote_id"],
                        Event.ev_type == data["ev_type"],
                    )
                    existing = (await session.execute(stmt)).scalars().first()
                
                if existing:
                    # Update fields
                    existing.timestamp = ts
                    if "received_at" in data and data["received_at"] is not None:
                        existing.received_at = _normalize_dt(datetime.fromisoformat(data["received_at"]))
                    existing.ev_type = data["ev_type"]
                    existing.source_host = data.get("source_host")
                    existing.source_app = data.get("source_app")
                    existing.content = json.dumps(data.get("content") or {})
                    existing.tags = json.dumps(tags_list)
                    existing.summary = data.get("summary")
                    if "deleted_at" in data and data["deleted_at"] is not None:
                        existing.deleted_at = _normalize_dt(datetime.fromisoformat(data["deleted_at"]))
                    else:
                        existing.deleted_at = None
                    existing.remote_id = data.get("remote_id")
                    existing.resource_uri = data.get("resource_uri")
                    
                    if "update_id" in data and data["update_id"] is not None:
                        existing.update_id = data["update_id"]
                    else:
                        existing.update_id = next_update_id
                        next_update_id += 1
                        
                    session.add(existing)
                else:
                    event = Event(
                        id=data.get("id"),
                        timestamp=ts,
                        received_at=_normalize_dt(datetime.fromisoformat(data["received_at"])) if data.get("received_at") is not None else now,
                        ev_type=data["ev_type"],
                        source_host=data.get("source_host"),
                        source_app=data.get("source_app"),
                        content=json.dumps(data.get("content") or {}),
                        tags=json.dumps(tags_list),
                        summary=data.get("summary"),
                        deleted_at=_normalize_dt(datetime.fromisoformat(data["deleted_at"])) if data.get("deleted_at") is not None else None,
                        remote_id=data.get("remote_id"),
                        resource_uri=data.get("resource_uri"),
                    )
                    if "update_id" in data and data["update_id"] is not None:
                        event.update_id = data["update_id"]
                    else:
                        event.update_id = next_update_id
                        next_update_id += 1
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

    next_update_id = await _get_next_update_id(session)
    event.update_id = next_update_id

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
    next_update_id = await _get_next_update_id(session)
    event.update_id = next_update_id

    session.add(event)
    await session.commit()
