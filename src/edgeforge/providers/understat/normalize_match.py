"""Understat match payload → players, shots and player match stats in ``core``."""

import uuid
from dataclasses import dataclass
from functools import partial

from sqlalchemy.orm import Session

from edgeforge.catalog.entity_map import find_internal_id, resolve_or_create
from edgeforge.catalog.reference import ensure_sport
from edgeforge.football.models import Match, Player, PlayerMatchStats, Shot
from edgeforge.football.upsert import upsert_if_changed
from edgeforge.providers.understat.client import Resource, parse_match
from edgeforge.providers.understat.normalize import available_at
from edgeforge.providers.understat.schemas import PARSER_VERSION, MatchPayload, RosterEntry
from edgeforge.raw.blobstore import BlobStore
from edgeforge.raw.models import RawPayload
from edgeforge.raw.service import load_body

SUBSTITUTE_POSITION = "Sub"
GOAL = "Goal"
PENALTY = "Penalty"


class UnknownEntityError(LookupError):
    """The payload refers to a match or team that has not been normalized yet."""


@dataclass(slots=True)
class MatchNormalizeStats:
    players_created: int = 0
    appearances: int = 0
    shots: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "players_created": self.players_created,
            "appearances": self.appearances,
            "shots": self.shots,
        }


def normalize_match_payload(
    session: Session, store: BlobStore, payload: RawPayload
) -> MatchNormalizeStats:
    if payload.resource != Resource.MATCH:
        raise ValueError(f"payload {payload.id} is a {payload.resource!r} payload")
    parsed = parse_match(load_body(store, payload))
    stats = normalize_match(session, payload, parsed)
    payload.parser_version = PARSER_VERSION
    return stats


def normalize_match(
    session: Session, payload: RawPayload, parsed: MatchPayload
) -> MatchNormalizeStats:
    match = session.get(Match, _required_id(session, payload, "match", payload.key))
    if match is None:
        raise UnknownEntityError(f"match {payload.key} has no core.match row")

    stats = MatchNormalizeStats()
    provenance = {
        "provider_id": payload.provider_id,
        "source_raw_id": payload.id,
        "observed_at": payload.fetched_at,
        "available_at": available_at(match.kickoff_at, payload.fetched_at),
    }
    team_for_side = {"h": match.home_team_id, "a": match.away_team_id}
    sport_id = ensure_sport(session).id

    def player_id(external_id: int, name: str) -> uuid.UUID:
        internal, created = resolve_or_create(
            session,
            payload.provider_id,
            "player",
            str(external_id),
            partial(_create_player, session, sport_id, name),
        )
        stats.players_created += created
        return internal

    for side, roster in (("h", parsed.rosters.h), ("a", parsed.rosters.a)):
        for entry in roster.values():
            team_id = _required_id(session, payload, "team", str(entry.team_id))
            if team_id != team_for_side[side]:
                raise ValueError(
                    f"roster entry {entry.id} team {entry.team_id} does not match side {side!r}"
                )
            upsert_if_changed(
                session,
                PlayerMatchStats,
                {"match_id": match.id, "player_id": player_id(entry.player_id, entry.player)},
                _appearance_values(entry, team_id),
                provenance,
            )
            stats.appearances += 1

    for side, shots in (("h", parsed.shots.h), ("a", parsed.shots.a)):
        for shot in shots:
            upsert_if_changed(
                session,
                Shot,
                {"provider_id": payload.provider_id, "external_id": str(shot.id)},
                {
                    "match_id": match.id,
                    "team_id": team_for_side[side],
                    "player_id": player_id(shot.player_id, shot.player),
                    "assister_name": shot.player_assisted,
                    "minute": shot.minute,
                    "x": shot.x,
                    "y": shot.y,
                    "xg": shot.xg,
                    "result": shot.result,
                    "situation": shot.situation,
                    "shot_type": shot.shot_type,
                    "last_action": shot.last_action,
                    "is_goal": shot.result == GOAL,
                    "is_penalty": shot.situation == PENALTY,
                },
                {k: v for k, v in provenance.items() if k != "provider_id"},
            )
            stats.shots += 1

    session.flush()
    return stats


def _required_id(session: Session, payload: RawPayload, entity_type: str, key: str) -> uuid.UUID:
    internal = find_internal_id(session, payload.provider_id, entity_type, key)
    if internal is None:
        raise UnknownEntityError(
            f"Understat {entity_type} {key} is not mapped; normalize its league payload first"
        )
    return internal


def _create_player(session: Session, sport_id: uuid.UUID, name: str) -> uuid.UUID:
    player = Player(sport_id=sport_id, name=name)
    session.add(player)
    session.flush()
    return player.id


def _appearance_values(entry: RosterEntry, team_id: uuid.UUID) -> dict[str, object]:
    return {
        "team_id": team_id,
        "position": entry.position,
        "started": entry.position != SUBSTITUTE_POSITION,
        "minutes": entry.time,
        "goals": entry.goals,
        "own_goals": entry.own_goals,
        "shots": entry.shots,
        "xg": entry.xg,
        "assists": entry.assists,
        "xa": entry.xa,
        "key_passes": entry.key_passes,
        "yellow_cards": entry.yellow_card,
        "red_cards": entry.red_card,
        "xg_chain": entry.xg_chain,
        "xg_buildup": entry.xg_buildup,
    }
