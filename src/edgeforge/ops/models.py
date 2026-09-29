"""Tables in the ``ops`` schema."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Index, text
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


class Severity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


class DqIssue(IdMixin, Base):
    """A data-quality problem found by a check. At most one open issue per check and entity;
    it is resolved automatically when a later run no longer finds the problem."""

    __tablename__ = "dq_issue"
    __table_args__ = (
        Index(
            "uq_dq_issue_open",
            "check_code",
            "entity_type",
            "entity_id",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
        ),
        {"schema": SCHEMA},
    )

    check_code: Mapped[str]
    severity: Mapped[Severity] = mapped_column(text_enum(Severity, "dq_severity"))
    entity_type: Mapped[str]
    entity_id: Mapped[uuid.UUID]
    details: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    first_seen_at: Mapped[datetime]
    last_seen_at: Mapped[datetime]
    resolved_at: Mapped[datetime | None]
