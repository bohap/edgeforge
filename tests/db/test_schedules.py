from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from edgeforge.core.config import Settings
from edgeforge.ingestion.understat import LEAGUE_TASK, current_season, queue_current_season_refresh
from edgeforge.jobs.app import create_app

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("moment", "season"),
    [
        (datetime(2026, 9, 29, tzinfo=UTC), 2026),
        (datetime(2027, 3, 1, tzinfo=UTC), 2026),
        (datetime(2026, 7, 1, tzinfo=UTC), 2026),
        (datetime(2026, 6, 30, 23, 59, tzinfo=UTC), 2025),
    ],
)
def test_current_season_rolls_over_in_july(moment: datetime, season: int) -> None:
    assert current_season(moment) == season


def test_periodic_tasks_are_registered() -> None:
    app = create_app(Settings(_env_file=None))
    schedules = {
        task.task.name: task.cron for task in app.periodic_registry.periodic_tasks.values()
    }

    assert schedules == {
        "ingest:understat_refresh_current_season": "17 */6 * * *",
        "ops:dq_checks": "41 * * * *",
    }


@pytest.mark.db
def test_refresh_queues_each_league_once(committed: sessionmaker[Session]) -> None:
    with committed.begin() as session:
        first = queue_current_season_refresh(session, NOW)
    with committed.begin() as session:
        second = queue_current_season_refresh(session, NOW)

    with committed() as session:
        seasons = (
            session.execute(
                text(
                    "SELECT DISTINCT args->>'season' FROM procrastinate_jobs WHERE task_name = :t"
                ),
                {"t": LEAGUE_TASK},
            )
            .scalars()
            .all()
        )
    assert (first, second) == (6, 0)
    assert seasons == ["2026"]
