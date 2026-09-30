from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from edgeforge.backtest.market import compare_with_market
from edgeforge.backtest.walk_forward import run_backtest
from edgeforge.catalog.models import Competition, DataProvider, ProviderKind
from edgeforge.catalog.reference import ensure_provider
from edgeforge.providers.football_data_uk.normalize import normalize_season_payload
from edgeforge.providers.understat.normalize import normalize_league_payload
from edgeforge.raw.blobstore import PostgresBlobStore
from edgeforge.raw.models import RawPayload
from edgeforge.raw.service import record_payload

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _load(
    session: Session, provider: DataProvider, resource: str, key: str, path: str
) -> RawPayload:
    result = record_payload(
        session,
        PostgresBlobStore(session),
        provider_id=provider.id,
        resource=resource,
        key=key,
        url=f"https://example/{key}",
        http_status=200,
        body=(FIXTURES / path).read_bytes(),
        fetched_at=datetime(2026, 9, 30, tzinfo=UTC),
    )
    return session.get_one(RawPayload, result.payload_id)


def test_backtest_is_scored_against_closing_prices(db_session: Session) -> None:
    store = PostgresBlobStore(db_session)
    understat = ensure_provider(db_session, "understat", ProviderKind.STATS)
    odds = ensure_provider(db_session, "football_data_uk", ProviderKind.ODDS)
    normalize_league_payload(
        db_session,
        store,
        _load(db_session, understat, "league", "EPL/2025", "understat/league_EPL_2025.json"),
    )
    normalize_season_payload(
        db_session,
        store,
        _load(db_session, odds, "season_csv", "EPL/2025", "football_data_uk/E0_2526.csv"),
    )
    competition = db_session.scalars(select(Competition.id)).one()
    result = run_backtest(
        db_session,
        competition,
        datetime(2025, 10, 15, tzinfo=UTC),
        datetime(2026, 6, 1, tzinfo=UTC),
    )

    comparisons = {c.market: c for c in compare_with_market(db_session, result)}

    assert set(comparisons) == {"MATCH_RESULT", "TOTAL_GOALS"}
    for comparison in comparisons.values():
        assert comparison.matches == 310
        assert 0.5 < comparison.market_log_loss < 1.1
        assert {(s.price_type, s.min_edge) for s in comparison.simulations} == {
            (t, e) for t in ("opening", "closing") for e in (0.02, 0.05, 0.10)
        }
        for sim in comparison.simulations:
            assert sim.wins <= sim.bets
            assert -sim.bets <= sim.profit
    # The closing line is a strong benchmark: on 2025/26 it beats the baseline model on 1X2.
    result_market = comparisons["MATCH_RESULT"]
    assert result_market.market_log_loss < result_market.model_log_loss
