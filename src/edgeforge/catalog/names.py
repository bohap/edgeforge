"""Team-name similarity across providers ("Brighton" vs "Brighton & Hove Albion FC")."""

import unicodedata
from difflib import SequenceMatcher

# Club-type words that providers add or drop freely.
NOISE_WORDS = frozenset({"fc", "afc", "cf", "sc", "ac", "club", "the"})


def name_tokens(name: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    words = "".join(ch if ch.isalnum() else " " for ch in plain).split()
    return [w for w in words if w not in NOISE_WORDS]


def name_similarity(a: str, b: str) -> float:
    """1.0 when every word of one name starts a word of the other ("Leeds" and "Leeds United
    FC", "Hull" and "Hull City AFC"); otherwise the character similarity of the cleaned names,
    between 0 and 1."""
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return 0.0
    if _covered(ta, tb) or _covered(tb, ta):
        return 1.0
    return SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()


def _covered(short: list[str], long: list[str]) -> bool:
    return all(any(word.startswith(part) for word in long) for part in short)
