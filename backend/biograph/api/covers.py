"""Book cover image serving router — /covers."""

from __future__ import annotations

import logging
import os
import re
import stat
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from biograph.config import get_config

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/covers", tags=["covers"])

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_ALLOWED_EXTS: tuple[tuple[str, str], ...] = (
    (".jpg", "image/jpeg"),
    (".jpeg", "image/jpeg"),
    (".png", "image/png"),
)


def validate_book_covers_dir(raw_dir: str) -> tuple[Path | None, str | None]:
    """Validate and resolve ``resources.book_covers``.

    Returns ``(resolved_path, error_message)``. When ``raw_dir`` is empty,
    returns ``(None, None)``. When configured but unreachable (missing, not a
    directory, or permission denied), returns ``(None, actionable_message)``.
    """
    if not raw_dir or not raw_dir.strip():
        return None, None

    expanded = Path(raw_dir).expanduser()
    try:
        resolved = expanded.resolve()
        st = os.stat(resolved)
    except PermissionError as exc:
        return None, (
            f"Permission denied accessing book_covers directory '{raw_dir}': {exc}. "
            "If running as the 'biograph' service user, ensure traverse/read permissions "
            "(e.g. 'sudo setfacl -m u:biograph:x /home/<user>')."
        )
    except FileNotFoundError:
        return None, f"Configured book_covers directory does not exist: '{resolved}'"
    except OSError as exc:
        return None, f"Cannot access book_covers directory '{raw_dir}': {exc}"

    if not stat.S_ISDIR(st.st_mode):
        return None, f"Configured book_covers path is not a directory: '{resolved}'"

    if not os.access(resolved, os.R_OK | os.X_OK):
        return None, (
            f"Insufficient permissions (need read+execute) for book_covers directory '{resolved}'. "
            "If running as the 'biograph' service user, grant access "
            "(e.g. 'sudo setfacl -m u:biograph:x /home/<user>')."
        )

    return resolved, None


def check_book_covers_on_startup() -> None:
    """Log startup diagnostics when ``resources.book_covers`` is configured."""
    raw_dir = get_config().resources.book_covers
    if not raw_dir or not raw_dir.strip():
        return

    covers_dir, err = validate_book_covers_dir(raw_dir)
    if err:
        logger.error("Book covers disabled: %s", err)
    elif covers_dir is not None:
        logger.info("Serving book covers from %s", covers_dir)


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
    if not raw_dir or not raw_dir.strip():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Book covers directory not configured",
        )

    covers_dir, err = validate_book_covers_dir(raw_dir)
    if err or covers_dir is None:
        logger.error("Book covers unavailable: %s", err)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=err or "Book covers directory not found",
        )

    stem_lower = stem.lower()
    for ext, media_type in _ALLOWED_EXTS:
        for candidate_name in (f"{stem}{ext}", f"{stem_lower}{ext}"):
            candidate = (covers_dir / candidate_name).resolve()
            if not candidate.is_relative_to(covers_dir):
                continue
            try:
                if candidate.is_file():
                    return FileResponse(
                        candidate,
                        media_type=media_type,
                        headers={"Cache-Control": "public, max-age=86400"},
                    )
            except PermissionError as exc:
                msg = f"Permission denied reading book cover '{candidate}': {exc}"
                logger.error("%s", msg)
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=msg,
                )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Book cover not found",
    )
