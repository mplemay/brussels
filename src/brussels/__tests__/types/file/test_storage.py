from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest
from sqlalchemy.dialects.postgresql import dialect as postgres_dialect
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect
from sqlalchemy.orm import Mapped, mapped_column

from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin

try:
    from obstore.store import MemoryStore  # ty: ignore[unresolved-import]

    from brussels.types.file import (
        RemoteFile,
        RemoteMetadata,
        RemoteStorage,
        cleanup_remote_fields,
    )
except ImportError:
    pytest.skip("files optional dependencies not installed", allow_module_level=True)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import Session


class FileModel(DataclassBase, PrimaryKeyMixin):
    __tablename__ = "file_model"

    file: Mapped[RemoteMetadata | None] = mapped_column(RemoteStorage(store=MemoryStore()), nullable=True, default=None)
    attachment: Mapped[RemoteMetadata | None] = mapped_column(
        RemoteStorage(store=MemoryStore()),
        nullable=True,
        default=None,
    )


class OtherFileModel(DataclassBase, PrimaryKeyMixin):
    __tablename__ = "other_file_model"

    file: Mapped[RemoteMetadata | None] = mapped_column(RemoteStorage(store=MemoryStore()), nullable=True, default=None)


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
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
        self.put_error: Exception | None = None
        self.delete_error: Exception | None = None
        self.put_response: object = {
            "size_bytes": 5,
            "content_type": "text/plain",
            "etag": "etag-123",
            "checksum": "sum-123",
            "version": "v1",
        }

    def _record(self, name: str, args: tuple[object, ...], kwargs: dict[str, object]) -> None:
        self.calls.append((name, args, kwargs))

    async def put(self, *args: object, **kwargs: object) -> object:
        self._record("put", args, kwargs)
        if self.put_error is not None:
            raise self.put_error
        return self.put_response

    async def get(self, *args: object, **kwargs: object) -> object:
        self._record("get", args, kwargs)
        return b"downloaded"

    async def get_range(self, *args: object, **kwargs: object) -> object:
        self._record("get_range", args, kwargs)
        return b"range"

    async def delete(self, *args: object, **kwargs: object) -> object:
        self._record("delete", args, kwargs)
        if self.delete_error is not None:
            raise self.delete_error
        return None


def _configure_remote_field(*, field_name: str, store_ops: FakeStoreOps) -> None:
    remote_file = cast("RemoteStorage", FileModel.__table__.c[field_name].type)
    remote_file.store = store_ops


def _file_handle(model: FileModel) -> RemoteFile:
    return RemoteFile.from_metadata(model, FileModel.file)


def _attachment_handle(model: FileModel) -> RemoteFile:
    return RemoteFile.from_metadata(model, FileModel.attachment)


def test_remote_file_compiles_to_jsonb_for_postgres() -> None:
    compiled = RemoteStorage(store=MemoryStore()).compile(dialect=postgres_dialect())
    assert "JSONB" in compiled


def test_remote_file_compiles_to_json_for_sqlite() -> None:
    compiled = RemoteStorage(store=MemoryStore()).compile(dialect=sqlite_dialect())
    assert "JSON" in compiled


def test_build_key_is_deterministic_model_id_and_field() -> None:
    remote_file = RemoteStorage(store=MemoryStore())

    assert remote_file.build_key(model_id="abc", field_name="file") == "abc/file"
    assert remote_file.build_key(model_id=42, field_name="file") == "42/file"


def test_remote_file_rejects_removed_key_prefix_and_key_factory_args() -> None:
    with pytest.raises(TypeError):
        RemoteStorage(store=MemoryStore(), key_prefix="uploads")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        RemoteStorage(store=MemoryStore(), key_factory=lambda _model_id, _filename: "x")  # type: ignore[call-arg]


def test_from_metadata_resolves_remote_storage_for_mapped_field() -> None:
    model = FileModel()

    handle = RemoteFile.from_metadata(model, FileModel.file)

    assert handle.field_name == "file"


