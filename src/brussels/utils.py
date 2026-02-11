from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial


def utc(value: datetime, *, raise_on_naive: bool = True) -> datetime:
    if value.tzinfo is None:
        if raise_on_naive:
            msg = "Datetime values must be timezone-aware."
            raise ValueError(msg)
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


now: Callable[[], datetime] = partial(datetime.now, UTC)
