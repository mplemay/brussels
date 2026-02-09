from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Self, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator  # ty: ignore[unresolved-import]
from sqlalchemy import JSON
from sqlalchemy.types import TypeDecorator

from brussels.types.json_type import Json

if TYPE_CHECKING:
    from sqlalchemy.engine.interfaces import Dialect
    from sqlalchemy.sql.type_api import TypeEngine

type RemoteFileDict = dict[str, object]
type RemoteFileNowFactory = Callable[[], datetime]
type RemoteFileKeyFactory = Callable[[str, str | None], str]


class UploadStatus(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"
    DELETED = "deleted"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _default_key_factory(model_id: str, filename: str | None) -> str:
    suffix = ""
    if filename is not None:
        suffix = Path(filename).suffix.lower()
    return f"{model_id}/{uuid4().hex}{suffix}"


class RemoteFileMetadata(BaseModel):
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


class RemoteFile(TypeDecorator[RemoteFileMetadata]):
    impl = JSON
    cache_ok = False

    def __init__(
        self,
        *,
        store: object,
        key_prefix: str | None = None,
        now: RemoteFileNowFactory | None = None,
        key_factory: RemoteFileKeyFactory | None = None,
        store_ops: object | None = None,
    ) -> None:
        super().__init__()
        self.store = store
        self.key_prefix = key_prefix.strip("/") if key_prefix is not None else ""
        self.now = now or _utc_now
        self.key_factory = key_factory or _default_key_factory
        self.store_ops = store_ops

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[object]:
        return dialect.type_descriptor(Json)

    def build_key(self, *, model_id: str | int | UUID, filename: str | None = None) -> str:
        key = self.key_factory(str(model_id), filename).lstrip("/")
        if self.key_prefix == "":
            return key
        return f"{self.key_prefix}/{key}"

    def process_bind_param(
        self,
        value: RemoteFileMetadata | RemoteFileDict | None,
        _dialect: object,
    ) -> RemoteFileDict | None:  # type: ignore[override]
        if value is None:
            return None
        try:
            metadata = value if isinstance(value, RemoteFileMetadata) else RemoteFileMetadata.from_dict(value)
        except ValidationError as exc:
            msg = "RemoteFile metadata is invalid."
            raise ValueError(msg) from exc
        return metadata.to_dict()

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
        try:
            return RemoteFileMetadata.from_dict(cast("RemoteFileDict", value))
        except ValidationError as exc:
            msg = "RemoteFile metadata from database is invalid."
            raise ValueError(msg) from exc
