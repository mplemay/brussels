from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest
from sqlalchemy.orm import Mapped, mapped_column

from brussels.base import Base

try:
    from brussels.types import RemoteFile, RemoteFileMetadata, UploadStatus
except ModuleNotFoundError:
    pytest.skip("files optional dependencies not installed", allow_module_level=True)


class FileModel(Base):
    __tablename__ = "file_model"

    id: Mapped[str | int | None] = mapped_column(primary_key=True)
    file: Mapped[RemoteFileMetadata | None] = mapped_column(RemoteFile(store=object()), nullable=True)


class SyncSessionSpy:
    def __init__(self) -> None:
        self.flush_calls = 0

    def flush(self) -> None:
        self.flush_calls += 1


class AsyncSessionSpy:
    def __init__(self) -> None:
        self.flush_calls = 0

    async def flush(self) -> None:
        self.flush_calls += 1


class FakeStoreOps:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, tuple[object, ...], dict[str, object]]] = []
        self.put_error: Exception | None = None
        self.put_response: object = {
            "size_bytes": 5,
            "content_type": "text/plain",
            "etag": "etag-123",
            "checksum": "sum-123",
            "version": "v1",
        }

    def _record(self, name: str, store: object, args: tuple[object, ...], kwargs: dict[str, object]) -> None:
        self.calls.append((name, store, args, kwargs))

    async def put(self, store: object, *args: object, **kwargs: object) -> object:
        self._record("put", store, args, kwargs)
        if self.put_error is not None:
            raise self.put_error
        return self.put_response

    async def get(self, store: object, *args: object, **kwargs: object) -> object:
        self._record("get", store, args, kwargs)
        return b"downloaded"

    async def get_range(self, store: object, *args: object, **kwargs: object) -> object:
        self._record("get_range", store, args, kwargs)
        return b"range"

    async def delete(self, store: object, *args: object, **kwargs: object) -> object:
        self._record("delete", store, args, kwargs)
        return None


def _clock(values: list[datetime]):
    def now() -> datetime:
        if values:
            return values.pop(0)
        return datetime(2025, 1, 1, 0, 0, tzinfo=UTC)

    return now


def _configure_remote_file(*, store_ops: FakeStoreOps, now_values: list[datetime]) -> None:
    remote_file = cast("RemoteFile", FileModel.__table__.c.file.type)
    remote_file.store_ops = store_ops
    remote_file.now = _clock(now_values)


@pytest.mark.asyncio
async def test_upload_success_updates_metadata_and_uses_model_method() -> None:
    store_ops = FakeStoreOps()
    _configure_remote_file(
        store_ops=store_ops,
        now_values=[
            datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
            datetime(2025, 1, 1, 12, 1, tzinfo=UTC),
        ],
    )
    model = FileModel(id="user-123")
    session = SyncSessionSpy()

    metadata = await model.upload(  # type: ignore[attr-defined]
        data=b"hello",
        content_type="text/plain",
        session=session,
        flush=True,
    )

    assert metadata.status is UploadStatus.COMPLETE
    assert metadata.key == "user-123/file"
    assert metadata.size_bytes == 5
    assert metadata.error_message is None
    assert model.file is not None
    assert model.file.status is UploadStatus.COMPLETE
    assert session.flush_calls == 2
    assert [name for name, *_rest in store_ops.calls] == ["put"]
    assert store_ops.calls[0][2][0] == "user-123/file"
    assert store_ops.calls[0][2][1] == b"hello"


@pytest.mark.asyncio
async def test_upload_failure_marks_metadata_failed_and_re_raises() -> None:
    store_ops = FakeStoreOps()
    store_ops.put_error = RuntimeError("upload failed")
    _configure_remote_file(
        store_ops=store_ops,
        now_values=[
            datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
            datetime(2025, 1, 1, 12, 1, tzinfo=UTC),
        ],
    )
    model = FileModel(id=42)
    session = AsyncSessionSpy()

    with pytest.raises(RuntimeError, match="upload failed"):
        await model.upload(  # type: ignore[attr-defined]
            data=b"boom",
            session=session,
            flush=True,
        )

    assert model.file is not None
    assert model.file.status is UploadStatus.FAILED
    assert model.file.error_message == "upload failed (RuntimeError)"
    assert session.flush_calls == 2


@pytest.mark.asyncio
async def test_reupload_bucket_behavior() -> None:
    store_ops = FakeStoreOps()
    _configure_remote_file(
        store_ops=store_ops,
        now_values=[datetime(2025, 1, 1, 12, 1, tzinfo=UTC), datetime(2025, 1, 1, 12, 2, tzinfo=UTC)],
    )
    model = FileModel(
        id="user-123",
        file=RemoteFileMetadata(
            bucket="existing-bucket",
            key="user-123/file",
            status=UploadStatus.PENDING,
            created_at=datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
            updated_at=datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
        ),
    )

    updated = await model.upload(data=b"hello")  # type: ignore[attr-defined]
    assert updated.bucket == "existing-bucket"

    updated = await model.upload(data=b"hello", bucket="new-bucket")  # type: ignore[attr-defined]
    assert updated.bucket == "new-bucket"


@pytest.mark.asyncio
async def test_download_read_range_and_delete() -> None:
    store_ops = FakeStoreOps()
    _configure_remote_file(
        store_ops=store_ops,
        now_values=[datetime(2025, 1, 1, 12, 1, tzinfo=UTC)],
    )
    metadata = RemoteFileMetadata(
        key="folder/item.txt",
        status=UploadStatus.COMPLETE,
        created_at=datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
        updated_at=datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
    )
    model = FileModel(id="abc", file=metadata)

    downloaded = await model.download()  # type: ignore[attr-defined]
    ranged = await model.read_range(0, 4)  # type: ignore[attr-defined]
    await model.delete()  # type: ignore[attr-defined]

    assert downloaded == b"downloaded"
    assert ranged == b"range"
    assert model.file is None
    assert [name for name, *_rest in store_ops.calls] == ["get", "get_range", "delete"]
    assert store_ops.calls[0][2][0] == "folder/item.txt"
    assert store_ops.calls[1][2][0] == "folder/item.txt"
    assert store_ops.calls[2][2][0] == "folder/item.txt"


@pytest.mark.asyncio
async def test_upload_requires_model_id() -> None:
    _configure_remote_file(
        store_ops=FakeStoreOps(),
        now_values=[datetime(2025, 1, 1, 12, 0, tzinfo=UTC)],
    )
    model = FileModel(id=None)

    with pytest.raises(ValueError, match=r"model\.id"):
        await model.upload(data=b"data")  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_download_read_range_and_delete_require_metadata() -> None:
    _configure_remote_file(
        store_ops=FakeStoreOps(),
        now_values=[datetime(2025, 1, 1, 12, 0, tzinfo=UTC)],
    )
    model = FileModel(id="abc", file=None)

    with pytest.raises(ValueError, match="has no file metadata"):
        await model.download()  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="has no file metadata"):
        await model.read_range(0, 1)  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match="has no file metadata"):
        await model.delete()  # type: ignore[attr-defined]
