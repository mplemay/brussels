from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from uuid import UUID

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Mapped, Session, mapped_column

from brussels.base import Base, DataclassBase
from brussels.mixins import PrimaryKeyMixin

try:
    from obstore.store import MemoryStore

    from brussels.types.file import RemoteFile, RemoteMetadata, RemoteStorage
except ImportError:
    pytest.skip("files optional dependencies not installed", allow_module_level=True)

if TYPE_CHECKING:
    from obstore import Attributes, GetOptions, PutMode

    from brussels.types.file.file import RemoteMetadataField


class NoPrimaryKeyMixinModel(Base):
    __tablename__ = "no_primary_key_mixin_models"

    id: Mapped[int] = mapped_column(primary_key=True)
    file: Mapped[RemoteMetadata | None] = mapped_column(RemoteStorage(store=MemoryStore()), nullable=True)


class FileModel(DataclassBase, PrimaryKeyMixin):
    __tablename__ = "file_model"

    file: Mapped[RemoteMetadata | None] = mapped_column(RemoteStorage(store=MemoryStore()), nullable=True, default=None)


class OtherFileModel(DataclassBase, PrimaryKeyMixin):
    __tablename__ = "other_file_model"

    file: Mapped[RemoteMetadata | None] = mapped_column(RemoteStorage(store=MemoryStore()), nullable=True, default=None)


