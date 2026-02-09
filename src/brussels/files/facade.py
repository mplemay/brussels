from __future__ import annotations

from importlib import import_module
from inspect import isawaitable
from typing import TYPE_CHECKING, Protocol, cast
from uuid import UUID

from brussels.types import RemoteFile, RemoteFileMetadata, UploadStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import Session


class SupportsFileId(Protocol):
    id: str | int | UUID


class _StoreOps(Protocol):
    async def put(self, store: object, *args: object, **kwargs: object) -> object: ...
    async def put_multipart(self, store: object, *args: object, **kwargs: object) -> object: ...
    async def get(self, store: object, *args: object, **kwargs: object) -> object: ...
    async def get_range(self, store: object, *args: object, **kwargs: object) -> object: ...
    async def head(self, store: object, *args: object, **kwargs: object) -> object: ...
    async def list(self, store: object, *args: object, **kwargs: object) -> object: ...
    async def list_with_delimiter(self, store: object, *args: object, **kwargs: object) -> object: ...
    async def delete(self, store: object, *args: object, **kwargs: object) -> object: ...
    async def copy(self, store: object, *args: object, **kwargs: object) -> object: ...
    async def rename(self, store: object, *args: object, **kwargs: object) -> object: ...
    async def sign(self, store: object, *args: object, **kwargs: object) -> object: ...
    async def attributes(self, store: object, *args: object, **kwargs: object) -> object: ...


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

HAS_OBSTORE = _obstore_store is not None


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


