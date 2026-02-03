import inspect
from collections.abc import Iterator
from typing import cast

import pytest
from sqlalchemy import Engine, ForeignKey, Integer, Table, create_engine
from sqlalchemy.ext.orderinglist import ordering_list
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from brussels.base import DataclassBase
from brussels.mixins import OrderedMixin, PrimaryKeyMixin


class OrderedList(DataclassBase, PrimaryKeyMixin):
    __tablename__ = "ordered_lists"

    name: Mapped[str] = mapped_column()
    items: Mapped[list["OrderedItem"]] = relationship(
        "OrderedItem",
        order_by="OrderedItem.position",
        collection_class=ordering_list("position"),
        back_populates="list",
        default_factory=list,
    )


class OrderedItem(DataclassBase, PrimaryKeyMixin, OrderedMixin):
    __tablename__ = "ordered_items"

    list_id: Mapped[int] = mapped_column(ForeignKey("ordered_lists.id"), init=False)
    list: Mapped[OrderedList] = relationship("OrderedList", back_populates="items", init=False)
    name: Mapped[str] = mapped_column()


def test_position_column_definition() -> None:
    table = cast("Table", OrderedItem.__table__)
    column = table.c.position

    assert isinstance(column.type, Integer)
    assert column.nullable is False
    assert any("position" in index.columns for index in table.indexes)


def test_position_not_in_init_signature() -> None:
    signature = inspect.signature(OrderedItem)
    assert "position" not in signature.parameters


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine("sqlite:///:memory:")
    try:
        yield engine
    finally:
        engine.dispose()


def test_ordering_list_populates_positions(engine: Engine) -> None:
    DataclassBase.metadata.create_all(engine)

    with Session(engine) as session:
        ordered_list = OrderedList(name="list")
        ordered_list.items.append(OrderedItem(name="first"))
        ordered_list.items.append(OrderedItem(name="second"))
        ordered_list.items.append(OrderedItem(name="third"))

        session.add(ordered_list)
        session.flush()

        assert [item.position for item in ordered_list.items] == [0, 1, 2]
