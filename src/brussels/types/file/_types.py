from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm.attributes import InstrumentedAttribute

if TYPE_CHECKING:
    from collections.abc import AsyncIterable, AsyncIterator, Buffer, Iterable, Iterator
    from pathlib import Path
    from typing import IO

    from brussels.types.file.metadata import RemoteMetadata

    type PutInput = IO[bytes] | Path | bytes | Buffer | Iterator[Buffer] | Iterable[Buffer]
    type PutAsyncInput = (
        IO[bytes]
        | Path
        | bytes
        | Buffer
        | AsyncIterator[Buffer]
        | AsyncIterable[Buffer]
        | Iterator[Buffer]
        | Iterable[Buffer]
    )
else:
    type PutInput = object
    type PutAsyncInput = object

type RemoteMetadataField = InstrumentedAttribute[RemoteMetadata | None]
