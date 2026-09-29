# EdgeForge

Sports betting intelligence platform. It ingests sports data, estimates calibrated
probabilities for betting markets, compares them with market prices, and reports its
own historical performance. Outputs are statistical estimates, never guarantees.

Stage 1 covers football, with Understat as the first data provider.

## Requirements

- Python 3.14 and [uv](https://docs.astral.sh/uv/)
- PostgreSQL 18 (from the database layer onward)

## Development

```bash
uv sync                      # create .venv and install dependencies
uv run pytest                # tests (network-marked tests are skipped in CI)
uv run ruff check .          # lint
uv run ruff format .         # format
uv run mypy                  # type check (strict)
uv run pre-commit install    # optional: run the checks before each commit
```

Settings come from environment variables prefixed with `EDGEFORGE_` (or a local `.env`
file). See `src/edgeforge/core/config.py`.

## Layout

```
src/edgeforge/      application package (modular monolith)
  core/             configuration, logging, database, time
tests/              unit and integration tests
docs/adr/           architecture decision records
```

## Documentation

- [ADR 0001: technology stack](docs/adr/0001-technology-stack.md)
