import dataclasses
import inspect
from datetime import datetime
from typing import cast

import pytest
from sqlalchemy import CheckConstraint, ForeignKey, Table, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from brussels.base import NAMING_CONVENTION, TYPE_ANNOTATION_MAP, Base, DataclassBase
from brussels.types import DateTimeUTC


class BaseWidget(Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column()


class ConventionParent(Base):
    id: Mapped[int] = mapped_column(primary_key=True)


class ConventionChild(Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("convention_parent.id"))
    code: Mapped[str] = mapped_column()

    __table_args__ = (
        UniqueConstraint("code"),
        CheckConstraint("length(code) > 1", name="code_length"),
    )


class DataclassWidget(DataclassBase, kw_only=True, repr=False, eq=False):
    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    name: Mapped[str] = mapped_column()


class OAuthToken(Base):
    id: Mapped[int] = mapped_column(primary_key=True)


class JSON2XML(Base):
    id: Mapped[int] = mapped_column(primary_key=True)


class My2FAThing(Base):
    id: Mapped[int] = mapped_column(primary_key=True)


class ExplicitTable(Base):
    __tablename__ = "explicit_table"

    id: Mapped[int] = mapped_column(primary_key=True)


def test_base_is_not_dataclass() -> None:
    assert dataclasses.is_dataclass(BaseWidget) is False


def test_base_uses_auto_tablename_snake_case() -> None:
    assert BaseWidget.__tablename__ == "base_widget"
    assert DataclassWidget.__tablename__ == "dataclass_widget"


def test_base_type_annotation_map_is_configured() -> None:
    assert {datetime: DateTimeUTC} == TYPE_ANNOTATION_MAP
    assert Base.type_annotation_map is TYPE_ANNOTATION_MAP

    column = BaseWidget.__table__.c.created_at
    assert isinstance(column.type, DateTimeUTC)


def test_base_naming_convention_is_applied_to_constraints() -> None:
    assert Base.metadata.naming_convention == NAMING_CONVENTION

    table = cast("Table", ConventionChild.__table__)
    assert table.primary_key.name == "pk_convention_child"

    unique_constraint = next(constraint for constraint in table.constraints if isinstance(constraint, UniqueConstraint))
    assert unique_constraint.name == "uq_convention_child_code"

    check_constraint = next(constraint for constraint in table.constraints if isinstance(constraint, CheckConstraint))
    assert check_constraint.name == "ck_convention_child_code_length"

    fk_constraint = next(iter(table.foreign_key_constraints))
    assert fk_constraint.name == "fk_convention_child_parent_id_convention_parent"


def test_dataclass_base_kwargs_are_applied() -> None:
    assert dataclasses.is_dataclass(DataclassWidget) is True

    params = DataclassWidget.__dataclass_params__
    assert params is not None
    assert params.kw_only is True
    assert params.repr is False
    assert params.eq is False

    signature = inspect.signature(DataclassWidget)
    assert "name" in signature.parameters
    assert signature.parameters["name"].kind is inspect.Parameter.KEYWORD_ONLY
    assert "id" not in signature.parameters

    with pytest.raises(TypeError):
        DataclassWidget("widget")


def test_dataclass_base_uses_base_metadata() -> None:
    assert DataclassBase.metadata is Base.metadata


def test_base_handles_acronyms_and_digits() -> None:
    assert OAuthToken.__tablename__ == "oauth_token"
    assert JSON2XML.__tablename__ == "json2_xml"
    assert My2FAThing.__tablename__ == "my2_fa_thing"


def test_base_allows_explicit_tablename_override() -> None:
    assert ExplicitTable.__tablename__ == "explicit_table"
    table = cast("Table", ExplicitTable.__table__)
    assert table.name == "explicit_table"
