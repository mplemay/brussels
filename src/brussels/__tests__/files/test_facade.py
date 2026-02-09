from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest

try:
    from brussels import files
    from brussels.files.facade import HAS_OBSTORE, RemoteFileFacade
    from brussels.types import RemoteFile, RemoteFileMetadata, UploadStatus
except ModuleNotFoundError:
    pytest.skip("files optional dependencies not installed", allow_module_level=True)

if TYPE_CHECKING:
    from uuid import UUID


@dataclass
class FileModel:
    id: str | int | UUID
    file: RemoteFileMetadata | None = None


@dataclass
class MissingIdModel:
    id: None = None
    file: RemoteFileMetadata | None = None


class SyncSessionSpy:
    def __init__(self) -> None:
        self.flush_calls = 0
        self.commit_calls = 0

    def flush(self) -> None:
        self.flush_calls += 1

    def commit(self) -> None:
        self.commit_calls += 1


class AsyncSessionSpy:
    def __init__(self) -> None:
        self.flush_calls = 0
        self.commit_calls = 0

    async def flush(self) -> None:
        self.flush_calls += 1

    async def commit(self) -> None:
        self.commit_calls += 1


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

    async def put_multipart(self, store: object, *args: object, **kwargs: object) -> object:
        self._record("put_multipart", store, args, kwargs)
        return "put_multipart"

    async def get(self, store: object, *args: object, **kwargs: object) -> object:
        self._record("get", store, args, kwargs)
        return b"downloaded"

    async def get_range(self, store: object, *args: object, **kwargs: object) -> object:
        self._record("get_range", store, args, kwargs)
        return b"range"

    async def head(self, store: object, *args: object, **kwargs: object) -> object:
        self._record("head", store, args, kwargs)
        return {"head": True}

    async def list(self, store: object, *args: object, **kwargs: object) -> object:
        self._record("list", store, args, kwargs)
        return ["a", "b"]

    async def list_with_delimiter(self, store: object, *args: object, **kwargs: object) -> object:
        self._record("list_with_delimiter", store, args, kwargs)
        return {"objects": [], "prefixes": []}

    async def delete(self, store: object, *args: object, **kwargs: object) -> object:
        self._record("delete", store, args, kwargs)
        return None

    async def copy(self, store: object, *args: object, **kwargs: object) -> object:
        self._record("copy", store, args, kwargs)
        return "copy"

    async def rename(self, store: object, *args: object, **kwargs: object) -> object:
        self._record("rename", store, args, kwargs)
        return "rename"

    async def sign(self, store: object, *args: object, **kwargs: object) -> object:
        self._record("sign", store, args, kwargs)
        return "signed-url"

    async def attributes(self, store: object, *args: object, **kwargs: object) -> object:
        self._record("attributes", store, args, kwargs)
        return {"region": "test"}


def _clock(values: list[datetime]):
    def now() -> datetime:
        if values:
            return values.pop(0)
        return datetime(2025, 1, 1, 0, 0, tzinfo=UTC)

    return now


@pytest.mark.asyncio
async def test_upload_success_updates_metadata_and_never_commits() -> None:
    store = object()
    store_ops = FakeStoreOps()
    model = FileModel(id="user-123")
    session = SyncSessionSpy()
    remote_file = RemoteFile(
        store=store,
        store_ops=store_ops,
        key_prefix="uploads",
        key_factory=lambda model_id, _filename: f"{model_id}/generated.txt",
        now=_clock(
            [
                datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
                datetime(2025, 1, 1, 12, 1, tzinfo=UTC),
            ],
        ),
    )
    facade = RemoteFileFacade(remote_file=remote_file)

    metadata = await facade.upload(
        model=model,
        field_name="file",
        data=b"hello",
        bucket="uploads-bucket",
        filename="hello.txt",
        content_type="text/plain",
        session=session,  # type: ignore[arg-type]
        flush=True,
    )

    assert metadata.status is UploadStatus.COMPLETE
    assert metadata.key == "uploads/user-123/generated.txt"
    assert metadata.size_bytes == 5
    assert metadata.content_type == "text/plain"
    assert metadata.etag == "etag-123"
    assert metadata.error_message is None
    assert model.file is not None
    assert model.file.status is UploadStatus.COMPLETE
    assert session.flush_calls == 2
    assert session.commit_calls == 0

    operation, called_store, args, kwargs = store_ops.calls[0]
    assert operation == "put"
    assert called_store is store
    assert args[0] == "uploads/user-123/generated.txt"
    assert args[1] == b"hello"
    assert kwargs["content_type"] == "text/plain"


