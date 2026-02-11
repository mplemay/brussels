from __future__ import annotations

from datetime import UTC, datetime
from inspect import isawaitable
from typing import TYPE_CHECKING, cast
from uuid import UUID

from pydantic import ValidationError  # ty: ignore[unresolved-import]
from sqlalchemy.types import TypeDecorator

from brussels.types.file.file import RemoteMetadata, RemoteMetadataDict, SupportsFileId, UploadStatus
from brussels.types.json_type import Json

if TYPE_CHECKING:
    from obstore.store import ObjectStore  # ty: ignore[unresolved-import]
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import Session


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


class RemoteStorage(TypeDecorator[RemoteMetadata]):
    impl = Json
    cache_ok = False

    def __init__(
        self,
        *,
        store: ObjectStore,
    ) -> None:
        super().__init__()
        self.store = store

    def build_key(self, *, model_id: str | int | UUID, field_name: str) -> str:
        return f"{str(model_id).lstrip('/')}/{field_name.lstrip('/')}"

    def process_bind_param(
        self,
        value: RemoteMetadata | RemoteMetadataDict | None,
        _dialect: object,
    ) -> RemoteMetadataDict | None:  # type: ignore[override]
        if value is None:
            return None
        try:
            metadata = value if isinstance(value, RemoteMetadata) else RemoteMetadata.from_dict(value)
        except ValidationError as exc:
            msg = "RemoteStorage RemoteMetadata is invalid."
            raise ValueError(msg) from exc
        return metadata.to_dict()

    def process_result_value(
        self,
        value: object,
        _dialect: object,
    ) -> RemoteMetadata | None:  # type: ignore[override]
        if value is None:
            return None
        if not isinstance(value, dict):
            type_name = type(value).__name__
            msg = f"RemoteStorage expected dict from database, got {type_name}."
            raise TypeError(msg)
        try:
            return RemoteMetadata.from_dict(cast("RemoteMetadataDict", value))
        except ValidationError as exc:
            msg = "RemoteStorage RemoteMetadata from database is invalid."
            raise ValueError(msg) from exc

    @staticmethod
    def _model_id(model: SupportsFileId) -> str:
        if (model_id := getattr(model, "id", None)) is None:
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
    def _get_metadata(*, model: object, field_name: str) -> RemoteMetadata | None:
        if (value := getattr(model, field_name)) is None:
            return None
        if isinstance(value, RemoteMetadata):
            return value
        if isinstance(value, dict):
            metadata = RemoteMetadata.from_dict(value)
            setattr(model, field_name, metadata)
            return metadata
        type_name = type(value).__name__
        msg = f"Model field '{field_name}' must hold RemoteMetadata | dict | None, got {type_name}."
        raise TypeError(msg)

    def get_metadata(self, *, model: object, field_name: str) -> RemoteMetadata | None:
        return self._get_metadata(model=model, field_name=field_name)

    async def _put(self, *args: object, **kwargs: object) -> object:
        return await self.store.put(*args, **kwargs)

    async def _get(self, *args: object, **kwargs: object) -> object:
        return await self.store.get(*args, **kwargs)

    async def _get_range(self, *args: object, **kwargs: object) -> object:
        return await self.store.get_range(*args, **kwargs)

    async def _delete(self, *args: object, **kwargs: object) -> object:
        return await self.store.delete(*args, **kwargs)

    async def upload(  # noqa: PLR0913
        self,
        *,
        model: SupportsFileId,
        field_name: str,
        data: object,
        bucket: str | None = None,
        key: str | None = None,
        url: str | None = None,
        content_type: str | None = None,
        session: Session | AsyncSession | None = None,
        flush: bool = False,
        **put_kwargs: object,
    ) -> RemoteMetadata:
        metadata = self._get_metadata(model=model, field_name=field_name)
        if metadata is None:
            now = datetime.now(UTC)
            metadata = RemoteMetadata(
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
            update_now = datetime.now(UTC)
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
                    "updated_at": datetime.now(UTC),
                    "error_message": f"upload failed ({type(exc).__name__})",
                },
            )
            setattr(model, field_name, failed_metadata)
            await self._flush(session=session, flush=flush)
            raise

        finished_at = datetime.now(UTC)
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
        if (metadata := self._get_metadata(model=model, field_name=field_name)) is None:
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
        if (metadata := self._get_metadata(model=model, field_name=field_name)) is None:
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
        if (metadata := self._get_metadata(model=model, field_name=field_name)) is None:
            msg = f"Model field '{field_name}' has no file metadata."
            raise ValueError(msg)
        if delete_remote:
            await self._delete(metadata.key, **delete_kwargs)
        setattr(model, field_name, None)
        await self._flush(session=session, flush=flush)
