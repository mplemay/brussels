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


pytestmark = pytest.mark.integration


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


def test_orm_round_trip_returns_remote_file_metadata(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)

    with Session(engine) as session:
        record = FileRecord(
            file=RemoteMetadata(
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
