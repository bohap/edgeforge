import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.orm import Session

from edgeforge.schema import SCHEMAS

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("EDGEFORGE_TEST_DATABASE_URL")
    if not url:
        if os.environ.get("EDGEFORGE_REQUIRE_DB_TESTS") == "1":
            pytest.fail("EDGEFORGE_TEST_DATABASE_URL is required when EDGEFORGE_REQUIRE_DB_TESTS=1")
        pytest.skip("EDGEFORGE_TEST_DATABASE_URL not set")
    return url


def alembic_config(database_url: str) -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    config.attributes["configure_logger"] = False
    return config


def reset_database(engine: Engine) -> None:
    with engine.begin() as conn:
        for schema in SCHEMAS:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.execute(text("DROP TABLE IF EXISTS public.alembic_version"))


@pytest.fixture(scope="session")
def migrated_engine(database_url: str) -> Iterator[Engine]:
    engine = create_engine(database_url)
    reset_database(engine)
    command.upgrade(alembic_config(database_url), "head")
    yield engine
    engine.dispose()


@pytest.fixture
def db_connection(migrated_engine: Engine) -> Iterator[Connection]:
    """A connection inside a transaction that is rolled back after the test."""
    with migrated_engine.connect() as conn:
        transaction = conn.begin()
        yield conn
        transaction.rollback()


@pytest.fixture
def db_session(db_connection: Connection) -> Iterator[Session]:
    session = Session(bind=db_connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
