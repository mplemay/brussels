from uuid import UUID, uuid4

from sqlalchemy import func
from sqlalchemy.orm import Mapped, MappedAsDataclass, declarative_mixin, mapped_column


@declarative_mixin
class PrimaryKeyMixin(MappedAsDataclass):
    """Mixin that adds a UUID primary key column.

    Inherits from MappedAsDataclass to support standalone usage without Base.
    When used with DataclassBase (which also inherits MappedAsDataclass), the
    duplicate inheritance is safely handled by Python's MRO (Method Resolution Order).

    The id field is excluded from __init__ (init=False) and is automatically
    generated both client-side (default_factory=uuid4) and server-side
    (server_default=gen_random_uuid()) for maximum compatibility.

    Usage:
        class MyModel(DataclassBase, PrimaryKeyMixin, TimestampMixin):
            __tablename__ = "my_table"
            name: Mapped[str]

    The UUID is:
    - Generated client-side by default (uuid4)
    - Has server-side fallback (gen_random_uuid() for PostgreSQL)
    """

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default_factory=uuid4,
        server_default=func.gen_random_uuid(),
        init=False,
    )


@declarative_mixin
class UUIDv7PrimaryKeyMixin(MappedAsDataclass):
    """Mixin that adds a PostgreSQL 18+ UUIDv7 primary key column.

    Inherits from MappedAsDataclass to support standalone usage without Base.
    When used with DataclassBase (which also inherits MappedAsDataclass), the
    duplicate inheritance is safely handled by Python's MRO (Method Resolution Order).

    The id field is excluded from __init__ (init=False) and is generated during
    insert using PostgreSQL's uuidv7() function. Because the UUID is database
    generated, it is not guaranteed to be populated until the row is flushed or
    inserted.

    Usage:
        class MyModel(DataclassBase, UUIDv7PrimaryKeyMixin, TimestampMixin):
            __tablename__ = "my_table"
            name: Mapped[str]

    This mixin is only supported on PostgreSQL 18+ because it relies on the
    built-in uuidv7() database function.
    """

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        insert_default=func.uuidv7(),
        server_default=func.uuidv7(),
        init=False,
    )
