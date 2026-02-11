from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, Self, TypeVar, cast

from sqlalchemy.orm.attributes import InstrumentedAttribute

from brussels.types.file.file import RemoteMetadata, SupportsFileId
from brussels.types.file.storage import RemoteStorage

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import Session


class SupportsRemoteFileModel(Protocol):
    id: str | int | UUID | None
    __table__: object


ModelT = TypeVar("ModelT", bound=SupportsRemoteFileModel)
type RemoteMetadataField = InstrumentedAttribute[RemoteMetadata | None]


@dataclass(slots=True, kw_only=True)
class RemoteFile:
    model: SupportsRemoteFileModel
    field_name: str
    remote_storage: RemoteStorage

    @classmethod
    def from_metadata(cls, model: ModelT, field: RemoteMetadataField) -> Self:
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

    async def upload(  # noqa: PLR0913
        self,
        *,
        data: object,
        bucket: str | None = None,
        key: str | None = None,
        url: str | None = None,
        content_type: str | None = None,
        session: Session | AsyncSession | None = None,
        flush: bool = False,
        **put_kwargs: object,
    ) -> RemoteMetadata:
        return await self.remote_storage.upload(
            model=cast("SupportsFileId", self.model),
            field_name=self.field_name,
            data=data,
            bucket=bucket,
            key=key,
            url=url,
            content_type=content_type,
            session=session,
            flush=flush,
            **put_kwargs,
        )

    async def download(self, **kwargs: object) -> object:
        return await self.remote_storage.download(model=self.model, field_name=self.field_name, **kwargs)

    async def read_range(self, start: int, end: int, **kwargs: object) -> object:
        return await self.remote_storage.read_range(
            model=self.model,
            field_name=self.field_name,
            start=start,
            end=end,
            **kwargs,
        )

    async def delete(
        self,
        *,
        session: Session | AsyncSession | None = None,
        flush: bool = False,
        delete_remote: bool = True,
        **delete_kwargs: object,
    ) -> None:
        await self.remote_storage.delete_file(
            model=self.model,
            field_name=self.field_name,
            session=session,
            flush=flush,
            delete_remote=delete_remote,
            **delete_kwargs,
        )
