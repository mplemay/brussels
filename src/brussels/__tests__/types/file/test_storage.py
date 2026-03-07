from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.dialects.postgresql import dialect as postgres_dialect
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect

try:
    from obstore.store import MemoryStore

    from brussels.types.file import RemoteMetadata, RemoteStorage
except ImportError:
    pytest.skip("files optional dependencies not installed", allow_module_level=True)

if TYPE_CHECKING:
    from brussels.types.file.metadata import RemoteMetadataDict


class ModelWithMetadataField:
    def __init__(self, file: object) -> None:
        self.file = file


def test_build_key_is_deterministic_model_id_and_field() -> None:
    remote_storage = RemoteStorage(store=MemoryStore())

    assert remote_storage.build_key(model_id="abc", field_name="file") == "abc/file"
    assert remote_storage.build_key(model_id=42, field_name="file") == "42/file"


def test_remote_file_compiles_to_jsonb_for_postgres() -> None:
    compiled = RemoteStorage(store=MemoryStore()).compile(dialect=postgres_dialect())
    assert "JSONB" in compiled


def test_remote_file_compiles_to_json_for_sqlite() -> None:
    compiled = RemoteStorage(store=MemoryStore()).compile(dialect=sqlite_dialect())
    assert "JSON" in compiled


def test_build_key_strips_leading_slashes() -> None:
    remote_storage = RemoteStorage(store=MemoryStore())

    assert remote_storage.build_key(model_id="/abc", field_name="/file") == "abc/file"


def test_process_bind_param_none_returns_none() -> None:
    assert RemoteStorage(store=MemoryStore()).process_bind_param(None, None) is None


def test_process_bind_param_serializes_metadata() -> None:
    now = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    metadata = RemoteMetadata(
        key="example/file.txt",
        status="pending",
        created_at=now,
        updated_at=now,
    )

    bound = RemoteStorage(store=MemoryStore()).process_bind_param(metadata, None)

    assert bound is not None
    assert bound["schema"] == 1
    assert bound["key"] == "example/file.txt"
    assert bound["status"] == "pending"


def test_process_bind_param_accepts_dict_payload() -> None:
    raw: RemoteMetadataDict = {
        "schema": 1,
        "key": "example/file.txt",
        "status": "pending",
        "created_at": "2025-01-01T12:00:00+00:00",
        "updated_at": "2025-01-01T12:01:00+00:00",
    }

    bound = RemoteStorage(store=MemoryStore()).process_bind_param(raw, None)

    assert bound is not None
    assert bound["schema"] == 1
    assert bound["key"] == "example/file.txt"


def test_process_bind_param_rejects_invalid_value_type() -> None:
    with pytest.raises(ValueError, match="RemoteStorage RemoteMetadata is invalid"):
        RemoteStorage(store=MemoryStore()).process_bind_param("bad-value", None)  # type: ignore[arg-type]


def test_process_result_value_none_returns_none() -> None:
    assert RemoteStorage(store=MemoryStore()).process_result_value(None, None) is None


def test_process_result_value_returns_typed_metadata() -> None:
    raw = {
        "schema": 1,
        "key": "example/file.txt",
        "status": "complete",
        "size_bytes": 8,
        "content_type": "text/plain",
        "etag": "etag-value",
        "checksum": "checksum-value",
        "version": "v1",
        "created_at": "2025-01-01T12:00:00+00:00",
        "updated_at": "2025-01-01T12:01:00+00:00",
    }

    metadata = RemoteStorage(store=MemoryStore()).process_result_value(raw, None)

    assert isinstance(metadata, RemoteMetadata)
    assert metadata.status == "complete"
    assert metadata.size_bytes == 8


def test_process_result_value_rejects_non_dict_payload() -> None:
    with pytest.raises(TypeError, match="expected dict"):
        RemoteStorage(store=MemoryStore()).process_result_value("bad", None)


def test_process_result_value_rejects_invalid_metadata_payload() -> None:
    raw = {
        "schema": 1,
        "key": "example/file.txt",
        "status": "deleted",
        "created_at": "2025-01-01T12:00:00+00:00",
        "updated_at": "2025-01-01T12:01:00+00:00",
    }

    with pytest.raises(ValueError, match="RemoteStorage RemoteMetadata from database is invalid"):
        RemoteStorage(store=MemoryStore()).process_result_value(raw, None)


def test_get_metadata_coerces_dict_to_remote_metadata() -> None:
    model = ModelWithMetadataField(
        {
            "schema": 1,
            "key": "example/file.txt",
            "status": "pending",
            "created_at": "2025-01-01T12:00:00+00:00",
            "updated_at": "2025-01-01T12:00:00+00:00",
        },
    )

    metadata = RemoteStorage(store=MemoryStore()).get_metadata(model=model, field_name="file")

    assert isinstance(metadata, RemoteMetadata)
    assert isinstance(model.file, RemoteMetadata)
    assert metadata.key == "example/file.txt"


def test_get_metadata_rejects_invalid_field_value_type() -> None:
    model = ModelWithMetadataField(123)

    with pytest.raises(TypeError, match=r"must hold RemoteMetadata \| dict \| None"):
        RemoteStorage(store=MemoryStore()).get_metadata(model=model, field_name="file")
