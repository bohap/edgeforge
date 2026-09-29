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
uv run pytest                # tests (skips live network tests)
uv run pytest -m network     # live checks against real providers (manual only)
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

## Database

Migrations live in `migrations/` (Alembic). Autogenerate output is only a draft: review
each migration as SQL before committing.

```bash
export EDGEFORGE_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/edgeforge
uv run alembic upgrade head            # apply
uv run alembic upgrade head --sql      # print the SQL without touching the database
```

Database tests need `EDGEFORGE_TEST_DATABASE_URL` pointing at a disposable database (its
`ref` and `ops` schemas are dropped and recreated). Without it they are skipped locally;
CI sets `EDGEFORGE_REQUIRE_DB_TESTS=1` so they can never be skipped there.

## Background jobs

Jobs run on [Procrastinate](https://procrastinate.readthedocs.io/), which stores the queue
in PostgreSQL. Its schema is applied by our Alembic migrations from a vendored copy
(`migrations/sql/`), pinned to the exact package version.

```bash
uv run edgeforge-worker            # all queues
uv run edgeforge-worker ops        # only the "ops" queue
```

Enqueue with `edgeforge.jobs.enqueue.enqueue_in_session(session, "ops:heartbeat", ...)`: the
job commits or rolls back together with the rest of the transaction. Wrap job bodies in
`edgeforge.ops.job_runs.run_tracked` so each run is recorded in `ops.job_run`.

## Ingestion

```bash
uv run edgeforge backfill understat --seasons 2021-2026            # all six leagues
uv run edgeforge backfill understat --seasons 2026 --leagues EPL   # one league-season
uv run edgeforge-worker ingest-understat                            # process the queue
```

A league job fetches and normalizes the league, then queues a match job for every finished
match that has no player data yet. All Understat jobs share one lock, so only one request
stream runs at a time (`EDGEFORGE_UNDERSTAT_REQUESTS_PER_SECOND`, default 0.4). Re-running a
backfill is safe: unchanged responses are skipped and waiting jobs are not duplicated.