def test_from_metadata_rejects_non_remote_storage_field() -> None:
    model = FileModel()

    with pytest.raises(TypeError, match=r"must use brussels\.types\.file\.RemoteStorage"):
        RemoteFile.from_metadata(model, FileModel.id)  # type: ignore[arg-type]


def test_from_metadata_rejects_field_from_different_model() -> None:
    model = FileModel()

    with pytest.raises(TypeError, match=r"is not mapped on model type"):
        RemoteFile.from_metadata(model, OtherFileModel.file)


def test_model_does_not_receive_dynamic_file_methods() -> None:
    assert "upload" not in FileModel.__dict__
    assert "download" not in FileModel.__dict__
    assert "read_range" not in FileModel.__dict__
    assert "delete" not in FileModel.__dict__


@pytest.mark.asyncio
async def test_upload_success_updates_metadata() -> None:
    store_ops = FakeStoreOps()
    _configure_remote_field(field_name="file", store_ops=store_ops)
    model = FileModel()
    expected_key = f"{model.id}/file"
    session = SyncSessionSpy()

    metadata = await _file_handle(model).upload(
        data=b"hello",
        content_type="text/plain",
        session=cast("Session", session),
        flush=True,
    )

    assert metadata.status == "complete"
    assert metadata.key == expected_key
    assert metadata.size_bytes == 5
    assert metadata.error_message is None
    assert model.file is not None
    assert model.file.status == "complete"
    assert session.flush_calls == 2
    assert [name for name, *_rest in store_ops.calls] == ["put"]
    assert store_ops.calls[0][1][0] == expected_key
    assert store_ops.calls[0][1][1] == b"hello"


@pytest.mark.asyncio
async def test_upload_failure_marks_metadata_failed_and_re_raises() -> None:
    store_ops = FakeStoreOps()
    store_ops.put_error = RuntimeError("upload failed")
    _configure_remote_field(field_name="file", store_ops=store_ops)
    model = FileModel()
    session = AsyncSessionSpy()

    with pytest.raises(RuntimeError, match="upload failed"):
        await _file_handle(model).upload(
            data=b"boom",
            session=cast("AsyncSession", session),
            flush=True,
        )

    assert model.file is not None
    assert model.file.status == "failed"
    assert model.file.error_message == "upload failed (RuntimeError)"
    assert session.flush_calls == 2


@pytest.mark.asyncio
async def test_reupload_bucket_behavior() -> None:
    store_ops = FakeStoreOps()
    _configure_remote_field(field_name="file", store_ops=store_ops)
    model = FileModel()
    model.file = RemoteMetadata(
        bucket="existing-bucket",
        key=f"{model.id}/file",
        status="pending",
        created_at=datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
        updated_at=datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
    )

    updated = await _file_handle(model).upload(data=b"hello")
    assert updated.bucket == "existing-bucket"

    updated = await _file_handle(model).upload(data=b"hello", bucket="new-bucket")
    assert updated.bucket == "new-bucket"


@pytest.mark.asyncio
async def test_download_read_range_and_delete() -> None:
    store_ops = FakeStoreOps()
    _configure_remote_field(field_name="file", store_ops=store_ops)
    metadata = RemoteMetadata(
        key="folder/item.txt",
        status="complete",
        created_at=datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
        updated_at=datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
    )
    model = FileModel(file=metadata)

    file_handle = _file_handle(model)
    downloaded = await file_handle.download()
    ranged = await file_handle.read_range(0, 4)
    await file_handle.delete()

    assert downloaded == b"downloaded"
    assert ranged == b"range"
    assert model.file is None
    assert [name for name, *_rest in store_ops.calls] == ["get", "get_range", "delete"]
    assert store_ops.calls[0][1][0] == "folder/item.txt"
    assert store_ops.calls[1][1][0] == "folder/item.txt"
    assert store_ops.calls[2][1][0] == "folder/item.txt"


