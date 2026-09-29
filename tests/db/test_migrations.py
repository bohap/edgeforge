import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import CheckConstraint, Engine, inspect, text

from edgeforge.schema import SCHEMAS, metadata
from tests.conftest import alembic_config

pytestmark = pytest.mark.db


def _include_name(name: str | None, type_: str, parent_names: object) -> bool:
    return name in SCHEMAS if type_ == "schema" else True


def test_models_match_migrations(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as conn:
        context = MigrationContext.configure(
            conn,
            opts={
                "include_schemas": True,
                "include_name": _include_name,
                "compare_type": True,
                "compare_server_default": True,
            },
        )
        diff = compare_metadata(context, metadata)

    assert diff == []


def test_check_constraints_match_models(migrated_engine: Engine) -> None:
    expected = {
        constraint.name
        for table in metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    with migrated_engine.connect() as conn:
        actual = set(
            conn.execute(
                text(
                    "SELECT conname FROM pg_constraint c "
                    "JOIN pg_namespace n ON n.oid = c.connamespace "
                    "WHERE c.contype = 'c' AND n.nspname = ANY(:schemas)"
                ),
                {"schemas": list(SCHEMAS)},
            ).scalars()
        )

    assert actual == expected


def test_downgrade_to_base_and_upgrade_again(migrated_engine: Engine, database_url: str) -> None:
    config = alembic_config(database_url)

    command.downgrade(config, "base")
    remaining = set(inspect(migrated_engine).get_schema_names()) & set(SCHEMAS)
    public_leftovers = [
        t
        for t in inspect(migrated_engine).get_table_names(schema="public")
        if t != "alembic_version"
    ]
    command.upgrade(config, "head")

    assert remaining == set()
    assert public_leftovers == []
    assert {"sport", "competition", "season"} <= set(
        inspect(migrated_engine).get_table_names(schema="ref")
    )
