from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from brussels.utils import now, utc

if TYPE_CHECKING:
    from datetime import datetime
else:
    from datetime import datetime as _datetime

type RemoteMetadataDict = dict[str, object]


class RemoteMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal[1] = Field(default=1, alias="schema")
    key: str
    status: Literal["pending", "complete", "failed", "deleted"] = "pending"
    size_bytes: int | None = None
    content_type: str | None = None
    etag: str | None = None
    checksum: str | None = None
    version: str | None = None
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)

    @field_validator("created_at", "updated_at", mode="after")
    @classmethod
    def _normalize_to_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return utc(value, raise_on_naive=False)

    def to_dict(self) -> RemoteMetadataDict:
        return cast("RemoteMetadataDict", self.model_dump(mode="json", by_alias=True))

    @classmethod
    def from_dict(cls, data: RemoteMetadataDict) -> Self:
        return cls.model_validate(data)


if not TYPE_CHECKING:
    RemoteMetadata.model_rebuild(_types_namespace={"datetime": _datetime})
