from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Mapped, Session, mapped_column

import brussels.types.file.lifecycle as file_lifecycle
from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin

try:
    from obstore.store import MemoryStore

    from brussels.types.file import RemoteFile, RemoteMetadata, RemoteStorage
    from brussels.types.file.lifecycle import FileLifecycleCoordinator, snapshot_put_payload, snapshot_put_payload_async
except ImportError:
    pytest.skip("files optional dependencies not installed", allow_module_level=True)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

    from brussels.types.file.lifecycle import PutInput


pytestmark = pytest.mark.integration


class FileModel(DataclassBase, PrimaryKeyMixin):
    __tablename__ = "file_lifecycle_model"

    file: Mapped[RemoteMetadata | None] = mapped_column(RemoteStorage(store=MemoryStore()), nullable=True, default=None)


class AsyncSessionShim:
    def __init__(self, sync_session: Session) -> None:
        self.sync_session = sync_session

    async def flush(self) -> None:
        self.sync_session.flush()


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

    def put(
        self,
        path: str,
        file: object,
        *,
        attributes: object | None = None,
        tags: dict[str, str] | None = None,
        mode: object | None = None,
        use_multipart: bool | None = None,
        chunk_size: int = 5 * 1024 * 1024,
        max_concurrency: int = 12,
    ) -> object:
        self._record(
            "put",
            (path, file),
            {
                "attributes": attributes,
                "tags": tags,
                "mode": mode,
                "use_multipart": use_multipart,
                "chunk_size": chunk_size,
                "max_concurrency": max_concurrency,
            },
        )
        if self.put_error is not None:
            raise self.put_error
        return self.put_response

    def delete(self, paths: str | tuple[str, ...] | list[str]) -> None:
        self._record("delete", (paths,), {})
        if self.delete_error is not None:
            raise self.delete_error


@pytest.fixture
def engine() -> Engine:
    engine = create_engine("sqlite:///:memory:")
    DataclassBase.metadata.create_all(engine)
    return engine


def _configure_remote_field(*, store_ops: FakeStoreOps) -> None:
    remote_file = cast("RemoteStorage", FileModel.__table__.c["file"].type)
    remote_file.store = store_ops


def _file_handle(model: FileModel) -> RemoteFile:
    return RemoteFile.from_metadata(model, FileModel.file)


def _rollback_nested_delete(*, session: Session, model: FileModel) -> None:
    message = "nested rollback"
    with session.begin_nested():
        _file_handle(model).delete(session=session, flush=True)
        raise RuntimeError(message)


def test_lifecycle_listener_registration_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    listeners: set[tuple[str, str]] = set()
    calls: list[tuple[str, str]] = []

    def fake_contains(_target: object, event_name: str, handler: object) -> bool:
        handler_name = getattr(handler, "__name__", "unknown")
        return (event_name, handler_name) in listeners

    def fake_listen(_target: object, event_name: str, handler: object) -> None:
        handler_name = getattr(handler, "__name__", "unknown")
        key = (event_name, handler_name)
        listeners.add(key)
        calls.append(key)

    monkeypatch.setattr(file_lifecycle.event, "contains", fake_contains)
    monkeypatch.setattr(file_lifecycle.event, "listen", fake_listen)
    monkeypatch.setattr(FileLifecycleCoordinator, "_registered", False)

    FileLifecycleCoordinator.ensure_listeners_registered()
    FileLifecycleCoordinator.ensure_listeners_registered()

    assert FileLifecycleCoordinator.LIFECYCLE_STATE_KEY == "brussels_file_lifecycle_state"
    assert calls == [
        ("after_transaction_create", "_after_transaction_create"),
        ("after_commit", "_after_commit"),
        ("after_rollback", "_after_rollback"),
        ("after_transaction_end", "_after_transaction_end"),
    ]


