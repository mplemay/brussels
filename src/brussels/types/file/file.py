from __future__ import annotations

from dataclasses import dataclass
from inspect import isawaitable
from typing import TYPE_CHECKING, Self, cast
from uuid import UUID

from sqlalchemy.orm import Session, object_session

from brussels.mixins import PrimaryKeyMixin
from brussels.types.file.lifecycle import (
    enqueue_delete_operation,
    enqueue_put_operation,
    snapshot_put_payload,
    snapshot_put_payload_async,
)
from brussels.types.file.metadata import RemoteMetadata
from brussels.types.file.storage import RemoteStorage
from brussels.utils import now

if TYPE_CHECKING:
    from obstore import Attributes, GetOptions, PutMode, PutResult
    from obstore._obstore import Bytes, GetResult
    from sqlalchemy.ext.asyncio import AsyncSession

    from brussels.types.file._types import PutAsyncInput, PutInput, RemoteMetadataField


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
    def _missing_model_id_message(*, operation: str) -> str:
        return (
            f"RemoteStorage {operation} requires model.id to be set. "
            f"Pass flush=True or flush the model before calling {operation}."
        )

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

    def _ensure_model_id_ready_sync(
        self,
        *,
        session: Session | None,
        flush: bool,
        operation: str,
    ) -> None:
        if getattr(self.model, "id", None) is not None:
            return
        if not flush:
            raise ValueError(self._missing_model_id_message(operation=operation))

        self._flush_sync(session=session, flush=True)
        if getattr(self.model, "id", None) is not None:
            return

        msg = f"RemoteStorage {operation} requires model.id to be set after flush."
        raise ValueError(msg)

    async def _ensure_model_id_ready_async(
        self,
        *,
        session: Session | AsyncSession | None,
        flush: bool,
        operation: str,
    ) -> None:
        if getattr(self.model, "id", None) is not None:
            return
        if not flush:
            raise ValueError(self._missing_model_id_message(operation=operation))

        await self._flush_async(session=session, flush=True)
        if getattr(self.model, "id", None) is not None:
            return

        msg = f"RemoteStorage {operation} requires model.id to be set after flush."
        raise ValueError(msg)

    @staticmethod
    def _resolve_sync_session(
        *,
        session: Session | AsyncSession | None,
        model: PrimaryKeyMixin,
    ) -> Session | None:
        if isinstance(session, Session):
            return session

        if session is not None and isinstance(sync_session := getattr(session, "sync_session", None), Session):
            return sync_session

        if isinstance(loaded_session := object_session(model), Session):
            return loaded_session
        return None

    def _required_sync_session(
        self,
        *,
        session: Session | AsyncSession | None,
        operation: str,
    ) -> Session:
        if (resolved_session := self._resolve_sync_session(session=session, model=self.model)) is not None:
            return resolved_session

        msg = (
            f"RemoteStorage {operation} requires a resolvable SQLAlchemy session. "
            "Pass a Session/AsyncSession or ensure the model is attached to one."
        )
        raise RuntimeError(msg)

    def _prepare_pending_metadata(
        self,
        *,
        key: str | None,
        content_type: str | None,
    ) -> RemoteMetadata:
        if (metadata := self.metadata) is None:
            created_now = now()
            metadata = RemoteMetadata(
                key=key or self.remote_storage.build_key(model_id=self._model_id(), field_name=self.field_name),
                status="pending",
                content_type=content_type,
                created_at=created_now,
                updated_at=created_now,
            )
            setattr(self.model, self.field_name, metadata)
            return metadata

        updated_metadata = metadata.model_copy(
            update={
                "key": key or metadata.key,
                "status": "pending",
                "content_type": content_type or metadata.content_type,
                "updated_at": now(),
            },
        )
        setattr(self.model, self.field_name, updated_metadata)
        return updated_metadata

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
        key: str | None = None,
        content_type: str | None = None,
        session: Session | None = None,
        flush: bool = False,
    ) -> PutResult:
        resolved_session = self._required_sync_session(session=session, operation="put")
        self._ensure_model_id_ready_sync(
            session=session or resolved_session,
            flush=flush,
            operation="put",
        )
        metadata = self._prepare_pending_metadata(
            key=key,
            content_type=content_type,
        )
        self._flush_sync(session=session or resolved_session, flush=flush)
        payload = snapshot_put_payload(file)
        enqueue_put_operation(
            session=resolved_session,
            model=self.model,
            field_name=self.field_name,
            remote_storage=self.remote_storage,
            metadata=metadata,
            payload=payload,
            attributes=attributes,
            tags=tags,
            mode=mode,
            use_multipart=use_multipart,
            chunk_size=chunk_size,
            max_concurrency=max_concurrency,
            content_type=content_type,
        )
        return cast("PutResult", {"e_tag": None, "version": None})

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
        key: str | None = None,
        content_type: str | None = None,
        session: Session | AsyncSession | None = None,
        flush: bool = False,
    ) -> PutResult:
        resolved_session = self._required_sync_session(session=session, operation="put")
        await self._ensure_model_id_ready_async(
            session=session or resolved_session,
            flush=flush,
            operation="put_async",
        )
        metadata = self._prepare_pending_metadata(
            key=key,
            content_type=content_type,
        )
        await self._flush_async(session=session or resolved_session, flush=flush)
        payload = await snapshot_put_payload_async(file)
        enqueue_put_operation(
            session=resolved_session,
            model=self.model,
            field_name=self.field_name,
            remote_storage=self.remote_storage,
            metadata=metadata,
            payload=payload,
            attributes=attributes,
            tags=tags,
            mode=mode,
            use_multipart=use_multipart,
            chunk_size=chunk_size,
            max_concurrency=max_concurrency,
            content_type=content_type,
        )
        return cast("PutResult", {"e_tag": None, "version": None})

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
            resolved_session = self._required_sync_session(session=session, operation="delete")
            enqueue_delete_operation(
                session=resolved_session,
                model=self.model,
                field_name=self.field_name,
                remote_storage=self.remote_storage,
                metadata=metadata,
            )
        setattr(self.model, self.field_name, None)
        self._flush_sync(
            session=session or self._resolve_sync_session(session=None, model=self.model),
            flush=flush,
        )

    async def delete_async(
        self,
        *,
        session: Session | AsyncSession | None = None,
        flush: bool = False,
        delete_remote: bool = True,
    ) -> None:
        metadata = self._required_metadata()
        if delete_remote:
            resolved_session = self._required_sync_session(session=session, operation="delete")
            enqueue_delete_operation(
                session=resolved_session,
                model=self.model,
                field_name=self.field_name,
                remote_storage=self.remote_storage,
                metadata=metadata,
            )
        setattr(self.model, self.field_name, None)
        await self._flush_async(
            session=session or self._resolve_sync_session(session=None, model=self.model),
            flush=flush,
        )
