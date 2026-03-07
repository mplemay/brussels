from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from brussels.types.file.file import RemoteFile
from brussels.utils import utc

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import Session

    from brussels.mixins import PrimaryKeyMixin
    from brussels.types.file._types import RemoteMetadataField
    from brussels.types.file.metadata import RemoteMetadata


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
    if metadata.status not in {"pending", "failed"}:
        return False

    cutoff = utc(now) - stale_after
    return utc(metadata.updated_at) <= cutoff


def find_cleanup_candidates[T](
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
) -> None:
    for field in fields:
        remote_file = RemoteFile.from_metadata(model, field)
        if remote_file.metadata is None:
            continue
        await remote_file.delete_async(
            session=session,
            flush=flush,
            delete_remote=delete_remote,
        )