class TablelessPrimaryKeyModel(PrimaryKeyMixin):
    pass


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

    async def put_async(
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
            "put_async",
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

    def get(self, path: str, *, options: object | None = None) -> object:
        self._record("get", (path,), {"options": options})
        return b"downloaded-sync"

    async def get_async(self, path: str, *, options: object | None = None) -> object:
        self._record("get_async", (path,), {"options": options})
        return b"downloaded-async"

    def get_range(self, path: str, *, start: int, end: int | None = None, length: int | None = None) -> object:
        self._record("get_range", (path,), {"start": start, "end": end, "length": length})
        return b"range-sync"

    async def get_range_async(
        self,
        path: str,
        *,
        start: int,
        end: int | None = None,
        length: int | None = None,
    ) -> object:
        self._record("get_range_async", (path,), {"start": start, "end": end, "length": length})
        return b"range-async"

    def delete(self, paths: str | tuple[str, ...] | list[str]) -> None:
        self._record("delete", (paths,), {})
        if self.delete_error is not None:
            raise self.delete_error

    async def delete_async(self, paths: str | tuple[str, ...] | list[str]) -> None:
        self._record("delete_async", (paths,), {})
        if self.delete_error is not None:
            raise self.delete_error


def _configure_store(store_ops: FakeStoreOps) -> None:
    remote_storage = cast("RemoteStorage", FileModel.__table__.c["file"].type)
    remote_storage.store = store_ops


def _file_handle(model: FileModel) -> RemoteFile:
    return RemoteFile.from_metadata(model, FileModel.file)


@pytest.fixture
def engine() -> Engine:
    engine = create_engine("sqlite:///:memory:")
    DataclassBase.metadata.create_all(engine)
    return engine


def test_from_metadata_rejects_models_without_primary_key_mixin() -> None:
    model = NoPrimaryKeyMixinModel(id=1)

    with pytest.raises(TypeError, match=r"PrimaryKeyMixin"):
        RemoteFile.from_metadata(cast("PrimaryKeyMixin", model), NoPrimaryKeyMixinModel.file)


def test_from_metadata_rejects_invalid_mapped_field_shape() -> None:
    class FakeField:
        key = 123

    model = FileModel()

    with pytest.raises(TypeError, match="mapped SQLAlchemy field"):
        RemoteFile.from_metadata(model, cast("RemoteMetadataField", FakeField()))


def test_from_metadata_rejects_model_without_table_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    model = FileModel()
    monkeypatch.setattr(FileModel, "__table__", None)

    with pytest.raises(TypeError, match="__table__ metadata"):
        RemoteFile.from_metadata(model, FileModel.file)


def test_from_metadata_rejects_non_remote_storage_field() -> None:
    model = FileModel()

    with pytest.raises(TypeError, match=r"must use brussels\.types\.file\.RemoteStorage"):
        RemoteFile.from_metadata(model, FileModel.id)  # type: ignore[arg-type]


def test_from_metadata_rejects_field_from_different_model() -> None:
    model = FileModel()

    with pytest.raises(TypeError, match=r"is not mapped on model type"):
        RemoteFile.from_metadata(model, OtherFileModel.file)


def test_from_metadata_accepts_models_with_primary_key_mixin() -> None:
    model = FileModel()

    remote_file = RemoteFile.from_metadata(model, FileModel.file)

    assert remote_file.field_name == "file"


def test_put_sync_without_sqlalchemy_session_raises_and_does_not_call_store() -> None:
    store_ops = FakeStoreOps()
    _configure_store(store_ops)
    model = FileModel()

    with pytest.raises(RuntimeError, match="requires a resolvable SQLAlchemy session"):
        _file_handle(model).put(
            b"hello",
            content_type="text/plain",
        )

    assert store_ops.calls == []
    assert model.file is None


def test_put_sync_defers_and_commits_when_sqlalchemy_session_is_attached(engine: Engine) -> None:
    store_ops = FakeStoreOps()
    _configure_store(store_ops)
    with Session(engine) as session:
        model = FileModel()
        expected_key = f"{model.id}/file"
        session.add(model)
        session.flush()

        put_result = _file_handle(model).put(
            b"hello",
            content_type="text/plain",
        )
        assert put_result == {"e_tag": None, "version": None}
        assert model.file is not None
        assert model.file.status == "pending"
        assert model.file.key == expected_key
        assert store_ops.calls == []

        session.commit()

    assert [name for name, *_ in store_ops.calls] == ["put"]


def test_put_preserves_existing_metadata_when_result_has_no_fields(engine: Engine) -> None:
    store_ops = FakeStoreOps()
    store_ops.put_response = {}
    _configure_store(store_ops)
    created_at = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    model = FileModel(
        file=RemoteMetadata(
            key="existing/key.txt",
            status="failed",
            content_type="text/csv",
            size_bytes=22,
            etag="etag-old",
            checksum="sum-old",
            version="v-old",
            created_at=created_at,
            updated_at=created_at,
        ),
    )

    with Session(engine) as session:
        session.add(model)
        session.flush()
        _file_handle(model).put(b"hello")
        session.commit()

    assert model.file is not None
    assert model.file.status == "complete"
    assert model.file.key == "existing/key.txt"
    assert model.file.content_type == "text/csv"
    assert model.file.size_bytes == 22
    assert model.file.etag == "etag-old"
    assert model.file.checksum == "sum-old"
    assert model.file.version == "v-old"


def test_put_validates_metadata_projection_types(engine: Engine) -> None:
    store_ops = FakeStoreOps()
    store_ops.put_response = {"size_bytes": True}
    _configure_store(store_ops)
    with Session(engine) as session:
        model = FileModel()
        session.add(model)
        session.flush()
        _file_handle(model).put(b"hello")

        with pytest.raises(TypeError, match="Expected integer metadata field"):
            session.commit()


@pytest.mark.asyncio
async def test_put_async_without_sqlalchemy_session_raises_and_does_not_call_store() -> None:
    store_ops = FakeStoreOps()
    _configure_store(store_ops)
    model = FileModel()

    with pytest.raises(RuntimeError, match="requires a resolvable SQLAlchemy session"):
        await _file_handle(model).put_async(
            b"hello",
            attributes=cast("Attributes", {"cache_control": "max-age=60"}),
            tags={"kind": "avatar"},
            mode=cast("PutMode", "overwrite"),
            use_multipart=True,
            chunk_size=32,
            max_concurrency=4,
            content_type="text/plain",
        )

    assert store_ops.calls == []
    assert model.file is None


@pytest.mark.asyncio
async def test_put_async_propagates_upload_options_with_attached_session(engine: Engine) -> None:
    store_ops = FakeStoreOps()
    _configure_store(store_ops)
    with Session(engine) as session:
        model = FileModel()
        session.add(model)
        session.flush()
        await _file_handle(model).put_async(
            b"hello",
            attributes=cast("Attributes", {"cache_control": "max-age=60"}),
            tags={"kind": "avatar"},
            mode=cast("PutMode", "overwrite"),
            use_multipart=True,
            chunk_size=32,
            max_concurrency=4,
            content_type="text/plain",
        )
        assert store_ops.calls == []
        session.commit()

    assert [name for name, *_ in store_ops.calls] == ["put"]
    assert store_ops.calls[0][2]["tags"] == {"kind": "avatar"}
    assert store_ops.calls[0][2]["use_multipart"] is True
    assert store_ops.calls[0][2]["chunk_size"] == 32
    assert store_ops.calls[0][2]["max_concurrency"] == 4


@pytest.mark.asyncio
async def test_put_rejects_invalid_model_id_type(engine: Engine) -> None:
    _configure_store(FakeStoreOps())
    with Session(engine) as session:
        model = FileModel()
        session.add(model)
        session.flush()
        model.id = cast("UUID", object())

        with pytest.raises(TypeError, match=r"Model id must be str, int, or UUID"):
            await _file_handle(model).put_async(b"data")


@pytest.mark.asyncio
async def test_put_allows_uuid_model_id(engine: Engine) -> None:
    store_ops = FakeStoreOps()
    _configure_store(store_ops)
    with Session(engine) as session:
        model = FileModel()
        session.add(model)
        session.flush()
        await _file_handle(model).put_async(b"data")
        session.commit()

        assert isinstance(model.id, UUID)
        assert model.file is not None
        assert model.file.status == "complete"


def test_get_get_range_and_delete_sync() -> None:
    store_ops = FakeStoreOps()
    _configure_store(store_ops)
    metadata = RemoteMetadata(
        key="folder/item.txt",
        status="complete",
        created_at=datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
        updated_at=datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
    )
    model = FileModel(file=metadata)

    file_handle = _file_handle(model)
    options = cast("GetOptions", {"head": True})
    downloaded = file_handle.get(options=options)
    ranged = file_handle.get_range(start=0, end=4)
    file_handle.delete(delete_remote=False)

    assert downloaded == b"downloaded-sync"
    assert ranged == b"range-sync"
    assert model.file is None
    assert [name for name, *_ in store_ops.calls] == ["get", "get_range"]


def test_delete_sync_delete_remote_false_does_not_call_store_delete() -> None:
    store_ops = FakeStoreOps()
    _configure_store(store_ops)
    created_at = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    model = FileModel(
        file=RemoteMetadata(
            key="folder/file.txt",
            status="complete",
            created_at=created_at,
            updated_at=created_at,
        ),
    )

    _file_handle(model).delete(delete_remote=False)

    assert model.file is None
    assert store_ops.calls == []


def test_delete_sync_without_sqlalchemy_session_raises_and_does_not_call_store() -> None:
    store_ops = FakeStoreOps()
    _configure_store(store_ops)
    created_at = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    model = FileModel(
        file=RemoteMetadata(
            key="folder/file.txt",
            status="complete",
            created_at=created_at,
            updated_at=created_at,
        ),
    )

    with pytest.raises(RuntimeError, match="requires a resolvable SQLAlchemy session"):
        _file_handle(model).delete()

    assert store_ops.calls == []
    assert model.file is not None


@pytest.mark.asyncio
async def test_delete_async_without_sqlalchemy_session_raises_and_does_not_call_store() -> None:
    store_ops = FakeStoreOps()
    _configure_store(store_ops)
    created_at = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    model = FileModel(
        file=RemoteMetadata(
            key="folder/file.txt",
            status="complete",
            created_at=created_at,
            updated_at=created_at,
        ),
    )

    with pytest.raises(RuntimeError, match="requires a resolvable SQLAlchemy session"):
        await _file_handle(model).delete_async()

    assert store_ops.calls == []
    assert model.file is not None


@pytest.mark.asyncio
async def test_get_get_range_and_delete_require_metadata() -> None:
    _configure_store(FakeStoreOps())
    model = FileModel(file=None)
    file_handle = _file_handle(model)

    with pytest.raises(ValueError, match="has no file metadata"):
        file_handle.get()
    with pytest.raises(ValueError, match="has no file metadata"):
        await file_handle.get_async()
    with pytest.raises(ValueError, match="has no file metadata"):
        file_handle.get_range(start=0, end=1)
    with pytest.raises(ValueError, match="has no file metadata"):
        await file_handle.get_range_async(start=0, end=1)
    with pytest.raises(ValueError, match="has no file metadata"):
        file_handle.delete()
    with pytest.raises(ValueError, match="has no file metadata"):
        await file_handle.delete_async()
