from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Protocol, Self, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator  # ty: ignore[unresolved-import]

if TYPE_CHECKING:
    from uuid import UUID

type RemoteFileDict = dict[str, object]


class SupportsFileId(Protocol):
    id: str | int | UUID


class UploadStatus(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"
    DELETED = "deleted"


class RemoteFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema: Literal[1] = 1
    bucket: str | None = None
    key: str
    url: str | None = None
    status: UploadStatus = UploadStatus.PENDING
    size_bytes: int | None = None
    content_type: str | None = None
    etag: str | None = None
    checksum: str | None = None
    version: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
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
