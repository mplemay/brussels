from contextlib import suppress
from importlib import import_module

with suppress(ImportError):
    import_module("alembic_postgresql_enum")
