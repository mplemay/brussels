import sys
from uuid import UUID, uuid4

from sqlalchemy.orm import Mapped, MappedAsDataclass, declarative_mixin, mapped_column

if sys.version_info >= (3, 14):
    from uuid import uuid7 as _pk_uuid
else:
    _pk_uuid = uuid4


@declarative_mixin
class PrimaryKeyMixin(MappedAsDataclass):
    """Mixin that adds a UUID primary key column.

    Inherits from MappedAsDataclass to support standalone usage without Base.
    When used with DataclassBase (which also inherits MappedAsDataclass), the
    duplicate inheritance is safely handled by Python's MRO (Method Resolution Order).

    The id field is excluded from __init__ (init=False) and is generated
    client-side: uuid7() on Python 3.14+, otherwise uuid4(). There is no
    database server_default; non-ORM inserts must supply id explicitly if the
    schema does not define its own DEFAULT.

    Usage:
        class MyModel(DataclassBase, PrimaryKeyMixin, TimestampMixin):
            __tablename__ = "my_table"
            name: Mapped[str]
    """

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default_factory=_pk_uuid,
        init=False,
    )
