from __future__ import annotations

from dataclasses import dataclass
from inspect import isawaitable
from typing import TYPE_CHECKING, Self, cast
from uuid import UUID

from sqlalchemy.orm.attributes import InstrumentedAttribute

from brussels.mixins import PrimaryKeyMixin
from brussels.types.file.metadata import RemoteMetadata
from brussels.types.file.storage import RemoteStorage
from brussels.utils import now

if TYPE_CHECKING:
    from collections.abc import AsyncIterable, AsyncIterator, Buffer, Iterable, Iterator
    from pathlib import Path
    from typing import IO

    from obstore import Attributes, GetOptions, PutMode, PutResult
    from obstore._obstore import Bytes, GetResult
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import Session

    type PutInput = IO[bytes] | Path | bytes | Buffer | Iterator[Buffer] | Iterable[Buffer]
    type PutAsyncInput = (
        IO[bytes]
        | Path
        | bytes
        | Buffer
        | AsyncIterator[Buffer]
        | AsyncIterable[Buffer]
        | Iterator[Buffer]
        | Iterable[Buffer]
    )
else:
    type PutInput = object
    type PutAsyncInput = object

type RemoteMetadataField = InstrumentedAttribute[RemoteMetadata | None]


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
    if (value := _extract_value(result, *field_names)) is None:
        return None
    if not isinstance(value, str):
        type_name = type(value).__name__
        msg = f"Expected string metadata field from obstore result, got {type_name}."
        raise TypeError(msg)
    return value


def _extract_optional_int(result: object, *field_names: str) -> int | None:
    if (value := _extract_value(result, *field_names)) is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        type_name = type(value).__name__
        msg = f"Expected integer metadata field from obstore result, got {type_name}."
        raise TypeError(msg)
    return value


