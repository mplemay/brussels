from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.dialects.postgresql import dialect as postgres_dialect
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect
from sqlalchemy.orm import Mapped, Session, mapped_column

from brussels.base import Base
from brussels.types import RemoteFile, RemoteFileMetadata, UploadStatus

if TYPE_CHECKING:
    from collections.abc import Iterator


class FileRecord(Base):
    __tablename__ = "file_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    file: Mapped[RemoteFileMetadata | None] = mapped_column(RemoteFile(), nullable=True)


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine("sqlite:///:memory:")
    try:
        yield engine
    finally:
        engine.dispose()


def test_remote_file_compiles_to_jsonb_for_postgres() -> None:
    compiled = RemoteFile().compile(dialect=postgres_dialect())
    assert "JSONB" in compiled


def test_remote_file_compiles_to_json_for_sqlite() -> None:
    compiled = RemoteFile().compile(dialect=sqlite_dialect())
    assert "JSON" in compiled


def test_process_bind_param_serializes_metadata() -> None:
    now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    metadata = RemoteFileMetadata(
        store_name="store",
        key="example/file.txt",
        status=UploadStatus.PENDING,
        created_at=now,
        updated_at=now,
    )

    bound = RemoteFile().process_bind_param(metadata, None)

    assert bound is not None
    assert bound["store_name"] == "store"
    assert bound["key"] == "example/file.txt"
    assert bound["status"] == "pending"
    assert bound["created_at"] == now.isoformat()


def test_process_bind_param_rejects_invalid_value_type() -> None:
    with pytest.raises(TypeError, match="RemoteFile requires"):
        RemoteFile().process_bind_param("bad-value", None)  # type: ignore[arg-type]


def test_process_result_value_returns_typed_metadata() -> None:
    raw = {
        "schema_version": 1,
        "store_name": "store",
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

    metadata = RemoteFile().process_result_value(raw, None)

    assert isinstance(metadata, RemoteFileMetadata)
    assert metadata.status is UploadStatus.COMPLETE
    assert metadata.size_bytes == 8


def test_orm_round_trip_returns_remote_file_metadata(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)

    with Session(engine) as session:
        record = FileRecord(
            file=RemoteFileMetadata(
                store_name="store",
                bucket="bucket",
                key="example/file.txt",
                status=UploadStatus.PENDING,
                created_at=now,
                updated_at=now,
            ),
        )
        session.add(record)
        session.commit()
        session.refresh(record)

        assert isinstance(record.file, RemoteFileMetadata)
        assert record.file.status is UploadStatus.PENDING
        assert record.file.key == "example/file.txt"