@pytest.mark.asyncio
async def test_upload_requires_model_id() -> None:
    _configure_remote_field(field_name="file", store_ops=FakeStoreOps())
    model = FileModel()
    model.id = None  # type: ignore[assignment]

    with pytest.raises(ValueError, match=r"model\.id"):
        await _file_handle(model).upload(data=b"data")


@pytest.mark.asyncio
async def test_download_read_range_and_delete_require_metadata() -> None:
    _configure_remote_field(field_name="file", store_ops=FakeStoreOps())
    model = FileModel(file=None)
    file_handle = _file_handle(model)

    with pytest.raises(ValueError, match="has no file metadata"):
        await file_handle.download()
    with pytest.raises(ValueError, match="has no file metadata"):
        await file_handle.read_range(0, 1)
    with pytest.raises(ValueError, match="has no file metadata"):
        await file_handle.delete()


@pytest.mark.asyncio
async def test_cleanup_remote_fields_deletes_multiple_fields() -> None:
    file_store = FakeStoreOps()
    attachment_store = FakeStoreOps()
    _configure_remote_field(field_name="file", store_ops=file_store)
    _configure_remote_field(field_name="attachment", store_ops=attachment_store)
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

    await cleanup_remote_fields(model=model, fields=[FileModel.file, FileModel.attachment])

    assert model.file is None
    assert model.attachment is None
    assert [name for name, *_rest in file_store.calls] == ["delete"]
    assert [name for name, *_rest in attachment_store.calls] == ["delete"]
    assert file_store.calls[0][1][0] == "folder/file.txt"
    assert attachment_store.calls[0][1][0] == "folder/attachment.txt"


@pytest.mark.asyncio
async def test_cleanup_remote_fields_is_fail_fast() -> None:
    file_store = FakeStoreOps()
    attachment_store = FakeStoreOps()
    file_store.delete_error = RuntimeError("delete failed")
    _configure_remote_field(field_name="file", store_ops=file_store)
    _configure_remote_field(field_name="attachment", store_ops=attachment_store)
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

    with pytest.raises(RuntimeError, match="delete failed"):
        await cleanup_remote_fields(model=model, fields=[FileModel.file, FileModel.attachment])

    assert model.file is not None
    assert model.attachment is not None
    assert [name for name, *_rest in file_store.calls] == ["delete"]
    assert attachment_store.calls == []


@pytest.mark.asyncio
async def test_cleanup_remote_fields_skips_empty_metadata() -> None:
    file_store = FakeStoreOps()
    attachment_store = FakeStoreOps()
    _configure_remote_field(field_name="file", store_ops=file_store)
    _configure_remote_field(field_name="attachment", store_ops=attachment_store)
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

    await cleanup_remote_fields(model=model, fields=[FileModel.file, FileModel.attachment])

    assert model.file is None
    assert model.attachment is None
    assert file_store.calls == []
    assert [name for name, *_rest in attachment_store.calls] == ["delete"]


def test_remote_file_from_metadata_returns_handle() -> None:
    model = FileModel()

    handle = RemoteFile.from_metadata(model, FileModel.file)

    assert isinstance(handle, RemoteFile)
    assert handle.field_name == "file"


@pytest.mark.asyncio
async def test_remote_file_metadata_property_tracks_field_updates() -> None:
    store_ops = FakeStoreOps()
    _configure_remote_field(field_name="file", store_ops=store_ops)
    model = FileModel()
    file_handle = _file_handle(model)

    assert file_handle.metadata is None

    await file_handle.upload(data=b"hello")
    assert file_handle.metadata is not None
    assert file_handle.metadata.status == "complete"

    await file_handle.delete()
    assert file_handle.metadata is None


def test_attachment_field_handle_resolves() -> None:
    model = FileModel()

    handle = _attachment_handle(model)

    assert handle.field_name == "attachment"
