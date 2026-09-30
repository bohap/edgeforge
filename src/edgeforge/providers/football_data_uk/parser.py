"""Parse football-data.co.uk season CSVs.

Dates are day-first; times are UK local (Europe/London) and converted to UTC. Empty cells are
``None``. Only the bookmakers and markets we use are read; unknown columns are ignored because
the files gain and lose bookmakers over the years.
"""

import csv
import io
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

UK = ZoneInfo("Europe/London")

# Our bookmaker name -> (1X2 opening prefix, 1X2 closing prefix, totals opening, totals closing)
BOOKMAKERS: dict[str, tuple[str, str, str, str]] = {
    "bet365": ("B365", "B365C", "B365", "B365C"),
    "pinnacle": ("PS", "PSC", "P", "PC"),
    "market_average": ("Avg", "AvgC", "Avg", "AvgC"),
    "market_max": ("Max", "MaxC", "Max", "MaxC"),
    "betfair_exchange": ("BFE", "BFEC", "BFE", "BFEC"),
}
RESULT_OUTCOMES = {"HOME": "H", "DRAW": "D", "AWAY": "A"}
TOTALS_OUTCOMES = {"OVER": ">2.5", "UNDER": "<2.5"}
TOTALS_PARAMS = "line=2.5"


@dataclass(frozen=True, slots=True)
class OddsQuote:
    bookmaker: str
    market_code: str
    params_key: str
    outcome: str
    opening: float | None
    closing: float | None


@dataclass(frozen=True, slots=True)
class SeasonRow:
    match_date: date
    kickoff_at: datetime | None  # UTC; None when the file has no time
    home_team: str
    away_team: str
    home_goals: int | None
    away_goals: int | None
    quotes: list[OddsQuote] = field(default_factory=list)


def parse_season_csv(body: bytes) -> list[SeasonRow]:
    text = body.decode("utf-8-sig", errors="replace")
    rows = []
    for raw in csv.DictReader(io.StringIO(text)):
        if not raw.get("HomeTeam") or not raw.get("Date"):
            continue  # trailing blank lines
        match_date = _parse_date(raw["Date"])
        rows.append(
            SeasonRow(
                match_date=match_date,
                kickoff_at=_kickoff(match_date, raw.get("Time")),
                home_team=raw["HomeTeam"].strip(),
                away_team=raw["AwayTeam"].strip(),
                home_goals=_int(raw.get("FTHG")),
                away_goals=_int(raw.get("FTAG")),
                quotes=_quotes(raw),
            )
        )
    return rows


def _quotes(raw: dict[str, str]) -> list[OddsQuote]:
    quotes: list[OddsQuote] = []
    for book, (open_1x2, close_1x2, open_tot, close_tot) in BOOKMAKERS.items():
        for outcome, suffix in RESULT_OUTCOMES.items():
            _append(
                quotes,
                book,
                "MATCH_RESULT",
                "",
                outcome,
                raw.get(open_1x2 + suffix),
                raw.get(close_1x2 + suffix),
            )
        for outcome, suffix in TOTALS_OUTCOMES.items():
            _append(
                quotes,
                book,
                "TOTAL_GOALS",
                TOTALS_PARAMS,
                outcome,
                raw.get(open_tot + suffix),
                raw.get(close_tot + suffix),
            )
    return quotes


def _append(
    quotes: list[OddsQuote],
    book: str,
    market: str,
    params_key: str,
    outcome: str,
    opening: str | None,
    closing: str | None,
) -> None:
    opening_price, closing_price = _price(opening), _price(closing)
    if opening_price is None and closing_price is None:
        return
    quotes.append(OddsQuote(book, market, params_key, outcome, opening_price, closing_price))


def _parse_date(value: str) -> date:
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()  # noqa: DTZ007 (date only)
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {value!r}")


def _kickoff(match_date: date, value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    local = datetime.combine(match_date, time.fromisoformat(value.strip()), tzinfo=UK)
    return local.astimezone(UTC)


def _int(value: str | None) -> int | None:
    return int(value) if value and value.strip() else None


def _price(value: str | None) -> float | None:
    """Decimal odds; anything missing or not above 1.0 is treated as absent."""
    if value is None or not value.strip():
        return None
    try:
        price = float(value)
    except ValueError:
        return None
    return price if price > 1.0 else None
