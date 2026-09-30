"""Upserts that only rewrite a row (and its provenance) when its values actually change."""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import ColumnElement, or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from edgeforge.core.db import Base

PROVENANCE_COLUMNS = ("provider_id", "source_raw_id", "observed_at", "available_at")


BATCH_ROWS = 1000


def upsert_many_if_changed(
    session: Session,
    model: type[Base],
    key_columns: Sequence[str],
    value_columns: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    provenance: Mapping[str, Any],
) -> None:
    """Batched ``upsert_if_changed``: one multi-row statement per ``BATCH_ROWS`` rows."""
    refreshed = (*value_columns, *(c for c in provenance if c in PROVENANCE_COLUMNS))
    for start in range(0, len(rows), BATCH_ROWS):
        batch = [{**row, **provenance} for row in rows[start : start + BATCH_ROWS]]
        stmt = insert(model).values(batch)
        changed = [
            getattr(model, column).is_distinct_from(stmt.excluded[column])
            for column in value_columns
        ]
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=[getattr(model, column) for column in key_columns],
                set_={column: stmt.excluded[column] for column in refreshed},
                where=or_(*changed),
            )
        )


def upsert_if_changed(
    session: Session,
    model: type[Base],
    keys: Mapping[str, Any],
    values: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> None:
    """Insert, or update ``values`` + ``provenance`` when any value differs from the stored row."""
    stmt = insert(model).values(**keys, **values, **provenance)
    changed: Sequence[ColumnElement[bool]] = [
        getattr(model, column).is_distinct_from(stmt.excluded[column]) for column in values
    ]
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=[getattr(model, column) for column in keys],
            set_={
                column: stmt.excluded[column]
                for column in (*values, *(c for c in provenance if c in PROVENANCE_COLUMNS))
            },
            where=or_(*changed),
        )
    )
