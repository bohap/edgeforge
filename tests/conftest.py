import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from edgeforge.core.config import get_settings
from edgeforge.core.db import default_session_factory
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
        # Procrastinate's objects and alembic_version live in public; the test DB is disposable.
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


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


def clear_committed_data(engine: Engine) -> None:
    """Remove rows written by tests that commit (jobs, runs, and everything normalized)."""
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM procrastinate_events"))
        conn.execute(text("DELETE FROM procrastinate_jobs"))
        conn.execute(
            text(
                "TRUNCATE mkt.historical_odds, ops.job_run, ops.dq_issue, core.shot, "
                "core.player_match_stats, core.player, "
                "core.match_team_stats, core.match_result, core.match, core.team_season, "
                "core.team, raw.raw_payload, raw.raw_blob, ref.provider_entity_map, ref.season, "
                "ref.competition, ref.data_provider, ref.sport CASCADE"
            )
        )


@pytest.fixture
def committed(migrated_engine: Engine) -> Iterator[sessionmaker[Session]]:
    """Session factory whose commits are real; the database is cleaned before and after."""
    clear_committed_data(migrated_engine)
    yield sessionmaker(bind=migrated_engine, expire_on_commit=False)
    clear_committed_data(migrated_engine)


@pytest.fixture
def worker_settings(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("EDGEFORGE_DATABASE_URL", database_url)
    get_settings.cache_clear()
    default_session_factory.cache_clear()
    yield
    if default_session_factory.cache_info().currsize:
        bind = default_session_factory().kw["bind"]
        bind.dispose()
    get_settings.cache_clear()
    default_session_factory.cache_clear()
