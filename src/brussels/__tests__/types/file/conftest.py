from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import Engine, create_engine

from brussels.base import DataclassBase

try:
    import brussels.types.file  # noqa: F401
except ImportError:
    pytest.skip("files optional dependencies not installed", allow_module_level=True)

if TYPE_CHECKING:
    from collections.abc import Iterator


class FakeStoreOps:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
        self.put_error: Exception | None = None
        self.delete_error: Exception | None = None
        self.put_response: object = {
            "size_bytes": 5,
            "content_type": "text/plain",
            "etag": "etag-123",
            "checksum": "sum-123",
            "version": "v1",
        }

    def _record(self, name: str, args: tuple[object, ...], kwargs: dict[str, object]) -> None:
        self.calls.append((name, args, kwargs))

    def put(
        self,
        path: str,
        file: object,
        *,
        attributes: object | None = None,
        tags: dict[str, str] | None = None,
        mode: object | None = None,
        use_multipart: bool | None = None,
        chunk_size: int = 5 * 1024 * 1024,
        max_concurrency: int = 12,
    ) -> object:
        self._record(
            "put",
            (path, file),
            {
                "attributes": attributes,
                "tags": tags,
                "mode": mode,
                "use_multipart": use_multipart,
                "chunk_size": chunk_size,
                "max_concurrency": max_concurrency,
            },
        )
        if self.put_error is not None:
            raise self.put_error
        return self.put_response

    async def put_async(
        self,
        path: str,
        file: object,
        *,
        attributes: object | None = None,
        tags: dict[str, str] | None = None,
        mode: object | None = None,
        use_multipart: bool | None = None,
        chunk_size: int = 5 * 1024 * 1024,
        max_concurrency: int = 12,
    ) -> object:
        self._record(
            "put_async",
            (path, file),
            {
                "attributes": attributes,
                "tags": tags,
                "mode": mode,
                "use_multipart": use_multipart,
                "chunk_size": chunk_size,
                "max_concurrency": max_concurrency,
            },
        )
        if self.put_error is not None:
            raise self.put_error
        return self.put_response

    def get(self, path: str, *, options: object | None = None) -> object:
        self._record("get", (path,), {"options": options})
        return b"downloaded-sync"

    async def get_async(self, path: str, *, options: object | None = None) -> object:
        self._record("get_async", (path,), {"options": options})
        return b"downloaded-async"

    def get_range(self, path: str, *, start: int, end: int | None = None, length: int | None = None) -> object:
        self._record("get_range", (path,), {"start": start, "end": end, "length": length})
        return b"range-sync"

    async def get_range_async(
        self,
        path: str,
        *,
        start: int,
        end: int | None = None,
        length: int | None = None,
    ) -> object:
        self._record("get_range_async", (path,), {"start": start, "end": end, "length": length})
        return b"range-async"

    def delete(self, paths: str | tuple[str, ...] | list[str]) -> None:
        self._record("delete", (paths,), {})
        if self.delete_error is not None:
            raise self.delete_error

    async def delete_async(self, paths: str | tuple[str, ...] | list[str]) -> None:
        self._record("delete_async", (paths,), {})
        if self.delete_error is not None:
            raise self.delete_error


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine("sqlite:///:memory:")
    DataclassBase.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()
