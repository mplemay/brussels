from __future__ import annotations

from typing import cast

import pytest
from sqlalchemy.orm import Mapped, mapped_column

from brussels.base import Base, DataclassBase
from brussels.mixins import PrimaryKeyMixin

try:
    from obstore.store import MemoryStore  # ty: ignore[unresolved-import]

    from brussels.types.file import RemoteFile, RemoteMetadata, RemoteStorage
except ImportError:
    pytest.skip("files optional dependencies not installed", allow_module_level=True)


class NoPrimaryKeyMixinModel(Base):
    __tablename__ = "no_primary_key_mixin_models"

    id: Mapped[int] = mapped_column(primary_key=True)
    file: Mapped[RemoteMetadata | None] = mapped_column(RemoteStorage(store=MemoryStore()), nullable=True)


class PrimaryKeyMixinModel(DataclassBase, PrimaryKeyMixin):
    __tablename__ = "primary_key_mixin_models"

    file: Mapped[RemoteMetadata | None] = mapped_column(RemoteStorage(store=MemoryStore()), nullable=True, default=None)


def test_from_metadata_rejects_models_without_primary_key_mixin() -> None:
    model = NoPrimaryKeyMixinModel(id=1)

    with pytest.raises(TypeError, match=r"PrimaryKeyMixin"):
        RemoteFile.from_metadata(cast("PrimaryKeyMixin", model), NoPrimaryKeyMixinModel.file)


def test_from_metadata_accepts_models_with_primary_key_mixin() -> None:
    model = PrimaryKeyMixinModel()

    remote_file = RemoteFile.from_metadata(model, PrimaryKeyMixinModel.file)

    assert remote_file.field_name == "file"
