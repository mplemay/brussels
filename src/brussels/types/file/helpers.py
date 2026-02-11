from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, TypeVar

from brussels.types.file.file import RemoteMetadata, UploadStatus
from brussels.types.file.remote_file import RemoteFile, RemoteMetadataField

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import Session

    from brussels.mixins import PrimaryKeyMixin

T = TypeVar("T")


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        msg = "Datetime values must be timezone-aware."
        raise ValueError(msg)
    return value.astimezone(UTC)


def is_cleanup_candidate(
    metadata: RemoteMetadata | None,
    *,
    now: datetime,
    stale_after: timedelta,
) -> bool:
    if metadata is None:
        return False
    if stale_after < timedelta(0):
        msg = "stale_after must be non-negative."
        raise ValueError(msg)
    if metadata.status not in {UploadStatus.PENDING, UploadStatus.FAILED}:
        return False

    cutoff = _ensure_utc(now) - stale_after
    return _ensure_utc(metadata.updated_at) <= cutoff


def find_cleanup_candidates(
    items: list[T],
    *,
    extractor: Callable[[T], RemoteMetadata | None],
    now: datetime,
    stale_after: timedelta,
) -> list[T]:
    return [item for item in items if is_cleanup_candidate(extractor(item), now=now, stale_after=stale_after)]


async def cleanup_remote_fields(
    *,
    model: PrimaryKeyMixin,
    fields: list[RemoteMetadataField] | tuple[RemoteMetadataField, ...],
    session: Session | AsyncSession | None = None,
    flush: bool = False,
    delete_remote: bool = True,
    **delete_kwargs: object,
) -> None:
    for field in fields:
        remote_file = RemoteFile.from_metadata(model, field)
        if remote_file.metadata is None:
            continue
        await remote_file.delete(
            session=session,
            flush=flush,
            delete_remote=delete_remote,
            **delete_kwargs,
        )
