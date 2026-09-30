"""Season CSV locations. The ``www`` host redirects to the bare domain, so use that directly."""

from dataclasses import dataclass

BASE_URL = "https://football-data.co.uk"
PROVIDER_CODE = "football_data_uk"
RESOURCE = "season_csv"

# Internal competition code (see catalog.reference) -> football-data division code.
DIVISIONS = {
    "EPL": "E0",
    "LA_LIGA": "SP1",
    "BUNDESLIGA": "D1",
    "SERIE_A": "I1",
    "LIGUE_1": "F1",
}


@dataclass(frozen=True, slots=True)
class SeasonRef:
    competition_code: str
    season: int  # starting year: 2025 means 2025/26

    def __post_init__(self) -> None:
        if self.competition_code not in DIVISIONS:
            raise ValueError(f"no football-data division for competition {self.competition_code!r}")

    @property
    def division(self) -> str:
        return DIVISIONS[self.competition_code]

    @property
    def key(self) -> str:
        return f"{self.competition_code}/{self.season}"

    @property
    def url(self) -> str:
        first, second = self.season % 100, (self.season + 1) % 100
        return f"{BASE_URL}/mmz4281/{first:02d}{second:02d}/{self.division}.csv"


def season_ref_from_key(key: str) -> SeasonRef:
    competition_code, season = key.split("/")
    return SeasonRef(competition_code, int(season))