class RemoteFileFacade:
    def __init__(self, *, remote_file: RemoteFile | None = None) -> None:
        self._remote_file = remote_file

    def _resolve_remote_file(self, *, model: object | None = None, field_name: str | None = None) -> RemoteFile:
        if self._remote_file is not None:
            return self._remote_file

        if model is None or field_name is None:
            msg = "RemoteFileFacade requires a bound RemoteFile in the constructor for direct store operations."
            raise ValueError(msg)

        table = getattr(type(model), "__table__", None)
        if table is None:
            msg = "RemoteFileFacade requires SQLAlchemy model instances with __table__ metadata."
            raise TypeError(msg)

        if field_name not in table.c:
            msg = f"Model does not define column '{field_name}'."
            raise ValueError(msg)

        column_type = table.c[field_name].type
        if not isinstance(column_type, RemoteFile):
            msg = f"Model column '{field_name}' must use brussels.types.RemoteFile."
            raise TypeError(msg)
        return column_type

    def _resolve_store_ops(self, remote_file: RemoteFile) -> _StoreOps:
        if remote_file.store_ops is not None:
            return cast("_StoreOps", remote_file.store_ops)
        if _obstore_store is not None:
            return _obstore_store
        msg = "RemoteFileFacade requires the optional dependency 'obstore'. Install with `pip install brussels[files]`."
        raise ModuleNotFoundError(msg)

    @staticmethod
    def _model_id(model: SupportsFileId) -> str:
        model_id = getattr(model, "id", None)
        if model_id is None:
            msg = "RemoteFile operations require model.id to be set."
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
    def _get_metadata(*, model: object, field_name: str) -> RemoteFileMetadata | None:
        value = getattr(model, field_name)
        if value is None:
            return None
        if isinstance(value, RemoteFileMetadata):
            return value
        if isinstance(value, dict):
            metadata = RemoteFileMetadata.from_dict(value)
            setattr(model, field_name, metadata)
            return metadata
        type_name = type(value).__name__
        msg = f"Model field '{field_name}' must hold RemoteFileMetadata | dict | None, got {type_name}."
        raise TypeError(msg)

    async def create_pending(  # noqa: PLR0913
        self,
        *,
        model: SupportsFileId,
        field_name: str,
        bucket: str | None = None,
        key: str | None = None,
        url: str | None = None,
        filename: str | None = None,
        content_type: str | None = None,
        session: Session | AsyncSession | None = None,
        flush: bool = False,
    ) -> RemoteFileMetadata:
        remote_file = self._resolve_remote_file(model=model, field_name=field_name)
        now = remote_file.now()
        metadata = RemoteFileMetadata(
            bucket=bucket,
            key=key or remote_file.build_key(model_id=self._model_id(model), filename=filename),
            url=url,
            status=UploadStatus.PENDING,
            content_type=content_type,
            created_at=now,
            updated_at=now,
        )
        setattr(model, field_name, metadata)
        await self._flush(session=session, flush=flush)
        return metadata

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
    ) -> RemoteFileMetadata:
        remote_file = self._resolve_remote_file(model=model, field_name=field_name)
        metadata = self._get_metadata(model=model, field_name=field_name)
        if metadata is None:
            metadata = await self.create_pending(
                model=model,
                field_name=field_name,
                bucket=bucket,
                key=key,
                url=url,
                filename=filename,
                content_type=content_type,
                session=session,
                flush=flush,
            )
        else:
            update_now = remote_file.now()
            metadata = metadata.model_copy(
                update={
                    "bucket": bucket,
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
            result = await self.put(metadata.key, data, remote_file=remote_file, **put_kwargs)
        except Exception as exc:
            failed_metadata = metadata.model_copy(
                update={
                    "status": UploadStatus.FAILED,
                    "updated_at": remote_file.now(),
                    "error_message": str(exc),
                },
            )
            setattr(model, field_name, failed_metadata)
            await self._flush(session=session, flush=flush)
            raise

        finished_at = remote_file.now()
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

    async def download(
        self,
        metadata: RemoteFileMetadata,
        *,
        remote_file: RemoteFile | None = None,
        **kwargs: object,
    ) -> object:
        return await self.get(metadata.key, remote_file=remote_file, **kwargs)

    async def read_range(
        self,
        metadata: RemoteFileMetadata,
        start: int,
        end: int,
        *,
        remote_file: RemoteFile | None = None,
        **kwargs: object,
    ) -> object:
        return await self.get_range(metadata.key, start, end, remote_file=remote_file, **kwargs)

    async def delete_file(
        self,
        *,
        model: SupportsFileId,
        field_name: str,
        session: Session | AsyncSession | None = None,
        flush: bool = False,
        delete_remote: bool = True,
        **delete_kwargs: object,
    ) -> RemoteFileMetadata | None:
        remote_file = self._resolve_remote_file(model=model, field_name=field_name)
        metadata = self._get_metadata(model=model, field_name=field_name)
        if metadata is None:
            return None
        if delete_remote:
            await self.delete(metadata.key, remote_file=remote_file, **delete_kwargs)

        deleted_metadata = metadata.model_copy(
            update={
                "status": UploadStatus.DELETED,
                "updated_at": remote_file.now(),
                "error_message": None,
            },
        )
        setattr(model, field_name, deleted_metadata)
        await self._flush(session=session, flush=flush)
        return deleted_metadata

    async def put(
        self,
        *args: object,
        remote_file: RemoteFile | None = None,
        **kwargs: object,
    ) -> object:
        resolved_remote_file = remote_file or self._resolve_remote_file()
        store_ops = self._resolve_store_ops(resolved_remote_file)
        return await store_ops.put(resolved_remote_file.store, *args, **kwargs)

    async def put_multipart(
        self,
        *args: object,
        remote_file: RemoteFile | None = None,
        **kwargs: object,
    ) -> object:
        resolved_remote_file = remote_file or self._resolve_remote_file()
        store_ops = self._resolve_store_ops(resolved_remote_file)
        return await store_ops.put_multipart(resolved_remote_file.store, *args, **kwargs)

    async def get(
        self,
        *args: object,
        remote_file: RemoteFile | None = None,
        **kwargs: object,
    ) -> object:
        resolved_remote_file = remote_file or self._resolve_remote_file()
        store_ops = self._resolve_store_ops(resolved_remote_file)
        return await store_ops.get(resolved_remote_file.store, *args, **kwargs)

    async def get_range(
        self,
        *args: object,
        remote_file: RemoteFile | None = None,
        **kwargs: object,
    ) -> object:
        resolved_remote_file = remote_file or self._resolve_remote_file()
        store_ops = self._resolve_store_ops(resolved_remote_file)
        return await store_ops.get_range(resolved_remote_file.store, *args, **kwargs)

    async def head(
        self,
        *args: object,
        remote_file: RemoteFile | None = None,
        **kwargs: object,
    ) -> object:
        resolved_remote_file = remote_file or self._resolve_remote_file()
        store_ops = self._resolve_store_ops(resolved_remote_file)
        return await store_ops.head(resolved_remote_file.store, *args, **kwargs)

    async def list(
        self,
        *args: object,
        remote_file: RemoteFile | None = None,
        **kwargs: object,
    ) -> object:
        resolved_remote_file = remote_file or self._resolve_remote_file()
        store_ops = self._resolve_store_ops(resolved_remote_file)
        return await store_ops.list(resolved_remote_file.store, *args, **kwargs)

    async def list_with_delimiter(
        self,
        *args: object,
        remote_file: RemoteFile | None = None,
        **kwargs: object,
    ) -> object:
        resolved_remote_file = remote_file or self._resolve_remote_file()
        store_ops = self._resolve_store_ops(resolved_remote_file)
        return await store_ops.list_with_delimiter(resolved_remote_file.store, *args, **kwargs)

    async def delete(
        self,
        *args: object,
        remote_file: RemoteFile | None = None,
        **kwargs: object,
    ) -> object:
        resolved_remote_file = remote_file or self._resolve_remote_file()
        store_ops = self._resolve_store_ops(resolved_remote_file)
        return await store_ops.delete(resolved_remote_file.store, *args, **kwargs)

    async def copy(
        self,
        *args: object,
        remote_file: RemoteFile | None = None,
        **kwargs: object,
    ) -> object:
        resolved_remote_file = remote_file or self._resolve_remote_file()
        store_ops = self._resolve_store_ops(resolved_remote_file)
        return await store_ops.copy(resolved_remote_file.store, *args, **kwargs)

    async def rename(
        self,
        *args: object,
        remote_file: RemoteFile | None = None,
        **kwargs: object,
    ) -> object:
        resolved_remote_file = remote_file or self._resolve_remote_file()
        store_ops = self._resolve_store_ops(resolved_remote_file)
        return await store_ops.rename(resolved_remote_file.store, *args, **kwargs)

    async def sign(
        self,
        *args: object,
        remote_file: RemoteFile | None = None,
        **kwargs: object,
    ) -> object:
        resolved_remote_file = remote_file or self._resolve_remote_file()
        store_ops = self._resolve_store_ops(resolved_remote_file)
        return await store_ops.sign(resolved_remote_file.store, *args, **kwargs)

    async def attributes(
        self,
        *args: object,
        remote_file: RemoteFile | None = None,
        **kwargs: object,
    ) -> object:
        resolved_remote_file = remote_file or self._resolve_remote_file()
        store_ops = self._resolve_store_ops(resolved_remote_file)
        return await store_ops.attributes(resolved_remote_file.store, *args, **kwargs)
