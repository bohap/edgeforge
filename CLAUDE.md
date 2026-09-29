# Working in this repository

## Commands

- `uv sync` installs everything; `uv run pytest`, `uv run ruff check .`,
  `uv run ruff format --check .` and `uv run mypy` are the checks CI runs.
- Run all four before pushing. CI must be green before a PR is merged (squash merge).

## Conventions

- Python 3.14, src layout, strict mypy for `src/`.
- Modules under `src/edgeforge/` talk to each other through service functions, never
  through another module's tables or ORM models.
- All timestamps are timezone-aware UTC (`datetime.now(UTC)`); ruff's DTZ rules enforce it.
- Missing data is `None`, never `0`. Never substitute a default for a missing statistic.
- Point-in-time rule: anything that feeds a prediction reads only data with
  `event_time < as_of` and `observed_at <= as_of`.
- Tests: unit tests in `tests/unit`, database tests marked `db`, tests that call real
  external services marked `network` (never run in CI; use recorded fixtures instead).
- Work in small, stacked PRs; each PR has tests for what it adds.

## Product language

Never use "guaranteed", "safe bet", "lock", "can't lose" or "100%" in user-facing text.
Use "estimated probability", "model confidence", "market implied probability", "model edge".
