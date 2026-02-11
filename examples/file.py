from __future__ import annotations

import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import Mapped, Session, mapped_column

from brussels.base import Base

try:
    from obstore.store import MemoryStore  # ty: ignore[unresolved-import]

    from brussels.types.file import RemoteFile, RemoteStorage
except ImportError as exc:
    msg = "This example requires optional dependencies. Install with: pip install 'brussels[files]'"
    raise SystemExit(msg) from exc


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    file: Mapped[RemoteFile | None] = mapped_column(
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

        uploaded = await doc.upload(  # type: ignore[attr-defined]
            data=b"hello world",
            filename="hello.txt",
            content_type="text/plain",
        )
        if uploaded.key != f"{doc.id}/file":
            msg = "Unexpected key generated for uploaded file."
            raise RuntimeError(msg)

        content = await doc.download()  # type: ignore[attr-defined]
        if content != b"hello world":
            msg = "Unexpected content returned from remote file download."
            raise RuntimeError(msg)

        await doc.delete()  # type: ignore[attr-defined]
        session.commit()
        if doc.file is not None:
            msg = "File metadata should be cleared after delete."
            raise RuntimeError(msg)


if __name__ == "__main__":
    asyncio.run(main())
