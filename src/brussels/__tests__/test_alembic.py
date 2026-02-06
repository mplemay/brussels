from importlib import import_module


def test_import_is_safe_without_optional_dependency() -> None:
    import_module("brussels.alembic")