def test_put_with_sqlalchemy_session_defers_remote_upload_until_commit(engine: Engine) -> None:
    store_ops = FakeStoreOps()
    _configure_remote_field(store_ops=store_ops)

    with Session(engine) as session:
        model = FileModel()
        session.add(model)
        session.flush()
        expected_key = f"{model.id}/file"
        model_id = model.id

        result = _file_handle(model).put(b"hello", session=session, flush=True)

        assert result == {"deferred": True, "key": expected_key}
        assert model.file is not None
        assert model.file.status == "pending"
        assert store_ops.calls == []

        session.commit()

    assert [name for name, *_ in store_ops.calls] == ["put"]
    assert store_ops.calls[0][1][0] == expected_key
    assert store_ops.calls[0][1][1] == b"hello"

    with Session(engine) as read_session:
        metadata = read_session.scalar(select(FileModel.file).where(FileModel.id == model_id))
        assert metadata is not None
        assert metadata.status == "complete"
        assert metadata.key == expected_key


def test_put_with_sqlalchemy_session_rollback_discards_queued_upload(engine: Engine) -> None:
    store_ops = FakeStoreOps()
    _configure_remote_field(store_ops=store_ops)

    with Session(engine) as session:
        model = FileModel()
        session.add(model)
        session.flush()

        _file_handle(model).put(b"hello", session=session, flush=True)
        assert store_ops.calls == []
        session.rollback()

    assert store_ops.calls == []


def test_delete_with_sqlalchemy_session_defers_remote_delete_until_commit(engine: Engine) -> None:
    store_ops = FakeStoreOps()
    _configure_remote_field(store_ops=store_ops)
    created_at = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)

    with Session(engine) as session:
        model = FileModel(
            file=RemoteMetadata(
                key="folder/item.txt",
                status="complete",
                created_at=created_at,
                updated_at=created_at,
            ),
        )
        session.add(model)
        session.commit()
        model_id = model.id

    with Session(engine) as session:
        model = session.get(FileModel, model_id)
        assert model is not None

        _file_handle(model).delete(session=session, flush=True)

        assert model.file is None
        assert store_ops.calls == []
        session.commit()

    assert [name for name, *_ in store_ops.calls] == ["delete"]
    assert store_ops.calls[0][1][0] == "folder/item.txt"

    with Session(engine) as read_session:
        metadata = read_session.scalar(select(FileModel.file).where(FileModel.id == model_id))
        assert metadata is None


def test_delete_with_sqlalchemy_session_rollback_discards_queued_delete(engine: Engine) -> None:
    store_ops = FakeStoreOps()
    _configure_remote_field(store_ops=store_ops)
    created_at = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)

    with Session(engine) as session:
        model = FileModel(
            file=RemoteMetadata(
                key="folder/item.txt",
                status="complete",
                created_at=created_at,
                updated_at=created_at,
            ),
        )
        session.add(model)
        session.commit()
        model_id = model.id

    with Session(engine) as session:
        model = session.get(FileModel, model_id)
        assert model is not None
        _file_handle(model).delete(session=session, flush=True)
        assert model.file is None
        session.rollback()

    assert store_ops.calls == []

    with Session(engine) as read_session:
        metadata = read_session.scalar(select(FileModel.file).where(FileModel.id == model_id))
        assert metadata is not None
        assert metadata.key == "folder/item.txt"
        assert metadata.status == "complete"


def test_deferred_put_failure_marks_metadata_failed_and_cleans_up(engine: Engine) -> None:
    store_ops = FakeStoreOps()
    store_ops.put_error = RuntimeError("upload failed")
    _configure_remote_field(store_ops=store_ops)

    with Session(engine) as session:
        model = FileModel()
        session.add(model)
        session.flush()
        model_id = model.id

        _file_handle(model).put(b"hello", session=session, flush=True)
        session.commit()

    assert [name for name, *_ in store_ops.calls] == ["put", "delete"]
    with Session(engine) as read_session:
        metadata = read_session.scalar(select(FileModel.file).where(FileModel.id == model_id))
        assert metadata is not None
        assert metadata.status == "failed"


