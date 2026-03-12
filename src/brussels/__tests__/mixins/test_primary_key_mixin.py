import inspect
from collections.abc import Iterator
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, Table, create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, Session, mapped_column

from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin, UUIDv7PrimaryKeyMixin


class Widget(DataclassBase, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "primary_key_widgets"

    name: Mapped[str] = mapped_column()


class UUIDv7Widget(DataclassBase, UUIDv7PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "primary_key_v7_widgets"

    name: Mapped[str] = mapped_column()


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine("sqlite:///:memory:")
    try:
        yield engine
    finally:
        engine.dispose()


def test_id_column_definition() -> None:
    table = cast("Table", Widget.__table__)
    column = table.c.id

    assert column.primary_key is True

    server_default = column.server_default
    assert server_default is not None
    compiled = cast("Any", server_default).arg.compile(dialect=postgresql.dialect())
    assert "gen_random_uuid" in str(compiled)


def test_id_not_in_init_signature() -> None:
    signature = inspect.signature(Widget)
    assert "id" not in signature.parameters

    widget_cls = cast("Any", Widget)
    with pytest.raises(TypeError):
        widget_cls(id=uuid4(), name="widget")


def test_id_default_factory_generates_uuid_on_flush(engine: Engine) -> None:
    DataclassBase.metadata.create_all(engine)

    with Session(engine) as session:
        widget = Widget(name="widget")
        session.add(widget)
        session.flush()

        assert isinstance(widget.id, UUID)


def test_uuidv7_id_column_definition() -> None:
    table = cast("Table", UUIDv7Widget.__table__)
    column = table.c.id

    assert column.primary_key is True

    insert_default = column.default
    assert insert_default is not None
    compiled_insert_default = cast("Any", insert_default).arg.compile(dialect=postgresql.dialect())
    assert "uuidv7" in str(compiled_insert_default)

    server_default = column.server_default
    assert server_default is not None
    compiled_server_default = cast("Any", server_default).arg.compile(dialect=postgresql.dialect())
    assert "uuidv7" in str(compiled_server_default)


def test_uuidv7_id_not_in_init_signature() -> None:
    signature = inspect.signature(UUIDv7Widget)
    assert "id" not in signature.parameters

    widget_cls = cast("Any", UUIDv7Widget)
    with pytest.raises(TypeError):
        widget_cls(id=uuid4(), name="widget")


def test_uuidv7_id_is_not_populated_before_flush() -> None:
    widget = UUIDv7Widget(name="widget")

    assert widget.id is None
