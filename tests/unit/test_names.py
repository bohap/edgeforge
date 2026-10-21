import pytest

from edgeforge.catalog.names import name_similarity, name_tokens


def test_tokens_drop_accents_punctuation_and_club_words() -> None:
    assert name_tokens("Club Atlético de Madrid") == ["atletico", "de", "madrid"]
    assert name_tokens("Brighton & Hove Albion FC") == ["brighton", "hove", "albion"]
    assert name_tokens("1. FC Köln") == ["1", "koln"]


@pytest.mark.parametrize(
    ("ours", "theirs"),
    [
        ("Leeds", "Leeds United FC"),
        ("Hull", "Hull City AFC"),
        ("Brighton", "Brighton & Hove Albion FC"),
        ("Bournemouth", "AFC Bournemouth"),
        ("Malaga", "Málaga CF"),
        ("Atletico Madrid", "Club Atlético de Madrid"),
        ("Nottingham Forest", "Nottingham Forest FC"),
    ],
)
def test_same_club_scores_one(ours: str, theirs: str) -> None:
    assert name_similarity(ours, theirs) == 1.0
    assert name_similarity(theirs, ours) == 1.0


def test_different_clubs_score_below_one() -> None:
    assert name_similarity("Manchester City", "Manchester United FC") < 0.9
    assert name_similarity("Arsenal", "Everton FC") < 0.5
    assert name_similarity("", "Arsenal") == 0.0
