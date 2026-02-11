from __future__ import annotations

import logging
from collections.abc import AsyncIterable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, ClassVar, Final, Literal, cast

from sqlalchemy import event, update
from sqlalchemy.orm import Session, SessionTransaction

from brussels.utils import now

if TYPE_CHECKING:
    from collections.abc import Buffer, Callable, Iterator
    from typing import IO

    from obstore import Attributes, PutMode

    from brussels.mixins import PrimaryKeyMixin
    from brussels.types.file.metadata import RemoteMetadata
    from brussels.types.file.storage import RemoteStorage

    type PutInput = IO[bytes] | Path | bytes | Buffer | Iterator[Buffer] | Iterable[Buffer]
    type PutAsyncInput = PutInput | AsyncIterable[Buffer]
else:
    type PutInput = object
    type PutAsyncInput = object

LOGGER = logging.getLogger(__name__)

Outcome = Literal["commit", "rollback"]


@dataclass(slots=True, kw_only=True)
class QueuedPutOperation:
    model: PrimaryKeyMixin
    model_id: object
    model_type: type[object]
    field_name: str
    remote_storage: RemoteStorage
    metadata: RemoteMetadata
    payload: bytes
    attributes: Attributes | None
    tags: dict[str, str] | None
    mode: PutMode | None
    use_multipart: bool | None
    chunk_size: int
    max_concurrency: int
    content_type: str | None


@dataclass(slots=True, kw_only=True)
class QueuedDeleteOperation:
    model: PrimaryKeyMixin
    model_id: object
    model_type: type[object]
    field_name: str
    remote_storage: RemoteStorage
    metadata: RemoteMetadata


type QueuedOperation = QueuedPutOperation | QueuedDeleteOperation


@dataclass(slots=True)
class LifecycleState:
    queued_ops: dict[int, list[QueuedOperation]] = field(default_factory=dict)
    pre_root_ops: list[QueuedOperation] = field(default_factory=list)
    transaction_outcomes: dict[int, Outcome] = field(default_factory=dict)


