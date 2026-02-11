from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from brussels.utils import now, utc


def test_utc_converts_aware_datetime_to_utc() -> None:
    value = datetime(2024, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=5)))

    result = utc(value)

    assert result.tzinfo is UTC
    assert result == datetime(2024, 1, 1, 7, 0, tzinfo=UTC)


def test_utc_raises_for_naive_datetime_by_default() -> None:
    value = datetime(2024, 1, 1, 12, 0, tzinfo=UTC).replace(tzinfo=None)

    with pytest.raises(ValueError, match="timezone-aware"):
        utc(value)


def test_utc_coerces_naive_datetime_when_configured() -> None:
    value = datetime(2024, 1, 1, 12, 0, tzinfo=UTC).replace(tzinfo=None)

    result = utc(value, raise_on_naive=False)

    assert result.tzinfo is UTC
    assert result == datetime(2024, 1, 1, 12, 0, tzinfo=UTC)


def test_now_returns_utc_aware_datetime() -> None:
    result = now()

    assert result.tzinfo is UTC