@dataclass(slots=True, kw_only=True, frozen=True)
class RemoteFile[M: PrimaryKeyMixin]:
    model: M
    field_name: str
    remote_storage: RemoteStorage

    @classmethod
    def from_metadata(cls, model: M, field: RemoteMetadataField) -> Self:
        if not isinstance(model, PrimaryKeyMixin):
            msg = "RemoteStorage operations require models that inherit from brussels.mixins.PrimaryKeyMixin."
            raise TypeError(msg)
        if not isinstance(field_name := getattr(field, "key", None), str):
            msg = "RemoteStorage operations require a mapped SQLAlchemy field."
            raise TypeError(msg)
        if isinstance(field_owner := getattr(field, "class_", None), type) and not isinstance(model, field_owner):
            msg = f"Field '{field_name}' is not mapped on model type '{type(model).__name__}'."
            raise TypeError(msg)

        table = getattr(type(model), "__table__", None)
        if table is None:
            msg = "RemoteStorage operations require SQLAlchemy model instances with __table__ metadata."
            raise TypeError(msg)
        if field_name not in table.c:
            msg = f"Model does not define column '{field_name}'."
            raise ValueError(msg)
        column_type = table.c[field_name].type
        if not isinstance(column_type, RemoteStorage):
            msg = f"Model column '{field_name}' must use brussels.types.file.RemoteStorage."
            raise TypeError(msg)

        return cls(model=model, field_name=field_name, remote_storage=column_type)

    @property
    def metadata(self) -> RemoteMetadata | None:
        return self.remote_storage.get_metadata(model=self.model, field_name=self.field_name)

    def _model_id(self) -> str:
        if (model_id := getattr(self.model, "id", None)) is None:
            msg = "RemoteStorage operations require model.id to be set."
            raise ValueError(msg)
        if not isinstance(model_id, str | int | UUID):
            type_name = type(model_id).__name__
            msg = f"Model id must be str, int, or UUID, got {type_name}."
            raise TypeError(msg)
        return str(model_id)

    @staticmethod
    def _flush_sync(*, session: Session | None, flush: bool) -> None:
        if not flush or session is None:
            return
        session.flush()

    @staticmethod
    async def _flush_async(*, session: Session | AsyncSession | None, flush: bool) -> None:
        if not flush or session is None:
            return
        maybe_awaitable = session.flush()
        if isawaitable(maybe_awaitable):
            await maybe_awaitable

    def _prepare_pending_metadata(
        self,
        *,
        bucket: str | None,
        key: str | None,
        url: str | None,
        content_type: str | None,
    ) -> RemoteMetadata:
        if (metadata := self.metadata) is None:
            created_now = now()
            metadata = RemoteMetadata(
                bucket=bucket,
                key=key or self.remote_storage.build_key(model_id=self._model_id(), field_name=self.field_name),
                url=url,
                status="pending",
                content_type=content_type,
                created_at=created_now,
                updated_at=created_now,
            )
            setattr(self.model, self.field_name, metadata)
            return metadata

        updated_metadata = metadata.model_copy(
            update={
                "bucket": bucket if bucket is not None else metadata.bucket,
                "key": key or metadata.key,
                "url": url or metadata.url,
                "status": "pending",
                "content_type": content_type or metadata.content_type,
                "updated_at": now(),
                "uploaded_at": None,
                "error_message": None,
            },
        )
        setattr(self.model, self.field_name, updated_metadata)
        return updated_metadata

    def _apply_failed_metadata(self, *, metadata: RemoteMetadata, exc: Exception) -> None:
        failed_metadata = metadata.model_copy(
            update={
                "status": "failed",
                "updated_at": now(),
                "error_message": f"upload failed ({type(exc).__name__})",
            },
        )
        setattr(self.model, self.field_name, failed_metadata)

    def _apply_complete_metadata(
        self,
        *,
        metadata: RemoteMetadata,
        result: object,
        content_type: str | None,
    ) -> None:
        finished_at = now()
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
                "status": "complete",
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
        setattr(self.model, self.field_name, completed_metadata)

    def _required_metadata(self) -> RemoteMetadata:
        if (metadata := self.metadata) is None:
            msg = f"Model field '{self.field_name}' has no file metadata."
            raise ValueError(msg)
        return metadata

    def put(  # noqa: PLR0913
        self,
        file: PutInput,
        *,
        attributes: Attributes | None = None,
        tags: dict[str, str] | None = None,
        mode: PutMode | None = None,
        use_multipart: bool | None = None,
        chunk_size: int = 5 * 1024 * 1024,
        max_concurrency: int = 12,
        bucket: str | None = None,
        key: str | None = None,
        url: str | None = None,
        content_type: str | None = None,
        session: Session | None = None,
        flush: bool = False,
    ) -> PutResult:
        metadata = self._prepare_pending_metadata(
            bucket=bucket,
            key=key,
            url=url,
            content_type=content_type,
        )
        self._flush_sync(session=session, flush=flush)

        try:
            result = self.remote_storage.store.put(
                metadata.key,
                file,
                attributes=attributes,
                tags=tags,
                mode=mode,
                use_multipart=use_multipart,
                chunk_size=chunk_size,
                max_concurrency=max_concurrency,
            )
        except Exception as exc:
            self._apply_failed_metadata(metadata=metadata, exc=exc)
            self._flush_sync(session=session, flush=flush)
            raise

        self._apply_complete_metadata(
            metadata=metadata,
            result=result,
            content_type=content_type,
        )
        self._flush_sync(session=session, flush=flush)
        return result

    async def put_async(  # noqa: PLR0913
        self,
        file: PutAsyncInput,
        *,
        attributes: Attributes | None = None,
        tags: dict[str, str] | None = None,
        mode: PutMode | None = None,
        use_multipart: bool | None = None,
        chunk_size: int = 5 * 1024 * 1024,
        max_concurrency: int = 12,
        bucket: str | None = None,
        key: str | None = None,
        url: str | None = None,
        content_type: str | None = None,
        session: Session | AsyncSession | None = None,
        flush: bool = False,
    ) -> PutResult:
        metadata = self._prepare_pending_metadata(
            bucket=bucket,
            key=key,
            url=url,
            content_type=content_type,
        )
        await self._flush_async(session=session, flush=flush)

        try:
            result = await self.remote_storage.store.put_async(
                metadata.key,
                file,
                attributes=attributes,
                tags=tags,
                mode=mode,
                use_multipart=use_multipart,
                chunk_size=chunk_size,
                max_concurrency=max_concurrency,
            )
        except Exception as exc:
            self._apply_failed_metadata(metadata=metadata, exc=exc)
            await self._flush_async(session=session, flush=flush)
            raise

        self._apply_complete_metadata(
            metadata=metadata,
            result=result,
            content_type=content_type,
        )
        await self._flush_async(session=session, flush=flush)
        return result

    def get(
        self,
        *,
        options: GetOptions | None = None,
    ) -> GetResult:
        metadata = self._required_metadata()
        return self.remote_storage.store.get(
            metadata.key,
            options=options,
        )

    async def get_async(
        self,
        *,
        options: GetOptions | None = None,
    ) -> GetResult:
        metadata = self._required_metadata()
        return await self.remote_storage.store.get_async(
            metadata.key,
            options=options,
        )

    def get_range(
        self,
        *,
        start: int,
        end: int | None = None,
        length: int | None = None,
    ) -> Bytes:
        metadata = self._required_metadata()
        return self.remote_storage.store.get_range(
            metadata.key,
            start=start,
            end=end,
            length=length,
        )

    async def get_range_async(
        self,
        *,
        start: int,
        end: int | None = None,
        length: int | None = None,
    ) -> Bytes:
        metadata = self._required_metadata()
        return await self.remote_storage.store.get_range_async(
            metadata.key,
            start=start,
            end=end,
            length=length,
        )

    def delete(
        self,
        *,
        session: Session | None = None,
        flush: bool = False,
        delete_remote: bool = True,
    ) -> None:
        metadata = self._required_metadata()
        if delete_remote:
            self.remote_storage.store.delete(metadata.key)
        setattr(self.model, self.field_name, None)
        self._flush_sync(session=session, flush=flush)

    async def delete_async(
        self,
        *,
        session: Session | AsyncSession | None = None,
        flush: bool = False,
        delete_remote: bool = True,
    ) -> None:
        metadata = self._required_metadata()
        if delete_remote:
            await self.remote_storage.store.delete_async(metadata.key)
        setattr(self.model, self.field_name, None)
        await self._flush_async(session=session, flush=flush)
