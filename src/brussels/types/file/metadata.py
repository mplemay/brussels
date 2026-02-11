from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator  # ty: ignore[unresolved-import]

from brussels.utils import now, utc

if TYPE_CHECKING:
    from datetime import datetime

type RemoteMetadataDict = dict[str, object]


class RemoteMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema: Literal[1] = 1
    bucket: str | None = None
    key: str
    url: str | None = None
    status: Literal["pending", "complete", "failed", "deleted"] = "pending"
    size_bytes: int | None = None
    content_type: str | None = None
    etag: str | None = None
    checksum: str | None = None
    version: str | None = None
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
    uploaded_at: datetime | None = None
    error_message: str | None = None

    @field_validator("created_at", "updated_at", "uploaded_at", mode="after")
    @classmethod
    def _normalize_to_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return utc(value, raise_on_naive=False)

    def to_dict(self) -> RemoteMetadataDict:
        return cast("RemoteMetadataDict", self.model_dump(mode="json"))

    @classmethod
    def from_dict(cls, data: RemoteMetadataDict) -> Self:
        return cls.model_validate(data)
