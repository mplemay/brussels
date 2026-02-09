from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self, cast

from sqlalchemy import JSON
from sqlalchemy.types import TypeDecorator

from brussels.types.json_type import Json

type RemoteFileDict = dict[str, object]

_REQUIRED_FIELDS = frozenset({"store_name", "key", "status", "created_at", "updated_at"})
_ALLOWED_FIELDS = frozenset(
    {
        "schema_version",
        "store_name",
        "bucket",
        "key",
        "url",
        "status",
        "size_bytes",
        "content_type",
        "etag",
        "checksum",
        "version",
        "created_at",
        "updated_at",
        "uploaded_at",
        "error_message",
    },
)


class UploadStatus(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"
    DELETED = "deleted"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _ensure_utc(value: datetime, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        type_name = type(value).__name__
        msg = f"RemoteFileMetadata field '{field_name}' requires datetime value, got {type_name}."
        raise TypeError(msg)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _require_str(data: RemoteFileDict, *, field_name: str) -> str:
    value = data[field_name]
    if not isinstance(value, str):
        type_name = type(value).__name__
        msg = f"RemoteFileMetadata field '{field_name}' requires str value, got {type_name}."
        raise TypeError(msg)
    return value


def _optional_str(data: RemoteFileDict, *, field_name: str) -> str | None:
    value = data.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        type_name = type(value).__name__
        msg = f"RemoteFileMetadata field '{field_name}' requires str | None, got {type_name}."
        raise TypeError(msg)
    return value


def _optional_int(data: RemoteFileDict, *, field_name: str) -> int | None:
    value = data.get(field_name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        type_name = type(value).__name__
        msg = f"RemoteFileMetadata field '{field_name}' requires int | None, got {type_name}."
        raise TypeError(msg)
    return value


def _parse_datetime(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str):
        type_name = type(value).__name__
        msg = f"RemoteFileMetadata field '{field_name}' requires ISO-8601 str value, got {type_name}."
        raise TypeError(msg)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        msg = f"RemoteFileMetadata field '{field_name}' must be a valid ISO-8601 datetime."
        raise ValueError(msg) from exc
    return _ensure_utc(parsed, field_name=field_name)


@dataclass(slots=True, kw_only=True)
class RemoteFileMetadata:
    store_name: str
    key: str
    schema_version: int = 1
    bucket: str | None = None
    url: str | None = None
    status: UploadStatus = UploadStatus.PENDING
    size_bytes: int | None = None
    content_type: str | None = None
    etag: str | None = None
    checksum: str | None = None
    version: str | None = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    uploaded_at: datetime | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        self.created_at = _ensure_utc(self.created_at, field_name="created_at")
        self.updated_at = _ensure_utc(self.updated_at, field_name="updated_at")
        if self.uploaded_at is not None:
            self.uploaded_at = _ensure_utc(self.uploaded_at, field_name="uploaded_at")

    def to_dict(self) -> RemoteFileDict:
        uploaded_at_value = None if self.uploaded_at is None else self.uploaded_at.isoformat()

        return {
            "schema_version": self.schema_version,
            "store_name": self.store_name,
            "bucket": self.bucket,
            "key": self.key,
            "url": self.url,
            "status": self.status.value,
            "size_bytes": self.size_bytes,
            "content_type": self.content_type,
            "etag": self.etag,
            "checksum": self.checksum,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "uploaded_at": uploaded_at_value,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: RemoteFileDict) -> Self:
        unexpected_fields = set(data) - _ALLOWED_FIELDS
        if unexpected_fields:
            msg = f"RemoteFileMetadata contains unknown fields: {sorted(unexpected_fields)}."
            raise ValueError(msg)

        missing_fields = _REQUIRED_FIELDS - set(data)
        if missing_fields:
            msg = f"RemoteFileMetadata is missing required fields: {sorted(missing_fields)}."
            raise ValueError(msg)

        schema_version_value = data.get("schema_version", 1)
        if isinstance(schema_version_value, bool) or not isinstance(schema_version_value, int):
            type_name = type(schema_version_value).__name__
            msg = f"RemoteFileMetadata field 'schema_version' requires int value, got {type_name}."
            raise TypeError(msg)

        status_value = _require_str(data, field_name="status")
        try:
            status = UploadStatus(status_value)
        except ValueError as exc:
            allowed = [item.value for item in UploadStatus]
            msg = f"RemoteFileMetadata status must be one of {allowed}, got '{status_value}'."
            raise ValueError(msg) from exc

        uploaded_at_raw = data.get("uploaded_at")
        uploaded_at = None if uploaded_at_raw is None else _parse_datetime(uploaded_at_raw, field_name="uploaded_at")

        return cls(
            schema_version=schema_version_value,
            store_name=_require_str(data, field_name="store_name"),
            bucket=_optional_str(data, field_name="bucket"),
            key=_require_str(data, field_name="key"),
            url=_optional_str(data, field_name="url"),
            status=status,
            size_bytes=_optional_int(data, field_name="size_bytes"),
            content_type=_optional_str(data, field_name="content_type"),
            etag=_optional_str(data, field_name="etag"),
            checksum=_optional_str(data, field_name="checksum"),
            version=_optional_str(data, field_name="version"),
            created_at=_parse_datetime(data["created_at"], field_name="created_at"),
            updated_at=_parse_datetime(data["updated_at"], field_name="updated_at"),
            uploaded_at=uploaded_at,
            error_message=_optional_str(data, field_name="error_message"),
        )


class RemoteFile(TypeDecorator[RemoteFileMetadata]):
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:  # noqa: ANN401
        return dialect.type_descriptor(Json)

    def process_bind_param(
        self,
        value: RemoteFileMetadata | RemoteFileDict | None,
        _dialect: object,
    ) -> RemoteFileDict | None:  # type: ignore[override]
        if value is None:
            return None
        if isinstance(value, RemoteFileMetadata):
            return value.to_dict()
        if isinstance(value, dict):
            return RemoteFileMetadata.from_dict(value).to_dict()
        type_name = type(value).__name__
        msg = f"RemoteFile requires RemoteFileMetadata | dict | None, got {type_name}."
        raise TypeError(msg)

    def process_result_value(
        self,
        value: object,
        _dialect: object,
    ) -> RemoteFileMetadata | None:  # type: ignore[override]
        if value is None:
            return None
        if not isinstance(value, dict):
            type_name = type(value).__name__
            msg = f"RemoteFile expected dict from database, got {type_name}."
            raise TypeError(msg)
        return RemoteFileMetadata.from_dict(cast("RemoteFileDict", value))
