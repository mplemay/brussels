from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from importlib import import_module
from inspect import isawaitable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast
from uuid import uuid4

from brussels.types import RemoteFileMetadata, UploadStatus

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import Session


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


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _default_key_factory(filename: str | None) -> str:
    suffix = ""
    if filename is not None:
        suffix = Path(filename).suffix.lower()
    return f"{uuid4().hex}{suffix}"


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
    def __init__(
        self,
        *,
        store: object,
        key_prefix: str | None = None,
        now: Callable[[], datetime] | None = None,
        key_factory: Callable[[str | None], str] | None = None,
        store_ops: object | None = None,
    ) -> None:
        self._store = store
        self._key_prefix = key_prefix.strip("/") if key_prefix is not None else ""
        self._now = now or _utc_now
        self._key_factory = key_factory or _default_key_factory

        if store_ops is not None:
            self._store_ops = cast("_StoreOps", store_ops)
            return
        if _obstore_store is not None:
            self._store_ops = _obstore_store
            return

        msg = "RemoteFileFacade requires the optional dependency 'obstore'. Install with `pip install brussels[files]`."
        raise ModuleNotFoundError(msg)

    def _with_prefix(self, key: str) -> str:
        if self._key_prefix == "":
            return key
        return f"{self._key_prefix}/{key}"

    def _build_key(self, filename: str | None) -> str:
        return self._with_prefix(self._key_factory(filename))

    def _get_metadata(self, *, model: object, field_name: str) -> RemoteFileMetadata | None:
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

    async def _flush(self, *, session: Session | AsyncSession | None, flush: bool) -> None:
        if not flush or session is None:
            return
        maybe_awaitable = session.flush()
        if isawaitable(maybe_awaitable):
            await maybe_awaitable

    async def create_pending(  # noqa: PLR0913
        self,
        *,
        model: object,
        field_name: str,
        store_name: str,
        bucket: str | None = None,
        key: str | None = None,
        url: str | None = None,
        filename: str | None = None,
        content_type: str | None = None,
        session: Session | AsyncSession | None = None,
        flush: bool = False,
    ) -> RemoteFileMetadata:
        now = self._now()
        metadata = RemoteFileMetadata(
            store_name=store_name,
            bucket=bucket,
            key=key or self._build_key(filename),
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
        model: object,
        field_name: str,
        data: object,
        store_name: str,
        bucket: str | None = None,
        key: str | None = None,
        url: str | None = None,
        filename: str | None = None,
        content_type: str | None = None,
        session: Session | AsyncSession | None = None,
        flush: bool = False,
        **put_kwargs: object,
    ) -> RemoteFileMetadata:
        metadata = self._get_metadata(model=model, field_name=field_name)
        if metadata is None:
            metadata = await self.create_pending(
                model=model,
                field_name=field_name,
                store_name=store_name,
                bucket=bucket,
                key=key,
                url=url,
                filename=filename,
                content_type=content_type,
                session=session,
                flush=flush,
            )
        else:
            update_now = self._now()
            metadata = replace(
                metadata,
                store_name=store_name,
                bucket=bucket,
                key=key or metadata.key,
                url=url or metadata.url,
                status=UploadStatus.PENDING,
                content_type=content_type or metadata.content_type,
                updated_at=update_now,
                uploaded_at=None,
                error_message=None,
            )
            setattr(model, field_name, metadata)
            await self._flush(session=session, flush=flush)

        if content_type is not None and "content_type" not in put_kwargs and "contentType" not in put_kwargs:
            put_kwargs["content_type"] = content_type

        try:
            result = await self.put(metadata.key, data, **put_kwargs)
        except Exception as exc:
            failed_metadata = replace(
                metadata,
                status=UploadStatus.FAILED,
                updated_at=self._now(),
                error_message=str(exc),
            )
            setattr(model, field_name, failed_metadata)
            await self._flush(session=session, flush=flush)
            raise

        finished_at = self._now()
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

        completed_metadata = replace(
            metadata,
            status=UploadStatus.COMPLETE,
            size_bytes=size_bytes,
            content_type=result_content_type,
            etag=etag,
            checksum=checksum,
            version=version,
            updated_at=finished_at,
            uploaded_at=finished_at,
            error_message=None,
        )
        setattr(model, field_name, completed_metadata)
        await self._flush(session=session, flush=flush)
        return completed_metadata

    async def download(self, metadata: RemoteFileMetadata, **kwargs: object) -> object:
        return await self.get(metadata.key, **kwargs)

    async def read_range(
        self,
        metadata: RemoteFileMetadata,
        start: int,
        end: int,
        **kwargs: object,
    ) -> object:
        return await self.get_range(metadata.key, start, end, **kwargs)

    async def delete_file(
        self,
        *,
        model: object,
        field_name: str,
        session: Session | AsyncSession | None = None,
        flush: bool = False,
        delete_remote: bool = True,
        **delete_kwargs: object,
    ) -> RemoteFileMetadata | None:
        metadata = self._get_metadata(model=model, field_name=field_name)
        if metadata is None:
            return None
        if delete_remote:
            await self.delete(metadata.key, **delete_kwargs)

        deleted_metadata = replace(
            metadata,
            status=UploadStatus.DELETED,
            updated_at=self._now(),
            error_message=None,
        )
        setattr(model, field_name, deleted_metadata)
        await self._flush(session=session, flush=flush)
        return deleted_metadata

    async def put(self, *args: object, **kwargs: object) -> object:
        return await self._store_ops.put(self._store, *args, **kwargs)

    async def put_multipart(self, *args: object, **kwargs: object) -> object:
        return await self._store_ops.put_multipart(self._store, *args, **kwargs)

    async def get(self, *args: object, **kwargs: object) -> object:
        return await self._store_ops.get(self._store, *args, **kwargs)

    async def get_range(self, *args: object, **kwargs: object) -> object:
        return await self._store_ops.get_range(self._store, *args, **kwargs)

    async def head(self, *args: object, **kwargs: object) -> object:
        return await self._store_ops.head(self._store, *args, **kwargs)

    async def list(self, *args: object, **kwargs: object) -> object:
        return await self._store_ops.list(self._store, *args, **kwargs)

    async def list_with_delimiter(self, *args: object, **kwargs: object) -> object:
        return await self._store_ops.list_with_delimiter(self._store, *args, **kwargs)

    async def delete(self, *args: object, **kwargs: object) -> object:
        return await self._store_ops.delete(self._store, *args, **kwargs)

    async def copy(self, *args: object, **kwargs: object) -> object:
        return await self._store_ops.copy(self._store, *args, **kwargs)

    async def rename(self, *args: object, **kwargs: object) -> object:
        return await self._store_ops.rename(self._store, *args, **kwargs)

    async def sign(self, *args: object, **kwargs: object) -> object:
        return await self._store_ops.sign(self._store, *args, **kwargs)

    async def attributes(self, *args: object, **kwargs: object) -> object:
        return await self._store_ops.attributes(self._store, *args, **kwargs)
