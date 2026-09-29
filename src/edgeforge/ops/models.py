"""Tables in the ``ops`` schema."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Mapped, mapped_column

from edgeforge.core.db import Base, IdMixin, text_enum

SCHEMA = "ops"


class JobStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobRun(IdMixin, Base):
    """Audit record of one execution of a scheduled or triggered job."""

    __tablename__ = "job_run"
    __table_args__ = {"schema": SCHEMA}

    job_name: Mapped[str] = mapped_column(index=True)
    params: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    status: Mapped[JobStatus] = mapped_column(text_enum(JobStatus, "job_status"))
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]
    stats: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    error: Mapped[str | None]
