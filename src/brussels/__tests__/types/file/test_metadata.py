from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

try:
    from brussels.types.file import RemoteMetadata
except ImportError:
    pytest.skip("files optional dependencies not installed", allow_module_level=True)


def test_to_dict_and_from_dict_round_trip_with_aliases() -> None:
    created_at = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    updated_at = datetime(2025, 1, 1, 12, 1, tzinfo=UTC)
    original = RemoteMetadata(
        key="example/file.txt",
        status="complete",
        size_bytes=8,
        content_type="text/plain",
        created_at=created_at,
        updated_at=updated_at,
    )

    payload = original.to_dict()
    round_tripped = RemoteMetadata.from_dict(payload)

    assert payload["schema"] == 1
    assert payload["key"] == "example/file.txt"
    assert payload["status"] == "complete"
    assert round_tripped == original


def test_schema_alias_is_accepted_and_serialized() -> None:
    data = {
        "schema": 1,
        "key": "alias/file.txt",
        "status": "pending",
        "created_at": "2025-01-01T12:00:00+00:00",
        "updated_at": "2025-01-01T12:00:00+00:00",
    }

    metadata = RemoteMetadata.from_dict(data)

    assert metadata.schema_version == 1
    assert metadata.to_dict()["schema"] == 1


def test_datetime_fields_are_normalized_to_utc() -> None:
    eastern = timezone(timedelta(hours=-5))
    metadata = RemoteMetadata(
        key="example/file.txt",
        status="pending",
        created_at=datetime(2025, 1, 1, 12, 0, tzinfo=eastern),
        updated_at=datetime(2025, 1, 1, 13, 0, tzinfo=eastern),
    )

    assert metadata.created_at.tzinfo == UTC
    assert metadata.updated_at.tzinfo == UTC
    assert metadata.created_at.hour == 17
    assert metadata.updated_at.hour == 18


def test_invalid_status_is_rejected() -> None:
    with pytest.raises(ValidationError, match="status"):
        RemoteMetadata(
            key="example/file.txt",
            status="deleted",  # type: ignore[arg-type]
            created_at=datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
            updated_at=datetime(2025, 1, 1, 12, 0, tzinfo=UTC),
        )


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RemoteMetadata.from_dict(
            {
                "schema": 1,
                "key": "example/file.txt",
                "status": "pending",
                "created_at": "2025-01-01T12:00:00+00:00",
                "updated_at": "2025-01-01T12:00:00+00:00",
                "store_name": "legacy-store",
            },
        )
