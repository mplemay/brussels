import re
from datetime import datetime
from typing import Any, Final

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass, declared_attr

from brussels.types import DateTimeUTC

NAMING_CONVENTION: Final[dict[str, str]] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

TYPE_ANNOTATION_MAP: Final[dict[type | Any, object]] = {
    datetime: DateTimeUTC,
}

TABLENAME_CAPITAL_RUN_PATTERN: Final = re.compile(r"(?<=[A-Z]{2})([A-Z][a-z])")
TABLENAME_BOUNDARY_PATTERN: Final = re.compile(r"(?<=[a-z0-9])([A-Z])")


class Base(DeclarativeBase):
    __abstract__ = True
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = TYPE_ANNOTATION_MAP

    @declared_attr.directive
    def __tablename__(self) -> str:
        name = TABLENAME_CAPITAL_RUN_PATTERN.sub(r"_\1", self.__name__)
        return TABLENAME_BOUNDARY_PATTERN.sub(r"_\1", name).lower()


class DataclassBase(MappedAsDataclass, Base):
    __abstract__ = True
