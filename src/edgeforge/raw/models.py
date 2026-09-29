"""Tables in the ``raw`` schema."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from edgeforge.core.db import Base, IdMixin

SCHEMA = "raw"


class RawBlob(Base):
    """Content-addressed, gzip-compressed payload body. Key: ``sha256/<hex digest>``."""

    __tablename__ = "raw_blob"
    __table_args__ = {"schema": SCHEMA}

    blob_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    body: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class RawPayload(IdMixin, Base):
    """One fetch of one provider resource. Never updated except to mark it superseded."""

    __tablename__ = "raw_payload"
    __table_args__ = (
        Index(
            "ix_raw_payload_provider_resource_key", "provider_id", "resource", "key", "fetched_at"
        ),
        {"schema": SCHEMA},
    )

    provider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ref.data_provider.id"))
    resource: Mapped[str]
    key: Mapped[str]
    url: Mapped[str]
    http_status: Mapped[int]
    fetched_at: Mapped[datetime]
    content_hash: Mapped[str] = mapped_column(String(64))
    blob_key: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.raw_blob.blob_key"))
    bytes: Mapped[int]
    parser_version: Mapped[str | None]
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA}.raw_payload.id"))
