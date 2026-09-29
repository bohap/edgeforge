from datetime import date

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from edgeforge.catalog.models import (
    Competition,
    CompetitionKind,
    DataProvider,
    MappingMethod,
    ProviderEntityMap,
    ProviderKind,
    Season,
    Sport,
)
from edgeforge.core.ids import new_id

pytestmark = pytest.mark.db


def _football(session: Session) -> Sport:
    sport = Sport(code="football", name="Football")
    session.add(sport)
    session.flush()
    return sport


def _epl(session: Session) -> Competition:
    competition = Competition(
        sport_id=_football(session).id,
        code="EPL",
        name="Premier League",
        country="England",
        tier=1,
        kind=CompetitionKind.LEAGUE,
    )
    session.add(competition)
    session.flush()
    return competition


def test_round_trip_sport_competition_season(db_session: Session) -> None:
    competition = _epl(db_session)
    db_session.add(
        Season(
            competition_id=competition.id,
            label="2026/27",
            start_date=date(2026, 8, 21),
            end_date=date(2027, 5, 30),
            is_current=True,
        )
    )
    db_session.flush()
    db_session.expire_all()

    season = db_session.scalars(select(Season)).one()
    stored = db_session.get(Competition, competition.id)

    assert season.label == "2026/27"
    assert season.id.version == 7
    assert stored is not None
    assert stored.kind is CompetitionKind.LEAGUE
    assert stored.enabled is False
    assert stored.created_at.tzinfo is not None


def test_season_end_must_not_precede_start(db_session: Session) -> None:
    competition = _epl(db_session)
    db_session.add(
        Season(
            competition_id=competition.id,
            label="bad",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 7, 1),
        )
    )

    with pytest.raises(IntegrityError, match="ck_season_dates_ordered"):
        db_session.flush()


def test_competition_kind_rejects_unknown_value(db_session: Session) -> None:
    sport = _football(db_session)

    with pytest.raises(IntegrityError, match="ck_competition_competition_kind"):
        db_session.execute(
            text(
                "INSERT INTO ref.competition (id, sport_id, code, name, kind) "
                "VALUES (:id, :sport_id, 'X', 'X', 'friendly')"
            ),
            {"id": new_id(), "sport_id": sport.id},
        )


def test_external_id_maps_to_one_internal_entity_per_provider(db_session: Session) -> None:
    provider = DataProvider(code="understat", kind=ProviderKind.STATS)
    db_session.add(provider)
    db_session.flush()

    def mapping() -> ProviderEntityMap:
        return ProviderEntityMap(
            provider_id=provider.id,
            entity_type="team",
            external_id="89",
            internal_id=new_id(),
            method=MappingMethod.AUTO,
            confidence=1.0,
        )

    db_session.add(mapping())
    db_session.flush()
    db_session.add(mapping())

    with pytest.raises(IntegrityError, match="uq_provider_entity_map"):
        db_session.flush()


def test_provider_config_defaults_to_empty_object(db_session: Session) -> None:
    provider = DataProvider(code="football_data_uk", kind=ProviderKind.ODDS)
    db_session.add(provider)
    db_session.flush()
    db_session.refresh(provider)

    assert provider.config == {}
