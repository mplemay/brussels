from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal, cast

import pytest
from sqlalchemy.orm import Mapped, mapped_column

from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin

try:
    from obstore.store import MemoryStore

    from brussels.types.file import (
        RemoteFile,
        RemoteMetadata,
        RemoteStorage,
        cleanup_remote_fields,
        find_cleanup_candidates,
        is_cleanup_candidate,
    )
except ImportError:
    pytest.skip("files optional dependencies not installed", allow_module_level=True)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class Row:
    file: RemoteMetadata | None


class FileModel(DataclassBase, PrimaryKeyMixin):
    __tablename__ = "file_utils_model"

    file: Mapped[RemoteMetadata | None] = mapped_column(RemoteStorage(store=MemoryStore()), nullable=True, default=None)
    attachment: Mapped[RemoteMetadata | None] = mapped_column(
        RemoteStorage(store=MemoryStore()),
        nullable=True,
        default=None,
    )


type StatusLiteral = Literal["pending", "complete", "failed"]


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


def test_is_cleanup_candidate_true_on_cutoff_equality_boundary() -> None:
    now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    metadata = _metadata(
        status="failed",
        updated_at=datetime(2025, 1, 1, 11, 30, tzinfo=UTC),
    )

    assert is_cleanup_candidate(metadata, now=now, stale_after=timedelta(minutes=30)) is True


def test_is_cleanup_candidate_rejects_negative_stale_after() -> None:
    metadata = _metadata(
        status="pending",
        updated_at=datetime(2025, 1, 1, 11, 0, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="stale_after must be non-negative"):
        is_cleanup_candidate(metadata, now=datetime(2025, 1, 1, 12, 0, tzinfo=UTC), stale_after=timedelta(minutes=-1))


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


@pytest.mark.asyncio
async def test_cleanup_remote_fields_forwards_tuple_session_flush_and_delete_remote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_at = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    model = FileModel(
        file=RemoteMetadata(
            key="folder/file.txt",
            status="complete",
            created_at=created_at,
            updated_at=created_at,
        ),
    )
    session = object()
    captured: list[dict[str, object]] = []

    async def fake_delete_async(self, *, session=None, flush=False, delete_remote=True) -> None:
        captured.append({"session": session, "flush": flush, "delete_remote": delete_remote})
        setattr(self.model, self.field_name, None)

    monkeypatch.setattr(RemoteFile, "delete_async", fake_delete_async)

    await cleanup_remote_fields(
        model=model,
        fields=(FileModel.file,),
        session=cast("Session", session),
        flush=True,
        delete_remote=False,
    )

    assert model.file is None
    assert captured == [{"session": session, "flush": True, "delete_remote": False}]


@pytest.mark.asyncio
async def test_cleanup_remote_fields_is_fail_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    created_at = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    model = FileModel(
        file=RemoteMetadata(
            key="folder/file.txt",
            status="complete",
            created_at=created_at,
            updated_at=created_at,
        ),
        attachment=RemoteMetadata(
            key="folder/attachment.txt",
            status="complete",
            created_at=created_at,
            updated_at=created_at,
        ),
    )
    calls: list[str] = []

    async def fake_delete_async(self, *, session=None, flush=False, delete_remote=True) -> None:
        _ = (session, flush, delete_remote)
        calls.append(self.field_name)
        if self.field_name == "file":
            msg = "delete failed"
            raise RuntimeError(msg)
        setattr(self.model, self.field_name, None)

    monkeypatch.setattr(RemoteFile, "delete_async", fake_delete_async)

    with pytest.raises(RuntimeError, match="delete failed"):
        await cleanup_remote_fields(model=model, fields=[FileModel.file, FileModel.attachment])

    assert calls == ["file"]
    assert model.file is not None
    assert model.attachment is not None


@pytest.mark.asyncio
async def test_cleanup_remote_fields_skips_empty_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    created_at = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    model = FileModel(
        file=None,
        attachment=RemoteMetadata(
            key="folder/attachment.txt",
            status="complete",
            created_at=created_at,
            updated_at=created_at,
        ),
    )
    calls: list[str] = []

    async def fake_delete_async(self, *, session=None, flush=False, delete_remote=True) -> None:
        _ = (session, flush, delete_remote)
        calls.append(self.field_name)
        setattr(self.model, self.field_name, None)

    monkeypatch.setattr(RemoteFile, "delete_async", fake_delete_async)

    await cleanup_remote_fields(model=model, fields=[FileModel.file, FileModel.attachment])

    assert model.file is None
    assert model.attachment is None
    assert calls == ["attachment"]