def test_deferred_delete_failure_restores_failed_metadata(engine: Engine) -> None:
    store_ops = FakeStoreOps()
    store_ops.delete_error = RuntimeError("delete failed")
    _configure_remote_field(store_ops=store_ops)
    created_at = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)

    with Session(engine) as session:
        model = FileModel(
            file=RemoteMetadata(
                key="folder/item.txt",
                status="complete",
                created_at=created_at,
                updated_at=created_at,
            ),
        )
        session.add(model)
        session.commit()
        model_id = model.id

    with Session(engine) as session:
        model = session.get(FileModel, model_id)
        assert model is not None
        _file_handle(model).delete(session=session, flush=True)
        session.commit()

    assert [name for name, *_ in store_ops.calls] == ["delete"]

    with Session(engine) as read_session:
        metadata = read_session.scalar(select(FileModel.file).where(FileModel.id == model_id))
        assert metadata is not None
        assert metadata.status == "failed"
        assert metadata.key == "folder/item.txt"


@pytest.mark.asyncio
async def test_put_async_with_async_session_shim_defers_until_commit(engine: Engine) -> None:
    store_ops = FakeStoreOps()
    _configure_remote_field(store_ops=store_ops)

    with Session(engine) as session:
        model = FileModel()
        session.add(model)
        session.flush()
        expected_key = f"{model.id}/file"
        async_session = AsyncSessionShim(session)

        result = await _file_handle(model).put_async(
            b"hello",
            session=cast("AsyncSession", async_session),
            flush=True,
        )

        assert result == {"deferred": True, "key": expected_key}
        assert store_ops.calls == []
        session.commit()

    assert [name for name, *_ in store_ops.calls] == ["put"]


@pytest.mark.asyncio
async def test_put_async_with_async_session_shim_rollback_discards_queue(engine: Engine) -> None:
    store_ops = FakeStoreOps()
    _configure_remote_field(store_ops=store_ops)

    with Session(engine) as session:
        model = FileModel()
        session.add(model)
        session.flush()
        async_session = AsyncSessionShim(session)

        await _file_handle(model).put_async(
            b"hello",
            session=cast("AsyncSession", async_session),
            flush=True,
        )

        assert store_ops.calls == []
        session.rollback()

    assert store_ops.calls == []


@pytest.mark.asyncio
async def test_delete_async_with_async_session_shim_defers_remote_delete_until_commit(engine: Engine) -> None:
    store_ops = FakeStoreOps()
    _configure_remote_field(store_ops=store_ops)
    created_at = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)

    with Session(engine) as session:
        model = FileModel(
            file=RemoteMetadata(
                key="folder/item.txt",
                status="complete",
                created_at=created_at,
                updated_at=created_at,
            ),
        )
        session.add(model)
        session.commit()
        model_id = model.id

    with Session(engine) as session:
        model = session.get(FileModel, model_id)
        assert model is not None
        async_session = AsyncSessionShim(session)

        await _file_handle(model).delete_async(
            session=cast("AsyncSession", async_session),
            flush=True,
        )

        assert model.file is None
        assert store_ops.calls == []
        session.commit()

    assert [name for name, *_ in store_ops.calls] == ["delete"]
    assert store_ops.calls[0][1][0] == "folder/item.txt"

    with Session(engine) as read_session:
        metadata = read_session.scalar(select(FileModel.file).where(FileModel.id == model_id))
        assert metadata is None


@pytest.mark.asyncio
async def test_delete_async_with_async_session_shim_rollback_discards_queue(engine: Engine) -> None:
    store_ops = FakeStoreOps()
    _configure_remote_field(store_ops=store_ops)
    created_at = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)

    with Session(engine) as session:
        model = FileModel(
            file=RemoteMetadata(
                key="folder/item.txt",
                status="complete",
                created_at=created_at,
                updated_at=created_at,
            ),
        )
        session.add(model)
        session.commit()
        model_id = model.id

    with Session(engine) as session:
        model = session.get(FileModel, model_id)
        assert model is not None
        async_session = AsyncSessionShim(session)

        await _file_handle(model).delete_async(
            session=cast("AsyncSession", async_session),
            flush=True,
        )

        assert model.file is None
        assert store_ops.calls == []
        session.rollback()

    assert store_ops.calls == []

    with Session(engine) as read_session:
        metadata = read_session.scalar(select(FileModel.file).where(FileModel.id == model_id))
        assert metadata is not None
        assert metadata.key == "folder/item.txt"
        assert metadata.status == "complete"


