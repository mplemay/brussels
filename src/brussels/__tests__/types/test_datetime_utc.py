from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from sqlalchemy import DateTime
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect

from brussels.types import DateTimeUTC


def test_process_bind_param_returns_none() -> None:
    assert DateTimeUTC().process_bind_param(None, None) is None


@pytest.mark.parametrize("value", [date(2024, 1, 1), object()])
def test_process_bind_param_rejects_non_datetime(value: object) -> None:
    with pytest.raises(TypeError) as excinfo:
        DateTimeUTC().process_bind_param(value, None)  # type: ignore[arg-type]

    message = str(excinfo.value)
    assert "DateTimeUTC requires datetime object" in message
    assert type(value).__name__ in message
    assert "datetime.combine" in message


def test_process_bind_param_converts_naive_to_utc() -> None:
    input_value = datetime(2024, 1, 1, 12, 0, tzinfo=UTC).replace(tzinfo=None)
    output_value = DateTimeUTC().process_bind_param(input_value, None)

    assert output_value is not None
    assert output_value.tzinfo is UTC
    assert output_value == datetime(2024, 1, 1, 12, 0, tzinfo=UTC)


def test_process_bind_param_converts_aware_to_utc() -> None:
    input_value = datetime(2024, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=5)))
    output_value = DateTimeUTC().process_bind_param(input_value, None)

    assert output_value is not None
    assert output_value.tzinfo is UTC
    assert output_value == datetime(2024, 1, 1, 7, 0, tzinfo=UTC)


def test_process_result_value_returns_none() -> None:
    assert DateTimeUTC().process_result_value(None, None) is None


def test_process_result_value_normalizes_naive() -> None:
    input_value = datetime(2024, 1, 1, 12, 0, tzinfo=UTC).replace(tzinfo=None)
    output_value = DateTimeUTC().process_result_value(input_value, None)

    assert output_value is not None
    assert output_value.tzinfo is UTC
    assert output_value == datetime(2024, 1, 1, 12, 0, tzinfo=UTC)


def test_process_result_value_converts_aware_to_utc() -> None:
    input_value = datetime(2024, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=-4)))
    output_value = DateTimeUTC().process_result_value(input_value, None)

    assert output_value is not None
    assert output_value.tzinfo is UTC
    assert output_value == datetime(2024, 1, 1, 16, 0, tzinfo=UTC)


def test_type_decorator_bind_processor() -> None:
    processor = DateTimeUTC().bind_processor(sqlite_dialect())
    assert processor is not None

    input_value = datetime(2024, 1, 1, 12, 0, tzinfo=UTC).replace(tzinfo=None)
    output_value = processor(input_value)

    assert output_value is not None
    assert output_value.tzinfo is UTC
    assert output_value == datetime(2024, 1, 1, 12, 0, tzinfo=UTC)


def test_type_decorator_result_processor() -> None:
    processor = DateTimeUTC().result_processor(sqlite_dialect(), None)
    assert processor is not None

    input_value = datetime(2024, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=3)))
    output_value = processor(input_value)

    assert output_value is not None
    assert output_value.tzinfo is UTC
    assert output_value == datetime(2024, 1, 1, 9, 0, tzinfo=UTC)


def test_static_attributes() -> None:
    assert DateTimeUTC.cache_ok is True
    assert isinstance(DateTimeUTC.impl, DateTime)
    assert DateTimeUTC.impl.timezone is True
