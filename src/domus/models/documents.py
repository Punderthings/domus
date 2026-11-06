"""Content-addressed blobs, documents, and attachments (data-storage-backup.md 2.3, 3).

v0.1 creates the tables; the upload endpoint and blob store come in a later step.
"""

from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from domus.models.base import Base, EntityMixin, IdStr, utcnow


class Blob(Base):
    __tablename__ = "blob"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    size: Mapped[int]
    mime_type: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Document(EntityMixin, Base):
    """A stored file or an external link (for example a manual URL)."""

    __tablename__ = "document"

    property_id: Mapped[str] = mapped_column(IdStr, ForeignKey("property.id"), index=True)
    blob_sha256: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("blob.sha256"), index=True, default=None
    )
    url: Mapped[str | None] = mapped_column(String(2048), default=None)
    kind: Mapped[str] = mapped_column(String(32), default="other")
    title: Mapped[str | None] = mapped_column(String(300), default=None)
    original_filename: Mapped[str | None] = mapped_column(String(300), default=None)
    captured_at: Mapped[datetime | None] = mapped_column(default=None)
    sensitivity: Mapped[str] = mapped_column(String(16), default="resident")


class Attachment(EntityMixin, Base):
    """Links one document to any record (asset, product, task, ...)."""

    __tablename__ = "attachment"

    document_id: Mapped[str] = mapped_column(IdStr, ForeignKey("document.id"), index=True)
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(IdStr, index=True)
    role: Mapped[str | None] = mapped_column(String(32), default=None)
    sort: Mapped[int] = mapped_column(default=0)
