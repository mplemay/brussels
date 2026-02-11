from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from importlib import import_module
from inspect import isawaitable
from typing import TYPE_CHECKING, Protocol, Self, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator  # ty: ignore[unresolved-import]
from sqlalchemy import JSON, event
from sqlalchemy.orm import Mapper
from sqlalchemy.types import TypeDecorator

from brussels.types.json_type import Json

if TYPE_CHECKING:
    from sqlalchemy.engine.interfaces import Dialect
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import Session
    from sqlalchemy.sql.type_api import TypeEngine

type RemoteFileDict = dict[str, object]
type RemoteFileNowFactory = Callable[[], datetime]


class SupportsFileId(Protocol):
    id: str | int | UUID


class _StoreOps(Protocol):
    async def put(self, store: object, *args: object, **kwargs: object) -> object: ...
    async def get(self, store: object, *args: object, **kwargs: object) -> object: ...
    async def get_range(self, store: object, *args: object, **kwargs: object) -> object: ...
    async def delete(self, store: object, *args: object, **kwargs: object) -> object: ...


class UploadStatus(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"
    DELETED = "deleted"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _load_obstore_store() -> _StoreOps | None:
    try:
        module = import_module("obstore")
    except ModuleNotFoundError:
        return None
    store = getattr(module, "store", None)
    if store is None:
        return None
    return cast("_StoreOps", store)


_obstore_store = _load_obstore_store()


def _extract_value(result: object, *field_names: str) -> object | None:
    if isinstance(result, dict):
        result_dict = cast("dict[str, object]", result)
        for field_name in field_names:
            if field_name in result_dict:
                return result_dict[field_name]
        return None

    for field_name in field_names:
        if hasattr(result, field_name):
            return getattr(result, field_name)

    return None


def _extract_optional_str(result: object, *field_names: str) -> str | None:
    value = _extract_value(result, *field_names)
    if value is None:
        return None
    if not isinstance(value, str):
        type_name = type(value).__name__
        msg = f"Expected string metadata field from obstore result, got {type_name}."
        raise TypeError(msg)
    return value


def _extract_optional_int(result: object, *field_names: str) -> int | None:
    value = _extract_value(result, *field_names)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        type_name = type(value).__name__
        msg = f"Expected integer metadata field from obstore result, got {type_name}."
        raise TypeError(msg)
    return value


class RemoteFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    bucket: str | None = None
    key: str
    url: str | None = None
    status: UploadStatus = UploadStatus.PENDING
    size_bytes: int | None = None
    content_type: str | None = None
    etag: str | None = None
    checksum: str | None = None
    version: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    uploaded_at: datetime | None = None
    error_message: str | None = None

    @field_validator("created_at", "updated_at", "uploaded_at", mode="after")
    @classmethod
    def _normalize_to_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def to_dict(self) -> RemoteFileDict:
        return cast("RemoteFileDict", self.model_dump(mode="json"))

    @classmethod
    def from_dict(cls, data: RemoteFileDict) -> Self:
        return cls.model_validate(data)


class RemoteStorage(TypeDecorator[RemoteFile]):
    impl = JSON
    cache_ok = False

    def __init__(
        self,
        *,
        store: object,
        now: RemoteFileNowFactory | None = None,
        store_ops: object | None = None,
    ) -> None:
        super().__init__()
        self.store = store
        self.now = now or _utc_now
        self.store_ops = store_ops

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[object]:
        return dialect.type_descriptor(Json)

    def build_key(self, *, model_id: str | int | UUID, field_name: str) -> str:
        return f"{str(model_id).lstrip('/')}/{field_name.lstrip('/')}"

    def process_bind_param(
        self,
        value: RemoteFile | RemoteFileDict | None,
        _dialect: object,
    ) -> RemoteFileDict | None:  # type: ignore[override]
        if value is None:
            return None
        try:
            metadata = value if isinstance(value, RemoteFile) else RemoteFile.from_dict(value)
        except ValidationError as exc:
            msg = "RemoteStorage RemoteFile metadata is invalid."
            raise ValueError(msg) from exc
        return metadata.to_dict()

    def process_result_value(
        self,
        value: object,
        _dialect: object,
    ) -> RemoteFile | None:  # type: ignore[override]
        if value is None:
            return None
        if not isinstance(value, dict):
            type_name = type(value).__name__
            msg = f"RemoteStorage expected dict from database, got {type_name}."
            raise TypeError(msg)
        try:
            return RemoteFile.from_dict(cast("RemoteFileDict", value))
        except ValidationError as exc:
            msg = "RemoteStorage RemoteFile metadata from database is invalid."
            raise ValueError(msg) from exc

    def _resolve_store_ops(self) -> _StoreOps:
        if self.store_ops is not None:
            return cast("_StoreOps", self.store_ops)
        if _obstore_store is not None:
            return _obstore_store
        msg = (
            "RemoteStorage operations require the optional dependency 'obstore'. "
            "Install with `pip install brussels[files]`."
        )
        raise ModuleNotFoundError(msg)

    @staticmethod
    def _model_id(model: SupportsFileId) -> str:
        model_id = getattr(model, "id", None)
        if model_id is None:
            msg = "RemoteStorage operations require model.id to be set."
            raise ValueError(msg)
        if not isinstance(model_id, str | int | UUID):
            type_name = type(model_id).__name__
            msg = f"Model id must be str, int, or UUID, got {type_name}."
            raise TypeError(msg)
        return str(model_id)

    @staticmethod
    async def _flush(*, session: Session | AsyncSession | None, flush: bool) -> None:
        if not flush or session is None:
            return
        maybe_awaitable = session.flush()
        if isawaitable(maybe_awaitable):
            await maybe_awaitable

    @staticmethod
    def _get_metadata(*, model: object, field_name: str) -> RemoteFile | None:
        value = getattr(model, field_name)
        if value is None:
            return None
        if isinstance(value, RemoteFile):
            return value
        if isinstance(value, dict):
            metadata = RemoteFile.from_dict(value)
            setattr(model, field_name, metadata)
            return metadata
        type_name = type(value).__name__
        msg = f"Model field '{field_name}' must hold RemoteFile | dict | None, got {type_name}."
        raise TypeError(msg)

    async def _put(self, *args: object, **kwargs: object) -> object:
        return await self._resolve_store_ops().put(self.store, *args, **kwargs)

    async def _get(self, *args: object, **kwargs: object) -> object:
        return await self._resolve_store_ops().get(self.store, *args, **kwargs)

    async def _get_range(self, *args: object, **kwargs: object) -> object:
        return await self._resolve_store_ops().get_range(self.store, *args, **kwargs)

    async def _delete(self, *args: object, **kwargs: object) -> object:
        return await self._resolve_store_ops().delete(self.store, *args, **kwargs)

    async def upload(  # noqa: PLR0913
        self,
        *,
        model: SupportsFileId,
        field_name: str,
        data: object,
        bucket: str | None = None,
        key: str | None = None,
        url: str | None = None,
        filename: str | None = None,
        content_type: str | None = None,
        session: Session | AsyncSession | None = None,
        flush: bool = False,
        **put_kwargs: object,
    ) -> RemoteFile:
        del filename
        metadata = self._get_metadata(model=model, field_name=field_name)
        if metadata is None:
            now = self.now()
            metadata = RemoteFile(
                bucket=bucket,
                key=key or self.build_key(model_id=self._model_id(model), field_name=field_name),
                url=url,
                status=UploadStatus.PENDING,
                content_type=content_type,
                created_at=now,
                updated_at=now,
            )
            setattr(model, field_name, metadata)
            await self._flush(session=session, flush=flush)
        else:
            update_now = self.now()
            metadata = metadata.model_copy(
                update={
                    "bucket": bucket if bucket is not None else metadata.bucket,
                    "key": key or metadata.key,
                    "url": url or metadata.url,
                    "status": UploadStatus.PENDING,
                    "content_type": content_type or metadata.content_type,
                    "updated_at": update_now,
                    "uploaded_at": None,
                    "error_message": None,
                },
            )
            setattr(model, field_name, metadata)
            await self._flush(session=session, flush=flush)

        if content_type is not None and "content_type" not in put_kwargs and "contentType" not in put_kwargs:
            put_kwargs["content_type"] = content_type

        try:
            result = await self._put(metadata.key, data, **put_kwargs)
        except Exception as exc:
            failed_metadata = metadata.model_copy(
                update={
                    "status": UploadStatus.FAILED,
                    "updated_at": self.now(),
                    "error_message": f"upload failed ({type(exc).__name__})",
                },
            )
            setattr(model, field_name, failed_metadata)
            await self._flush(session=session, flush=flush)
            raise

        finished_at = self.now()
        size_bytes = _extract_optional_int(result, "size_bytes", "size", "bytes")
        if size_bytes is None:
            size_bytes = metadata.size_bytes
        result_content_type = _extract_optional_str(result, "content_type", "contentType", "mime_type")
        if result_content_type is None:
            result_content_type = content_type or metadata.content_type
        etag = _extract_optional_str(result, "etag", "e_tag")
        if etag is None:
            etag = metadata.etag
        checksum = _extract_optional_str(result, "checksum", "sha256")
        if checksum is None:
            checksum = metadata.checksum
        version = _extract_optional_str(result, "version", "version_id")
        if version is None:
            version = metadata.version

        completed_metadata = metadata.model_copy(
            update={
                "status": UploadStatus.COMPLETE,
                "size_bytes": size_bytes,
                "content_type": result_content_type,
                "etag": etag,
                "checksum": checksum,
                "version": version,
                "updated_at": finished_at,
                "uploaded_at": finished_at,
                "error_message": None,
            },
        )
        setattr(model, field_name, completed_metadata)
        await self._flush(session=session, flush=flush)
        return completed_metadata

    async def download(self, *, model: object, field_name: str, **kwargs: object) -> object:
        metadata = self._get_metadata(model=model, field_name=field_name)
        if metadata is None:
            msg = f"Model field '{field_name}' has no file metadata."
            raise ValueError(msg)
        return await self._get(metadata.key, **kwargs)

    async def read_range(
        self,
        *,
        model: object,
        field_name: str,
        start: int,
        end: int,
        **kwargs: object,
    ) -> object:
        metadata = self._get_metadata(model=model, field_name=field_name)
        if metadata is None:
            msg = f"Model field '{field_name}' has no file metadata."
            raise ValueError(msg)
        return await self._get_range(metadata.key, start, end, **kwargs)

    async def delete_file(
        self,
        *,
        model: object,
        field_name: str,
        session: Session | AsyncSession | None = None,
        flush: bool = False,
        delete_remote: bool = True,
        **delete_kwargs: object,
    ) -> None:
        metadata = self._get_metadata(model=model, field_name=field_name)
        if metadata is None:
            msg = f"Model field '{field_name}' has no file metadata."
            raise ValueError(msg)
        if delete_remote:
            await self._delete(metadata.key, **delete_kwargs)
        setattr(model, field_name, None)
        await self._flush(session=session, flush=flush)


def _resolve_remote_storage(model: object, *, field_name: str) -> RemoteStorage:
    table = getattr(type(model), "__table__", None)
    if table is None:
        msg = "RemoteStorage operations require SQLAlchemy model instances with __table__ metadata."
        raise TypeError(msg)
    if field_name not in table.c:
        msg = f"Model does not define column '{field_name}'."
        raise ValueError(msg)
    column_type = table.c[field_name].type
    if not isinstance(column_type, RemoteStorage):
        msg = f"Model column '{field_name}' must use brussels.types.RemoteStorage."
        raise TypeError(msg)
    return column_type


async def _model_upload(  # noqa: PLR0913
    self: object,
    *,
    data: object,
    bucket: str | None = None,
    key: str | None = None,
    url: str | None = None,
    filename: str | None = None,
    content_type: str | None = None,
    session: Session | AsyncSession | None = None,
    flush: bool = False,
    **put_kwargs: object,
) -> RemoteFile:
    remote_storage = _resolve_remote_storage(self, field_name="file")
    return await remote_storage.upload(
        model=cast("SupportsFileId", self),
        field_name="file",
        data=data,
        bucket=bucket,
        key=key,
        url=url,
        filename=filename,
        content_type=content_type,
        session=session,
        flush=flush,
        **put_kwargs,
    )


async def _model_download(self: object, **kwargs: object) -> object:
    remote_storage = _resolve_remote_storage(self, field_name="file")
    return await remote_storage.download(model=self, field_name="file", **kwargs)


async def _model_read_range(self: object, start: int, end: int, **kwargs: object) -> object:
    remote_storage = _resolve_remote_storage(self, field_name="file")
    return await remote_storage.read_range(model=self, field_name="file", start=start, end=end, **kwargs)


async def _model_delete(
    self: object,
    *,
    session: Session | AsyncSession | None = None,
    flush: bool = False,
    delete_remote: bool = True,
    **delete_kwargs: object,
) -> None:
    remote_storage = _resolve_remote_storage(self, field_name="file")
    await remote_storage.delete_file(
        model=self,
        field_name="file",
        session=session,
        flush=flush,
        delete_remote=delete_remote,
        **delete_kwargs,
    )


def _attach_file_methods(_mapper: Mapper[object], cls: type[object]) -> None:
    table = getattr(cls, "__table__", None)
    if table is None or "file" not in table.c:
        return
    column_type = table.c["file"].type
    if not isinstance(column_type, RemoteStorage):
        return

    if "upload" not in cls.__dict__:
        cls.upload = _model_upload  # type: ignore[attr-defined]

    if "download" not in cls.__dict__:
        cls.download = _model_download  # type: ignore[attr-defined]

    if "read_range" not in cls.__dict__:
        cls.read_range = _model_read_range  # type: ignore[attr-defined]

    if "delete" not in cls.__dict__:
        cls.delete = _model_delete  # type: ignore[attr-defined]


event.listen(Mapper, "mapper_configured", _attach_file_methods)
