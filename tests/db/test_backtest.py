from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from edgeforge.backtest.walk_forward import BacktestResult, run_backtest
from edgeforge.catalog.models import Competition, ProviderKind
from edgeforge.catalog.reference import ensure_provider
from edgeforge.providers.understat.normalize import normalize_league_payload
from edgeforge.raw.blobstore import PostgresBlobStore
from edgeforge.raw.models import RawPayload
from edgeforge.raw.service import record_payload

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "understat"
START = datetime(2025, 10, 15, tzinfo=UTC)
END = datetime(2026, 6, 1, tzinfo=UTC)


@pytest.fixture
def backtest(db_session: Session) -> BacktestResult:
    provider = ensure_provider(db_session, "understat", ProviderKind.STATS)
    store = PostgresBlobStore(db_session)
    recorded = record_payload(
        db_session,
        store,
        provider_id=provider.id,
        resource="league",
        key="EPL/2025",
        url="https://understat.com/getLeagueData/EPL/2025",
        http_status=200,
        body=(FIXTURES / "league_EPL_2025.json").read_bytes(),
        fetched_at=datetime(2026, 9, 29, tzinfo=UTC),
    )
    normalize_league_payload(db_session, store, db_session.get_one(RawPayload, recorded.payload_id))
    competition = db_session.scalars(select(Competition.id)).one()
    return run_backtest(db_session, competition, START, END)


def test_every_prediction_uses_only_earlier_data(backtest: BacktestResult) -> None:
    assert backtest.predictions
    for p in backtest.predictions:
        assert p.fitted_as_of <= p.as_of
        assert p.latest_data_kickoff < p.fitted_as_of


def test_each_match_gets_one_prediction_per_market(backtest: BacktestResult) -> None:
    per_market: dict[str, set[object]] = {}
    for p in backtest.predictions:
        per_market.setdefault(p.market, set()).add(p.match_id)

    counts = {market: len(ids) for market, ids in per_market.items()}
    assert counts == {"MATCH_RESULT": 310, "BTTS": 310, "TOTAL_GOALS": 310}
    assert all(abs(sum(p.model) - 1) < 1e-9 for p in backtest.predictions)
    assert all(abs(sum(p.base_rate) - 1) < 1e-9 for p in backtest.predictions)


def test_match_result_beats_base_rates_on_2025_26(backtest: BacktestResult) -> None:
    """Regression guard on recorded data: 1X2 log loss 1.037 vs 1.093 for base rates."""
    scores = {s.market: s for s in backtest.scores()}
    result = scores["MATCH_RESULT"]

    assert result.model_log_loss < result.base_log_loss - 0.03
    assert result.model_rps is not None
    assert result.model_ece < 0.05
