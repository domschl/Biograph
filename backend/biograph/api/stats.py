"""Stats API router — /stats."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from biograph.auth import require_token
from biograph.database import get_session
from biograph.models import Event

router = APIRouter(prefix="/stats", tags=["stats"])

Authenticated = Annotated[None, Depends(require_token)]
Session = Annotated[AsyncSession, Depends(get_session)]


class TypeCount(BaseModel):
    ev_type: str
    count: int


class Stats(BaseModel):
    total_events: int
    by_type: list[TypeCount]


@router.get("/", response_model=Stats)
async def get_stats(
    _: Authenticated,
    session: Session,
) -> Stats:
    """Return aggregate counts across all non-deleted events."""
    total: int = (
        await session.execute(
            select(func.count())
            .select_from(Event)
            .where(Event.deleted_at.is_(None))
        )
    ).scalar_one()

    rows = (
        await session.execute(
            select(Event.ev_type, func.count().label("count"))
            .where(Event.deleted_at.is_(None))
            .group_by(Event.ev_type)
            .order_by(func.count().desc())
        )
    ).all()

    return Stats(
        total_events=total,
        by_type=[TypeCount(ev_type=row[0], count=row[1]) for row in rows],
    )
