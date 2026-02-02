import dataclasses
import inspect
from datetime import datetime
from typing import cast

import pytest
from sqlalchemy import CheckConstraint, ForeignKey, Table, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from brussels.base import NAMING_CONVENTION, TYPE_ANNOTATION_MAP, Base, DataclassBase
from brussels.types import DateTimeUTC


class DataclassWidget(Base):
    __tablename__ = "base_dataclass_widgets"

    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    name: Mapped[str] = mapped_column()


class TypeMapEvent(Base):
    __tablename__ = "base_type_map_events"

    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    created_at: Mapped[datetime] = mapped_column()


class ConventionParent(Base):
    __tablename__ = "base_convention_parents"

    id: Mapped[int] = mapped_column(primary_key=True)


class ConventionChild(Base):
    __tablename__ = "base_convention_children"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("base_convention_parents.id"))
    code: Mapped[str] = mapped_column()

    __table_args__ = (
        UniqueConstraint("code"),
        CheckConstraint("length(code) > 1", name="code_length"),
    )


def test_dataclass_base_kwargs_are_applied() -> None:
    assert DataclassBase.__sa_dataclass_kwargs__ == {"kw_only": True, "repr": True, "eq": True}
    assert dataclasses.is_dataclass(DataclassWidget) is True

    params = DataclassWidget.__dataclass_params__
    assert params is not None
    assert params.kw_only is True
    assert params.repr is True
    assert params.eq is True

    signature = inspect.signature(DataclassWidget)
    assert "name" in signature.parameters
    assert signature.parameters["name"].kind is inspect.Parameter.KEYWORD_ONLY
    assert "id" not in signature.parameters

    with pytest.raises(TypeError):
        DataclassWidget("widget")


def test_type_annotation_map_is_configured() -> None:
    assert {datetime: DateTimeUTC} == TYPE_ANNOTATION_MAP
    assert Base.type_annotation_map is TYPE_ANNOTATION_MAP

    column = TypeMapEvent.__table__.c.created_at
    assert isinstance(column.type, DateTimeUTC)


def test_naming_convention_is_applied_to_constraints() -> None:
    assert Base.metadata.naming_convention == NAMING_CONVENTION

    table = cast("Table", ConventionChild.__table__)
    assert table.primary_key.name == "pk_base_convention_children"

    unique_constraint = next(constraint for constraint in table.constraints if isinstance(constraint, UniqueConstraint))
    assert unique_constraint.name == "uq_base_convention_children_code"

    check_constraint = next(constraint for constraint in table.constraints if isinstance(constraint, CheckConstraint))
    assert check_constraint.name == "ck_base_convention_children_code_length"

    fk_constraint = next(iter(table.foreign_key_constraints))
    assert fk_constraint.name == "fk_base_convention_children_parent_id_base_convention_parents"
