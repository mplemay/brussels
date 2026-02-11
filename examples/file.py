from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from sqlalchemy import create_engine
from sqlalchemy.orm import Mapped, Session, mapped_column

from brussels.base import Base

try:
    from obstore.store import MemoryStore  # ty: ignore[unresolved-import]

    from brussels.types.file import RemoteFile, RemoteMetadata, RemoteStorage
except ImportError as exc:
    msg = "This example requires optional dependencies. Install with: pip install 'brussels[file]'"
    raise SystemExit(msg) from exc

if TYPE_CHECKING:
    from brussels.types.file.remote_file import SupportsRemoteFileModel


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    file: Mapped[RemoteMetadata | None] = mapped_column(
        RemoteStorage(
            store=MemoryStore(),
        ),
        nullable=True,
    )


async def main() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        doc = Document()
        session.add(doc)
        session.flush()  # ensure doc.id exists before upload

        remote_file = RemoteFile.from_metadata(cast("SupportsRemoteFileModel", doc), Document.file)
        uploaded = await remote_file.upload(
            data=b"hello world",
            content_type="text/plain",
        )
        if uploaded.key != f"{doc.id}/file":
            msg = "Unexpected key generated for uploaded file."
            raise RuntimeError(msg)

        content = await remote_file.download()
        if content != b"hello world":
            msg = "Unexpected content returned from remote file download."
            raise RuntimeError(msg)

        await remote_file.delete()
        session.commit()
        if doc.file is not None:
            msg = "File metadata should be cleared after delete."
            raise RuntimeError(msg)


if __name__ == "__main__":
    asyncio.run(main())