class FileLifecycleCoordinator:
    LIFECYCLE_STATE_KEY: Final[str] = "brussels_file_lifecycle_state"
    _registered: ClassVar[bool] = False
    _register_lock: ClassVar[Lock] = Lock()

    @classmethod
    def ensure_listeners_registered(cls) -> None:
        if cls._registered:
            return

        with cls._register_lock:
            if cls._registered:
                return

            cls._listen_once("after_transaction_create", cls._after_transaction_create)
            cls._listen_once("after_commit", cls._after_commit)
            cls._listen_once("after_rollback", cls._after_rollback)
            cls._listen_once("after_transaction_end", cls._after_transaction_end)
            cls._registered = True

    @staticmethod
    def _listen_once(event_name: str, handler: Callable[..., None]) -> None:
        if event.contains(Session, event_name, handler):
            return
        event.listen(Session, event_name, handler)

    @classmethod
    def enqueue_put_operation(  # noqa: PLR0913
        cls,
        *,
        session: Session,
        model: PrimaryKeyMixin,
        field_name: str,
        remote_storage: RemoteStorage,
        metadata: RemoteMetadata,
        payload: bytes,
        attributes: Attributes | None,
        tags: dict[str, str] | None,
        mode: PutMode | None,
        use_multipart: bool | None,
        chunk_size: int,
        max_concurrency: int,
        content_type: str | None,
    ) -> None:
        cls.ensure_listeners_registered()
        operation = QueuedPutOperation(
            model=model,
            model_id=model.id,
            model_type=type(model),
            field_name=field_name,
            remote_storage=remote_storage,
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
        cls._enqueue_operation(session=session, operation=operation)

    @classmethod
    def enqueue_delete_operation(
        cls,
        *,
        session: Session,
        model: PrimaryKeyMixin,
        field_name: str,
        remote_storage: RemoteStorage,
        metadata: RemoteMetadata,
    ) -> None:
        cls.ensure_listeners_registered()
        operation = QueuedDeleteOperation(
            model=model,
            model_id=model.id,
            model_type=type(model),
            field_name=field_name,
            remote_storage=remote_storage,
            metadata=metadata,
        )
        cls._enqueue_operation(session=session, operation=operation)

    @classmethod
    def _state_for_session(cls, session: Session) -> LifecycleState:
        existing = session.info.get(cls.LIFECYCLE_STATE_KEY)
        if isinstance(existing, LifecycleState):
            return existing

        state = LifecycleState()
        session.info[cls.LIFECYCLE_STATE_KEY] = state
        return state

    @classmethod
    def _enqueue_operation(cls, *, session: Session, operation: QueuedOperation) -> None:
        state = cls._state_for_session(session)
        transaction = session.get_nested_transaction() or session.get_transaction()

        if transaction is None:
            state.pre_root_ops.append(operation)
            LOGGER.debug(
                "Queued file lifecycle operation before root transaction",
                extra={"field_name": operation.field_name},
            )
            return

        tx_id = id(transaction)
        state.queued_ops.setdefault(tx_id, []).append(operation)
        LOGGER.debug(
            "Queued file lifecycle operation in transaction",
            extra={"field_name": operation.field_name, "transaction_id": tx_id},
        )

    @classmethod
    def _after_transaction_create(cls, session: Session, transaction: SessionTransaction) -> None:
        state = cls._state_for_session(session)
        tx_id = id(transaction)
        if transaction.parent is None:
            state.queued_ops[tx_id] = state.pre_root_ops
            state.pre_root_ops = []
            LOGGER.debug(
                "Created root transaction queue",
                extra={"transaction_id": tx_id, "queued": len(state.queued_ops[tx_id])},
            )
            return

        state.queued_ops.setdefault(tx_id, [])
        LOGGER.debug("Created nested transaction queue", extra={"transaction_id": tx_id})

    @classmethod
    def _after_commit(cls, session: Session) -> None:
        cls._mark_outcome(session=session, outcome="commit")

    @classmethod
    def _after_rollback(cls, session: Session) -> None:
        cls._mark_outcome(session=session, outcome="rollback")

    @classmethod
    def _mark_outcome(cls, *, session: Session, outcome: Outcome) -> None:
        transaction = session.get_nested_transaction() or session.get_transaction()
        if transaction is None:
            return

        tx_id = id(transaction)
        state = cls._state_for_session(session)
        state.transaction_outcomes[tx_id] = outcome
        LOGGER.debug("Marked transaction outcome", extra={"transaction_id": tx_id, "outcome": outcome})

    @classmethod
    def _after_transaction_end(cls, session: Session, transaction: SessionTransaction) -> None:
        state = cast("LifecycleState | None", session.info.get(cls.LIFECYCLE_STATE_KEY))
        if state is None:
            return

        tx_id = id(transaction)
        queued_ops = state.queued_ops.pop(tx_id, [])
        outcome = state.transaction_outcomes.pop(tx_id, None)

        if transaction.parent is not None:
            if outcome == "commit":
                parent_id = id(transaction.parent)
                state.queued_ops.setdefault(parent_id, []).extend(queued_ops)
                LOGGER.debug(
                    "Merged nested transaction queue into parent",
                    extra={"transaction_id": tx_id, "parent_id": parent_id, "queued": len(queued_ops)},
                )
            else:
                LOGGER.debug(
                    "Discarded nested transaction queue",
                    extra={"transaction_id": tx_id, "queued": len(queued_ops)},
                )
            return

        try:
            if outcome == "commit" and queued_ops:
                LOGGER.debug("Executing committed file lifecycle queue", extra={"queued": len(queued_ops)})
                cls._execute_queued_operations(session=session, queued_ops=queued_ops)
            elif queued_ops:
                LOGGER.debug("Discarded root transaction queue", extra={"queued": len(queued_ops)})
        finally:
            session.info.pop(cls.LIFECYCLE_STATE_KEY, None)

    @classmethod
    def _execute_queued_operations(
        cls,
        *,
        session: Session,
        queued_ops: list[QueuedOperation],
    ) -> None:
        for operation in queued_ops:
            if isinstance(operation, QueuedPutOperation):
                cls._execute_put(session=session, operation=operation)
                continue
            cls._execute_delete(session=session, operation=operation)

    @classmethod
    def _operation_context(
        cls,
        *,
        operation: QueuedPutOperation | QueuedDeleteOperation,
        include_key: bool = True,
    ) -> dict[str, str]:
        context = {
            "model": operation.model_type.__name__,
            "model_id": str(operation.model_id),
            "field_name": operation.field_name,
        }
        if include_key:
            context["key"] = operation.metadata.key
        return context

    @classmethod
    def _set_and_persist_field(
        cls,
        *,
        session: Session,
        operation: QueuedPutOperation | QueuedDeleteOperation,
        metadata: RemoteMetadata | None,
    ) -> None:
        setattr(operation.model, operation.field_name, metadata)
        cls._persist_field_update(session=session, operation=operation, metadata=metadata)

    @classmethod
    def _execute_put(cls, *, session: Session, operation: QueuedPutOperation) -> None:
        try:
            result = operation.remote_storage.store.put(
                operation.metadata.key,
                operation.payload,
                attributes=operation.attributes,
                tags=operation.tags,
                mode=operation.mode,
                use_multipart=operation.use_multipart,
                chunk_size=operation.chunk_size,
                max_concurrency=operation.max_concurrency,
            )
        except Exception:
            LOGGER.exception("Deferred remote upload failed", extra=cls._operation_context(operation=operation))
            cls._cleanup_failed_put(operation=operation)
            failed_metadata = operation.metadata.model_copy(
                update={
                    "status": "failed",
                    "updated_at": now(),
                },
            )
            cls._set_and_persist_field(session=session, operation=operation, metadata=failed_metadata)
            return

        completed_metadata = cls._build_complete_metadata(
            metadata=operation.metadata,
            result=result,
            content_type=operation.content_type,
        )
        cls._set_and_persist_field(session=session, operation=operation, metadata=completed_metadata)

    @classmethod
    def _cleanup_failed_put(cls, *, operation: QueuedPutOperation) -> None:
        try:
            operation.remote_storage.store.delete(operation.metadata.key)
        except Exception:  # noqa: BLE001
            LOGGER.warning(
                "Deferred upload cleanup failed",
                exc_info=True,
                extra=cls._operation_context(operation=operation),
            )

    @classmethod
    def _execute_delete(cls, *, session: Session, operation: QueuedDeleteOperation) -> None:
        try:
            operation.remote_storage.store.delete(operation.metadata.key)
        except Exception:
            LOGGER.exception("Deferred remote delete failed", extra=cls._operation_context(operation=operation))
            failed_metadata = operation.metadata.model_copy(
                update={
                    "status": "failed",
                    "updated_at": now(),
                },
            )
            cls._set_and_persist_field(session=session, operation=operation, metadata=failed_metadata)
            return

        cls._set_and_persist_field(session=session, operation=operation, metadata=None)

    @classmethod
    def _persist_field_update(
        cls,
        *,
        session: Session,
        operation: QueuedPutOperation | QueuedDeleteOperation,
        metadata: RemoteMetadata | None,
    ) -> None:
        table = getattr(operation.model_type, "__table__", None)
        if table is None or "id" not in table.c:
            LOGGER.warning(
                "Could not persist deferred file metadata update",
                extra={"model": operation.model_type.__name__, "field_name": operation.field_name},
            )
            return

        bind = session.get_bind()
        statement = (
            update(operation.model_type)
            .where(table.c.id == operation.model_id)
            .values({operation.field_name: metadata})
        )

        try:
            with Session(bind=bind) as write_session:
                write_session.execute(statement)
                write_session.commit()
        except Exception:
            LOGGER.exception(
                "Persisting deferred file metadata update failed",
                extra=cls._operation_context(operation=operation, include_key=False),
            )

    @classmethod
    def _build_complete_metadata(
        cls,
        *,
        metadata: RemoteMetadata,
        result: object,
        content_type: str | None,
    ) -> RemoteMetadata:
        size_bytes = cls._extract_optional_int(result, "size_bytes", "size", "bytes")
        if size_bytes is None:
            size_bytes = metadata.size_bytes

        result_content_type = cls._extract_optional_str(result, "content_type", "contentType", "mime_type")
        if result_content_type is None:
            result_content_type = content_type or metadata.content_type

        etag = cls._extract_optional_str(result, "etag", "e_tag")
        if etag is None:
            etag = metadata.etag

        checksum = cls._extract_optional_str(result, "checksum", "sha256")
        if checksum is None:
            checksum = metadata.checksum

        version = cls._extract_optional_str(result, "version", "version_id")
        if version is None:
            version = metadata.version

        return metadata.model_copy(
            update={
                "status": "complete",
                "size_bytes": size_bytes,
                "content_type": result_content_type,
                "etag": etag,
                "checksum": checksum,
                "version": version,
                "updated_at": now(),
            },
        )

    @staticmethod
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

    @classmethod
    def _extract_optional_str(cls, result: object, *field_names: str) -> str | None:
        if (value := cls._extract_value(result, *field_names)) is None:
            return None
        if not isinstance(value, str):
            type_name = type(value).__name__
            msg = f"Expected string metadata field from obstore result, got {type_name}."
            raise TypeError(msg)
        return value

    @classmethod
    def _extract_optional_int(cls, result: object, *field_names: str) -> int | None:
        if (value := cls._extract_value(result, *field_names)) is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            type_name = type(value).__name__
            msg = f"Expected integer metadata field from obstore result, got {type_name}."
            raise TypeError(msg)
        return value


def ensure_lifecycle_listeners_registered() -> None:
    FileLifecycleCoordinator.ensure_listeners_registered()


def enqueue_put_operation(  # noqa: PLR0913
    *,
    session: Session,
    model: PrimaryKeyMixin,
    field_name: str,
    remote_storage: RemoteStorage,
    metadata: RemoteMetadata,
    payload: bytes,
    attributes: Attributes | None,
    tags: dict[str, str] | None,
    mode: PutMode | None,
    use_multipart: bool | None,
    chunk_size: int,
    max_concurrency: int,
    content_type: str | None,
) -> None:
    return FileLifecycleCoordinator.enqueue_put_operation(
        session=session,
        model=model,
        field_name=field_name,
        remote_storage=remote_storage,
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


def enqueue_delete_operation(
    *,
    session: Session,
    model: PrimaryKeyMixin,
    field_name: str,
    remote_storage: RemoteStorage,
    metadata: RemoteMetadata,
) -> None:
    FileLifecycleCoordinator.enqueue_delete_operation(
        session=session,
        model=model,
        field_name=field_name,
        remote_storage=remote_storage,
        metadata=metadata,
    )


def snapshot_put_payload(file: PutInput) -> bytes:
    if isinstance(file, bytes):
        return file
    if isinstance(file, bytearray | memoryview):
        return bytes(file)
    if isinstance(file, Path):
        return file.read_bytes()

    read_method = getattr(file, "read", None)
    if callable(read_method):
        data = read_method()
        if isinstance(data, bytes):
            return data
        if isinstance(data, bytearray | memoryview):
            return bytes(data)
        type_name = type(data).__name__
        msg = f"Expected bytes when reading upload input, got {type_name}."
        raise TypeError(msg)

    if isinstance(file, Iterable):
        return b"".join(_to_bytes(chunk) for chunk in file)

    type_name = type(file).__name__
    msg = f"Upload input type '{type_name}' is not supported for deferred transactions."
    raise TypeError(msg)


async def snapshot_put_payload_async(file: PutAsyncInput) -> bytes:
    if isinstance(file, AsyncIterable):
        parts = [_to_bytes(chunk) async for chunk in file]
        return b"".join(parts)

    return snapshot_put_payload(file)


def _to_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray | memoryview):
        return bytes(value)

    try:
        return bytes(cast("bytes | bytearray | memoryview", value))
    except Exception as exc:
        type_name = type(value).__name__
        msg = f"Upload chunk type '{type_name}' cannot be converted to bytes."
        raise TypeError(msg) from exc
