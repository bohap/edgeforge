import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from edgeforge.catalog.models import ProviderKind
from edgeforge.catalog.reference import ensure_provider
from edgeforge.features.gateway import played_matches
from edgeforge.football.models import Team
from edgeforge.models.football_goals.model import fit
from edgeforge.providers.understat.normalize import normalize_league_payload
from edgeforge.raw.blobstore import PostgresBlobStore
from edgeforge.raw.models import RawPayload
from edgeforge.raw.service import record_payload

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "understat"
AS_OF = datetime(2026, 1, 1, tzinfo=UTC)


def test_fit_on_real_premier_league_data_is_plausible(db_session: Session) -> None:
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

    matches = played_matches(db_session, AS_OF)
    ratings = fit(matches, AS_OF)

    teams = {name: tid for tid, name in db_session.execute(select(Team.id, Team.name))}
    matrix = ratings.score_matrix(teams["Arsenal"], teams["Burnley"])
    i, j = np.indices(matrix.shape)
    assert 150 < len(matches) < 200
    assert 1.1 < math.exp(ratings.mu) < 1.7  # goals per team per match
    assert 0.0 < ratings.home_advantage < 0.4
    assert matrix[i > j].sum() > 0.5  # a top side at home to a promoted side
    assert -0.2 <= ratings.rho <= 0.2