def test_nested_transaction_rollback_discards_only_nested_operations(engine: Engine) -> None:
    store_ops = FakeStoreOps()
    _configure_remote_field(store_ops=store_ops)
    created_at = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)

    with Session(engine) as session:
        model = FileModel(
            file=RemoteMetadata(
                key="folder/item.txt",
                status="complete",
                created_at=created_at,
                updated_at=created_at,
            ),
        )
        session.add(model)
        session.commit()
        model_id = model.id

    with Session(engine) as session:
        model = session.get(FileModel, model_id)
        assert model is not None

        _file_handle(model).put(b"hello", session=session, flush=True)
        assert store_ops.calls == []

        with pytest.raises(RuntimeError, match="nested rollback"):
            _rollback_nested_delete(session=session, model=model)

        session.commit()

    assert [name for name, *_ in store_ops.calls] == ["put"]


def test_nested_transaction_commit_merges_nested_queue_into_parent(engine: Engine) -> None:
    store_ops = FakeStoreOps()
    _configure_remote_field(store_ops=store_ops)

    with Session(engine) as session:
        model = FileModel()
        session.add(model)
        session.flush()

        _file_handle(model).put(b"hello", session=session, flush=True)
        with session.begin_nested():
            _file_handle(model).delete(session=session, flush=True)

        assert store_ops.calls == []
        session.commit()

    assert [name for name, *_ in store_ops.calls] == ["put", "delete"]


def test_pre_root_queue_executes_when_root_transaction_is_created(engine: Engine) -> None:
    store_ops = FakeStoreOps()
    _configure_remote_field(store_ops=store_ops)

    with Session(engine) as session:
        model = FileModel()
        expected_key = f"{model.id}/file"

        _file_handle(model).put(b"hello", session=session)
        assert store_ops.calls == []

        with session.begin():
            pass

    assert [name for name, *_ in store_ops.calls] == ["put"]
    assert store_ops.calls[0][1][0] == expected_key


def test_persist_failure_still_updates_in_memory_metadata(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    store_ops = FakeStoreOps()
    _configure_remote_field(store_ops=store_ops)
    persisted_payloads: list[RemoteMetadata | None] = []

    def fake_persist_field_update(*, session, operation, metadata) -> None:
        _ = (session, operation)
        persisted_payloads.append(metadata)

    monkeypatch.setattr(FileLifecycleCoordinator, "_persist_field_update", fake_persist_field_update)

    with Session(engine) as session:
        model = FileModel()
        session.add(model)
        session.flush()

        _file_handle(model).put(b"hello", session=session, flush=True)
        session.commit()

        assert model.file is not None
        assert model.file.status == "complete"

    assert persisted_payloads


def test_snapshot_put_payload_supports_bytes_buffers_path_and_iterable(tmp_path: Path) -> None:
    class Reader:
        def read(self) -> memoryview:
            return memoryview(b"abc")

    file_path = tmp_path / "upload.bin"
    file_path.write_bytes(b"hello")

    assert snapshot_put_payload(b"hello") == b"hello"
    assert snapshot_put_payload(bytearray(b"hello")) == b"hello"
    assert snapshot_put_payload(memoryview(b"hello")) == b"hello"
    assert snapshot_put_payload(file_path) == b"hello"
    assert snapshot_put_payload(cast("PutInput", Reader())) == b"abc"
    assert snapshot_put_payload([b"a", bytearray(b"b"), memoryview(b"c")]) == b"abc"


def test_snapshot_put_payload_rejects_invalid_read_result_and_input_type() -> None:
    class BadReader:
        def read(self) -> str:
            return "not-bytes"

    with pytest.raises(TypeError, match="Expected bytes when reading upload input"):
        snapshot_put_payload(cast("PutInput", BadReader()))
    with pytest.raises(TypeError, match="is not supported for deferred transactions"):
        snapshot_put_payload(cast("PutInput", object()))
    with pytest.raises(TypeError, match="cannot be converted to bytes"):
        snapshot_put_payload(cast("PutInput", [object()]))


@pytest.mark.asyncio
async def test_snapshot_put_payload_async_supports_async_iterable() -> None:
    async def chunks() -> AsyncIterator[object]:
        yield b"a"
        yield bytearray(b"b")
        yield memoryview(b"c")

    assert await snapshot_put_payload_async(chunks()) == b"abc"
