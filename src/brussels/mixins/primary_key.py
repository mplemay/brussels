from uuid import UUID, uuid4

from sqlalchemy import func
from sqlalchemy.orm import Mapped, MappedAsDataclass, declarative_mixin, mapped_column


@declarative_mixin
class PrimaryKeyMixin(MappedAsDataclass):
    """Mixin that adds a UUID primary key column.

    Inherits from MappedAsDataclass to support standalone usage without Base.
    When used with Base (which also inherits MappedAsDataclass), the duplicate
    inheritance is safely handled by Python's MRO (Method Resolution Order).

    The id field is excluded from __init__ (init=False) and is automatically
    generated both client-side (default_factory=uuid4) and server-side
    (server_default=gen_random_uuid()) for maximum compatibility.

    Usage:
        class MyModel(Base, PrimaryKeyMixin, TimestampMixin):
            __tablename__ = "my_table"
            name: Mapped[str]

    The UUID is:
    - Generated client-side by default (uuid4)
    - Has server-side fallback (gen_random_uuid() for PostgreSQL)
    - Indexed and unique for efficient lookups
    """

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default_factory=uuid4,
        server_default=func.gen_random_uuid(),
        index=True,
        unique=True,
        init=False,
    )
