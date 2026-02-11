from __future__ import annotations

import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import Mapped, Session, mapped_column

from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin

try:
    from obstore.store import MemoryStore  # ty: ignore[unresolved-import]

    from brussels.types.file import RemoteFile, RemoteMetadata, RemoteStorage
except ImportError as exc:
    msg = "This example requires optional dependencies. Install with: pip install 'brussels[file]'"
    raise SystemExit(msg) from exc


class Document(DataclassBase, PrimaryKeyMixin):
    __tablename__ = "documents"

    file: Mapped[RemoteMetadata | None] = mapped_column(
        RemoteStorage(
            store=MemoryStore(),
        ),
        nullable=True,
        default=None,
    )


async def main() -> None:
    engine = create_engine("sqlite:///:memory:")
    DataclassBase.metadata.create_all(engine)

    with Session(engine) as session:
        doc = Document()
        session.add(doc)
        session.flush()  # ensure doc.id exists before upload

        remote_file = RemoteFile.from_metadata(doc, Document.file)
        await remote_file.put_async(
            b"hello world",
            content_type="text/plain",
        )
        if remote_file.metadata is None or remote_file.metadata.key != f"{doc.id}/file":
            msg = "Unexpected key generated for uploaded file."
            raise RuntimeError(msg)

        content = await remote_file.get_async()
        if bytes(content.bytes()) != b"hello world":
            msg = "Unexpected content returned from remote file download."
            raise RuntimeError(msg)

        await remote_file.delete_async()
        session.commit()
        if doc.file is not None:
            msg = "File metadata should be cleared after delete."
            raise RuntimeError(msg)


if __name__ == "__main__":
    asyncio.run(main())
