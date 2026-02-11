from __future__ import annotations

from typing import TYPE_CHECKING, cast

from pydantic import ValidationError
from sqlalchemy.types import TypeDecorator

from brussels.types.file.metadata import RemoteMetadata, RemoteMetadataDict
from brussels.types.json_type import Json

if TYPE_CHECKING:
    from uuid import UUID

    from obstore.store import ObjectStore


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