@pytest.mark.asyncio
async def test_upload_failure_marks_metadata_failed_and_re_raises() -> None:
    store_ops = FakeStoreOps()
    store_ops.put_error = RuntimeError("upload failed")
    model = FileModel(id=42)
    session = AsyncSessionSpy()
    remote_file = RemoteFile(
        store=object(),
        store_ops=store_ops,
        key_factory=lambda model_id, _filename: f"{model_id}/generated.txt",
        now=_clock(
            [
                datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
                datetime(2025, 1, 1, 12, 1, tzinfo=UTC),
            ],
        ),
    )
    facade = RemoteFileFacade(remote_file=remote_file)

    with pytest.raises(RuntimeError, match="upload failed"):
        await facade.upload(
            model=model,
            field_name="file",
            data=b"boom",
            session=session,  # type: ignore[arg-type]
            flush=True,
        )

    assert model.file is not None
    assert model.file.status is UploadStatus.FAILED
    assert model.file.error_message == "upload failed"
    assert session.flush_calls == 2
    assert session.commit_calls == 0


@pytest.mark.asyncio
async def test_upload_requires_model_id() -> None:
    facade = RemoteFileFacade(remote_file=RemoteFile(store=object(), store_ops=FakeStoreOps()))
    model = MissingIdModel()

    with pytest.raises(ValueError, match=r"model\.id"):
        await facade.upload(model=cast("object", model), field_name="file", data=b"data")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_download_read_range_and_delete_file_use_metadata_key() -> None:
    now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    metadata = RemoteFileMetadata(
        key="folder/item.txt",
        status=UploadStatus.COMPLETE,
        created_at=now,
        updated_at=now,
    )
    model = FileModel(id="abc", file=metadata)
    store_ops = FakeStoreOps()
    remote_file = RemoteFile(
        store=object(),
        store_ops=store_ops,
        now=_clock([datetime(2025, 1, 1, 12, 1, tzinfo=UTC)]),
    )
    facade = RemoteFileFacade(remote_file=remote_file)

    downloaded = await facade.download(metadata)
    ranged = await facade.read_range(metadata, 0, 4)
    deleted = await facade.delete_file(model=model, field_name="file")

    assert downloaded == b"downloaded"
    assert ranged == b"range"
    assert deleted is not None
    assert deleted.status is UploadStatus.DELETED

    assert [name for name, *_rest in store_ops.calls] == ["get", "get_range", "delete"]
    assert store_ops.calls[0][2][0] == "folder/item.txt"
    assert store_ops.calls[1][2][0] == "folder/item.txt"
    assert store_ops.calls[2][2][0] == "folder/item.txt"


@pytest.mark.asyncio
async def test_all_wrapper_methods_call_obstore_operations() -> None:
    store_ops = FakeStoreOps()
    facade = RemoteFileFacade(remote_file=RemoteFile(store=object(), store_ops=store_ops))

    await facade.put("a", b"b")
    await facade.put_multipart("a", b"b")
    await facade.get("a")
    await facade.get_range("a", 0, 1)
    await facade.head("a")
    await facade.list(prefix="x")
    await facade.list_with_delimiter(prefix="x")
    await facade.delete("a")
    await facade.copy("a", "b")
    await facade.rename("a", "b")
    await facade.sign("a")
    await facade.attributes()

    assert [name for name, *_rest in store_ops.calls] == [
        "put",
        "put_multipart",
        "get",
        "get_range",
        "head",
        "list",
        "list_with_delimiter",
        "delete",
        "copy",
        "rename",
        "sign",
        "attributes",
    ]


def test_package_import_guard_raises_clear_error_when_obstore_missing() -> None:
    if HAS_OBSTORE:
        pytest.skip("obstore is installed in this environment")

    with pytest.raises(ModuleNotFoundError, match="brussels\\[files\\]"):
        _ = files.RemoteFileFacade
