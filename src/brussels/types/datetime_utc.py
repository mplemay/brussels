from datetime import datetime
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator

from brussels.utils import utc


class DateTimeUTC(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, _dialect: Any) -> datetime | None:  # ty: ignore[invalid-method-override]  # noqa: ANN401
        if value is None:
            return None
        if not isinstance(value, datetime):
            type_name = type(value).__name__
            msg = (
                f"DateTimeUTC requires datetime object, got {type_name}. "
                f"If using a date, convert to datetime first: "
                f"datetime.combine(your_date, time())"
            )
            raise TypeError(msg)
        return utc(value, raise_on_naive=False)

    def process_result_value(self, value: Any, _dialect: Any) -> datetime | None:  # ty: ignore[invalid-method-override]  # noqa: ANN401
        if value is None:
            return None
        return utc(value, raise_on_naive=False)
