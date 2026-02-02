import inspect
import time
from collections.abc import Iterator
from datetime import datetime, timedelta

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Mapped, Session, mapped_column

from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin
from brussels.types import DateTimeUTC


class Widget(DataclassBase, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "timestamp_widgets"

    name: Mapped[str] = mapped_column()


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine("sqlite:///:memory:")
    try:
        yield engine
    finally:
        engine.dispose()


def assert_is_utc(value: datetime) -> None:
    assert value.tzinfo is not None
    assert value.utcoffset() == timedelta(0)


def test_timestamp_column_definitions() -> None:
    created_at = Widget.__table__.c.created_at
    updated_at = Widget.__table__.c.updated_at
    deleted_at = Widget.__table__.c.deleted_at

    assert isinstance(created_at.type, DateTimeUTC)
    assert isinstance(updated_at.type, DateTimeUTC)
    assert isinstance(deleted_at.type, DateTimeUTC)

    assert created_at.default is not None
    assert "now()" in str(created_at.default.arg)

    assert updated_at.default is not None
    assert "now()" in str(updated_at.default.arg)
    assert updated_at.onupdate is not None
    assert "now()" in str(updated_at.onupdate.arg)

    assert deleted_at.nullable is True
    assert deleted_at.default is None or deleted_at.default.arg is None


def test_timestamps_not_in_init_signature() -> None:
    signature = inspect.signature(Widget)
    assert "created_at" not in signature.parameters
    assert "updated_at" not in signature.parameters
    assert "deleted_at" not in signature.parameters


def test_timestamps_populated_on_insert(engine: Engine) -> None:
    DataclassBase.metadata.create_all(engine)

    with Session(engine) as session:
        widget = Widget(name="widget")
        session.add(widget)
        session.commit()
        session.refresh(widget)

        assert widget.created_at is not None
        assert widget.updated_at is not None
        assert_is_utc(widget.created_at)
        assert_is_utc(widget.updated_at)


def test_updated_at_changes_on_update(engine: Engine) -> None:
    DataclassBase.metadata.create_all(engine)

    with Session(engine) as session:
        widget = Widget(name="widget")
        session.add(widget)
        session.commit()
        session.refresh(widget)
        before_update = widget.updated_at

        time.sleep(1.1)
        widget.name = "updated"
        session.commit()
        session.refresh(widget)

        assert widget.updated_at >= before_update
        assert_is_utc(widget.updated_at)


def test_mark_deleted_sets_deleted_at(engine: Engine) -> None:
    DataclassBase.metadata.create_all(engine)

    with Session(engine) as session:
        widget = Widget(name="widget")
        session.add(widget)
        session.commit()
        session.refresh(widget)

        assert widget.deleted_at is None
        widget.mark_deleted()
        session.commit()
        session.refresh(widget)

        assert widget.deleted_at is not None
        assert_is_utc(widget.deleted_at)
