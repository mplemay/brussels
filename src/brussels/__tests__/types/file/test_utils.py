from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

import pytest

try:
    from brussels.types.file import (
        RemoteMetadata,
        find_cleanup_candidates,
        is_cleanup_candidate,
    )
except ImportError:
    pytest.skip("files optional dependencies not installed", allow_module_level=True)


@dataclass
class Row:
    file: RemoteMetadata | None


type StatusLiteral = Literal["pending", "complete", "failed", "deleted"]


def _metadata(*, status: StatusLiteral, updated_at: datetime) -> RemoteMetadata:
    return RemoteMetadata(
        key="folder/item.txt",
        status=status,
        created_at=datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
        updated_at=updated_at,
    )


def test_is_cleanup_candidate_true_for_stale_pending() -> None:
    now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    metadata = _metadata(
        status="pending",
        updated_at=datetime(2025, 1, 1, 11, 0, tzinfo=UTC),
    )

    result = is_cleanup_candidate(metadata, now=now, stale_after=timedelta(minutes=30))

    assert result is True


def test_is_cleanup_candidate_false_for_complete_or_recent_pending() -> None:
    now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    complete = _metadata(
        status="complete",
        updated_at=datetime(2025, 1, 1, 10, 0, tzinfo=UTC),
    )
    recent_pending = _metadata(
        status="pending",
        updated_at=datetime(2025, 1, 1, 11, 50, tzinfo=UTC),
    )

    assert is_cleanup_candidate(complete, now=now, stale_after=timedelta(minutes=30)) is False
    assert is_cleanup_candidate(recent_pending, now=now, stale_after=timedelta(minutes=30)) is False


def test_is_cleanup_candidate_rejects_naive_now_datetime() -> None:
    metadata = _metadata(
        status="pending",
        updated_at=datetime(2025, 1, 1, 11, 0, tzinfo=UTC),
    )
    naive_now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC).replace(tzinfo=None)

    with pytest.raises(ValueError, match="timezone-aware"):
        is_cleanup_candidate(metadata, now=naive_now, stale_after=timedelta(minutes=30))


def test_find_cleanup_candidates_filters_stale_incomplete_rows() -> None:
    now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    rows = [
        Row(file=_metadata(status="pending", updated_at=datetime(2025, 1, 1, 10, 0, tzinfo=UTC))),
        Row(file=_metadata(status="failed", updated_at=datetime(2025, 1, 1, 10, 30, tzinfo=UTC))),
        Row(file=_metadata(status="complete", updated_at=datetime(2025, 1, 1, 9, 0, tzinfo=UTC))),
        Row(file=_metadata(status="pending", updated_at=datetime(2025, 1, 1, 11, 59, tzinfo=UTC))),
        Row(file=None),
    ]

    candidates = find_cleanup_candidates(
        rows,
        extractor=lambda row: row.file,
        now=now,
        stale_after=timedelta(minutes=45),
    )

    assert len(candidates) == 2
    assert candidates[0].file is not None
    assert candidates[1].file is not None
    assert candidates[0].file.status == "pending"
    assert candidates[1].file.status == "failed"
