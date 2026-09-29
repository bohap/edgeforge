"""Database foundation: declarative base, shared column mixins, engine and session factories."""

import uuid
from datetime import datetime
from enum import StrEnum
from functools import lru_cache
from typing import Any

from sqlalchemy import DateTime, Engine, Enum, MetaData, Uuid, create_engine, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from edgeforge.core.config import Settings, get_settings
from edgeforge.core.ids import new_id

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {
        datetime: DateTime(timezone=True),
        uuid.UUID: Uuid(),
        dict[str, Any]: JSONB(),
    }


def text_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """Store enum values as text with a CHECK constraint instead of a native Postgres enum type."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda members: [m.value for m in members],
    )


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


def create_db_engine(settings: Settings, **kwargs: Any) -> Engine:
    return create_engine(settings.database_url, pool_pre_ping=True, **kwargs)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@lru_cache(maxsize=1)
def default_session_factory() -> sessionmaker[Session]:
    """Process-wide session factory for the configured database (workers, API)."""
    return create_session_factory(create_db_engine(get_settings()))
