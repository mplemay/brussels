from __future__ import annotations

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import dialect as postgres_dialect
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect

from brussels.types import Json


def test_sqlite_variant_is_json() -> None:
    sqlite_type = Json.with_variant(JSON(), "sqlite")
    assert isinstance(sqlite_type, JSON)


def test_postgres_variant_is_jsonb() -> None:
    compiled = Json.compile(dialect=postgres_dialect())
    assert "JSONB" in compiled


def test_sqlite_compile_uses_json() -> None:
    compiled = Json.compile(dialect=sqlite_dialect())
    assert "JSON" in compiled
