"""Book cover image serving router — /covers."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from biograph.config import get_config

router = APIRouter(prefix="/covers", tags=["covers"])

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_ALLOWED_EXTS: tuple[tuple[str, str], ...] = (
    (".jpg", "image/jpeg"),
    (".jpeg", "image/jpeg"),
    (".png", "image/png"),
)


@router.get("/{book_uuid}")
async def get_book_cover(book_uuid: str) -> FileResponse:
    """Serve a book cover icon by UUID from ``resources.book_covers``.

    Intentionally unauthenticated so browser ``<img>`` tags on the internal
    network can load covers directly without Bearer headers.
    """
    stem = book_uuid
    for ext, _ in _ALLOWED_EXTS:
        if stem.lower().endswith(ext):
            stem = stem[: -len(ext)]
            break

    if not _UUID_RE.match(stem):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid book UUID",
        )

    raw_dir = get_config().resources.book_covers
    if not raw_dir:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book covers directory not configured",
        )

    covers_dir = Path(raw_dir).expanduser().resolve()
    if not covers_dir.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book covers directory not found",
        )

    stem_lower = stem.lower()
    for ext, media_type in _ALLOWED_EXTS:
        for candidate_name in (f"{stem}{ext}", f"{stem_lower}{ext}"):
            candidate = (covers_dir / candidate_name).resolve()
            if not candidate.is_relative_to(covers_dir):
                continue
            if candidate.is_file():
                return FileResponse(
                    candidate,
                    media_type=media_type,
                    headers={"Cache-Control": "public, max-age=86400"},
                )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Book cover not found",
    )
