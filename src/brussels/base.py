from collections.abc import Callable
from datetime import datetime
from typing import Any, ClassVar, Final

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass
from sqlalchemy.orm.decl_api import _NoArg

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


class Base(DeclarativeBase):
    __abstract__ = True
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = TYPE_ANNOTATION_MAP


class DataclassBase(MappedAsDataclass, Base):
    __abstract__ = True
    __sa_dataclass_kwargs__: ClassVar[dict[str, bool]] = {"kw_only": True, "repr": True, "eq": True}

    def __init_subclass__(  # noqa: PLR0913
        cls,
        *,
        init: _NoArg | bool = _NoArg.NO_ARG,
        repr: _NoArg | bool = _NoArg.NO_ARG,  # noqa: A002
        eq: _NoArg | bool = _NoArg.NO_ARG,
        order: _NoArg | bool = _NoArg.NO_ARG,
        unsafe_hash: _NoArg | bool = _NoArg.NO_ARG,
        match_args: _NoArg | bool = _NoArg.NO_ARG,
        kw_only: _NoArg | bool = _NoArg.NO_ARG,
        dataclass_callable: _NoArg | Callable[..., type[Any]] = _NoArg.NO_ARG,
        **kwargs: object,
    ) -> None:
        dataclass_kwargs = cls.__sa_dataclass_kwargs__
        repr_value = repr if repr is not _NoArg.NO_ARG else dataclass_kwargs["repr"]
        eq_value = eq if eq is not _NoArg.NO_ARG else dataclass_kwargs["eq"]
        kw_only_value = kw_only if kw_only is not _NoArg.NO_ARG else dataclass_kwargs["kw_only"]
        super().__init_subclass__(
            init=init,
            repr=repr_value,
            eq=eq_value,
            order=order,
            unsafe_hash=unsafe_hash,
            match_args=match_args,
            kw_only=kw_only_value,
            dataclass_callable=dataclass_callable,
            **kwargs,
        )
