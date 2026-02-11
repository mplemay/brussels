from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Mapped, Session, mapped_column

from brussels.base import Base

try:
    from obstore.store import MemoryStore

    from brussels.types.file import RemoteMetadata, RemoteStorage
except ImportError:
    pytest.skip("files optional dependencies not installed", allow_module_level=True)

if TYPE_CHECKING:
    from collections.abc import Iterator


class FileRecord(Base):
    __tablename__ = "file_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    file: Mapped[RemoteMetadata | None] = mapped_column(RemoteStorage(store=MemoryStore()), nullable=True)


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine("sqlite:///:memory:")
    try:
        yield engine
    finally:
        engine.dispose()


def test_process_bind_param_serializes_metadata() -> None:
    now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    metadata = RemoteMetadata(
        key="example/file.txt",
        status="pending",
        created_at=now,
        updated_at=now,
    )

    bound = RemoteStorage(store=MemoryStore()).process_bind_param(metadata, None)

    assert bound is not None
    assert bound["schema"] == 1
    assert bound["key"] == "example/file.txt"
    assert bound["status"] == "pending"
    assert bound["created_at"] in {now.isoformat(), "2025-01-01T12:00:00Z"}


def test_process_bind_param_rejects_invalid_value_type() -> None:
    with pytest.raises(ValueError, match="RemoteStorage RemoteMetadata is invalid"):
        RemoteStorage(store=MemoryStore()).process_bind_param("bad-value", None)  # type: ignore[arg-type]


def test_process_result_value_returns_typed_metadata() -> None:
    raw = {
        "schema": 1,
        "bucket": "bucket",
        "key": "example/file.txt",
        "url": None,
        "status": "complete",
        "size_bytes": 8,
        "content_type": "text/plain",
        "etag": "etag-value",
        "checksum": "checksum-value",
        "version": "v1",
        "created_at": "2025-01-01T12:00:00+00:00",
        "updated_at": "2025-01-01T12:01:00+00:00",
        "uploaded_at": "2025-01-01T12:01:00+00:00",
        "error_message": None,
    }

    metadata = RemoteStorage(store=MemoryStore()).process_result_value(raw, None)

    assert isinstance(metadata, RemoteMetadata)
    assert metadata.status == "complete"
    assert metadata.size_bytes == 8


def test_process_result_value_rejects_legacy_store_name_field() -> None:
    raw = {
        "store_name": "legacy-store",
        "key": "example/file.txt",
        "status": "complete",
        "created_at": "2025-01-01T12:00:00+00:00",
        "updated_at": "2025-01-01T12:01:00+00:00",
    }

    with pytest.raises(ValueError, match="RemoteStorage RemoteMetadata from database is invalid"):
        RemoteStorage(store=MemoryStore()).process_result_value(raw, None)


def test_orm_round_trip_returns_remote_file_metadata(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)

    with Session(engine) as session:
        record = FileRecord(
            file=RemoteMetadata(
                bucket="bucket",
                key="example/file.txt",
                status="pending",
                created_at=now,
                updated_at=now,
            ),
        )
        session.add(record)
        session.commit()
        session.refresh(record)

        assert isinstance(record.file, RemoteMetadata)
        assert record.file.status == "pending"
        assert record.file.key == "example/file.txt"
