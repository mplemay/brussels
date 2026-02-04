from uuid import UUID, uuid4

from sqlalchemy import Table, event, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, MappedAsDataclass, Session, declarative_mixin, mapped_column
from sqlalchemy.schema import DefaultClause


@declarative_mixin
class PrimaryKeyMixin(MappedAsDataclass):
    """Mixin that adds a UUID primary key column.

    Inherits from MappedAsDataclass to support standalone usage without Base.
    When used with DataclassBase (which also inherits MappedAsDataclass), the
    duplicate inheritance is safely handled by Python's MRO (Method Resolution Order).

    The id field is excluded from __init__ (init=False) and is automatically
    generated server-side (uuidv7()) for PostgreSQL and client-side
    (uuid4 on insert) for SQLite.

    Usage:
        class MyModel(DataclassBase, PrimaryKeyMixin, TimestampMixin):
            __tablename__ = "my_table"
            name: Mapped[str]

    The UUID is:
    - Generated server-side by default (uuidv7() for PostgreSQL)
    - Generated client-side on insert (uuid4 for SQLite)
    - Indexed and unique for efficient lookups
    """

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        server_default=text("uuidv7()"),
        index=True,
        unique=True,
        init=False,
    )


_UUIDV7_SERVER_DEFAULT_KEY = "uuidv7_server_default"


@event.listens_for(Session, "before_flush")
def _assign_sqlite_uuid(
    session: Session,
    _flush_context: object,
    _instances: object,
) -> None:
    bind = session.get_bind()
    if bind is None or bind.dialect.name != "sqlite":
        return
    for instance in session.new:
        if isinstance(instance, PrimaryKeyMixin) and instance.id is None:
            instance.id = uuid4()


@event.listens_for(Table, "before_create")
def _strip_uuidv7_server_default(table: Table, connection: Connection, **_kwargs: object) -> None:
    if connection.dialect.name == "postgresql":
        return

    column = table.columns.get("id")
    if column is None or column.server_default is None:
        return

    if not isinstance(column.server_default, DefaultClause):
        return
    if str(column.server_default.arg) != "uuidv7()":
        return

    column.info[_UUIDV7_SERVER_DEFAULT_KEY] = column.server_default
    column.server_default = None


@event.listens_for(Table, "after_create")
def _restore_uuidv7_server_default(table: Table, connection: Connection, **_kwargs: object) -> None:
    if connection.dialect.name == "postgresql":
        return

    column = table.columns.get("id")
    if column is None:
        return

    server_default = column.info.pop(_UUIDV7_SERVER_DEFAULT_KEY, None)
    if server_default is None:
        return

    column.server_default = server_default
