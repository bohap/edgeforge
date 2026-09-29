from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from edgeforge.catalog.models import DataProvider, ProviderKind
from edgeforge.catalog.reference import ensure_provider
from edgeforge.cli import main as cli_main
from edgeforge.football.models import MatchResult, PlayerMatchStats
from edgeforge.ops.models import DqIssue
from edgeforge.providers.understat.normalize import normalize_league_payload
from edgeforge.providers.understat.normalize_match import normalize_match_payload
from edgeforge.quality.checks import CHECKS, run_checks
from edgeforge.raw.blobstore import PostgresBlobStore
from edgeforge.raw.models import RawPayload
from edgeforge.raw.service import record_payload

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "understat"
FETCHED = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
NOW = datetime(2026, 9, 29, 18, 0, tzinfo=UTC)


def _ingest(session: Session, provider: DataProvider, resource: str, key: str, name: str) -> None:
    store = PostgresBlobStore(session)
    result = record_payload(
        session,
        store,
        provider_id=provider.id,
        resource=resource,
        key=key,
        url=f"https://understat.com/{resource}/{key}",
        http_status=200,
        body=(FIXTURES / name).read_bytes(),
        fetched_at=FETCHED,
    )
    payload = session.get_one(RawPayload, result.payload_id)
    normalize = normalize_league_payload if resource == "league" else normalize_match_payload
    normalize(session, store, payload)


@pytest.fixture
def season_with_one_detailed_match(db_session: Session) -> Session:
    provider = ensure_provider(db_session, "understat", ProviderKind.STATS)
    _ingest(db_session, provider, "league", "EPL/2025", "league_EPL_2025.json")
    _ingest(db_session, provider, "match", "28778", "match_28778.json")
    return db_session


def _open(session: Session, code: str) -> list[DqIssue]:
    return list(
        session.scalars(
            select(DqIssue).where(DqIssue.check_code == code, DqIssue.resolved_at.is_(None))
        )
    )


def test_clean_season_only_reports_matches_without_details(
    season_with_one_detailed_match: Session,
) -> None:
    summary = run_checks(season_with_one_detailed_match, NOW)

    assert summary == {check.code: 0 for check in CHECKS} | {"details_missing": 379}


def test_rerun_refreshes_instead_of_duplicating(season_with_one_detailed_match: Session) -> None:
    session = season_with_one_detailed_match
    run_checks(session, NOW)
    later = NOW + timedelta(hours=1)

    run_checks(session, later)

    issues = _open(session, "details_missing")
    total = session.scalar(select(func.count()).select_from(DqIssue))
    assert len(issues) == 379
    assert total == 379
    assert {i.first_seen_at for i in issues} == {NOW}
    assert {i.last_seen_at for i in issues} == {later}


def test_missing_result_opens_an_error_and_resolves_when_fixed(
    season_with_one_detailed_match: Session,
) -> None:
    session = season_with_one_detailed_match
    result = session.scalars(select(MatchResult).limit(1)).one()
    snapshot = {c.name: getattr(result, c.name) for c in MatchResult.__table__.columns}
    session.execute(delete(MatchResult).where(MatchResult.match_id == result.match_id))

    run_checks(session, NOW)
    opened = _open(session, "result_missing")
    session.add(MatchResult(**snapshot))
    session.flush()
    run_checks(session, NOW + timedelta(hours=1))

    assert [i.entity_id for i in opened] == [result.match_id]
    assert opened[0].severity.value == "error"
    assert _open(session, "result_missing") == []
    session.refresh(opened[0])
    assert opened[0].resolved_at == NOW + timedelta(hours=1)


def test_goal_mismatch_is_reported_with_team_details(
    season_with_one_detailed_match: Session,
) -> None:
    session = season_with_one_detailed_match
    scorer = session.scalars(
        select(PlayerMatchStats).where(PlayerMatchStats.goals > 0).limit(1)
    ).one()
    scorer.goals += 1
    session.flush()

    run_checks(session, NOW)

    [issue] = _open(session, "goals_mismatch")
    [team] = issue.details["teams"]
    assert issue.entity_id == scorer.match_id
    assert team["team_goals"] + 1 == team["from_players"]


def test_scheduled_matches_become_overdue_after_36_hours(db_session: Session) -> None:
    provider = ensure_provider(db_session, "understat", ProviderKind.STATS)
    _ingest(db_session, provider, "league", "EPL/2026", "league_EPL_2026.json")

    before = run_checks(db_session, datetime(2026, 10, 10, 12, 0, tzinfo=UTC))
    after = run_checks(db_session, datetime(2026, 10, 12, 0, 0, tzinfo=UTC))

    assert before["result_overdue"] == 0
    assert after["result_overdue"] > 0


def test_dq_command_exit_code(committed: sessionmaker[Session], worker_settings: None) -> None:
    assert cli_main(["dq"]) == 0
