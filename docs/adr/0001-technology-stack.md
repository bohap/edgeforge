# ADR 0001: Technology stack

- Status: accepted
- Date: 2026-09-29

## Context

EdgeForge needs data ingestion, statistical modelling, a web API, a web UI and, later,
market-price tracking and wallet-based trading. A small team (and coding agents) builds
it, so the stack should keep moving parts to a minimum and use one backend language.

## Decision

| Area | Choice |
|------|--------|
| Backend | Python 3.14, modular monolith, FastAPI + Pydantic v2, SQLAlchemy 2 (psycopg 3) |
| Migrations | Alembic; autogenerate is a draft only, migrations are reviewed as SQL |
| Database | PostgreSQL 18 (native `uuidv7()`, temporal `WITHOUT OVERLAPS` constraints) |
| Jobs and cron | Procrastinate (task queue stored in PostgreSQL, transactional enqueue) |
| Cache | Redis 8.6 or Valkey, added in Stage 2 for market prices only |
| Blob storage | PostgreSQL `bytea` behind a `BlobStore` interface; S3-compatible storage later |
| Features | SQL window functions into feature tables; NumPy/SciPy for model fitting |
| Frontend | Angular 22, Angular SSR for public pages, Apache ECharts |
| Observability | OpenTelemetry + Collector to Grafana Cloud; Sentry for errors; structlog JSON logs |
| Tooling | uv, ruff, mypy (strict), pytest, GitHub Actions |

## Consequences

- One database to operate in Stage 1; no broker or object store until data volume needs it.
- A job and the data change that triggers it commit together, so follow-up work is never lost.
- The Postgres queue has a lower throughput ceiling than Redis brokers; acceptable at
  thousands of jobs per hour. Revisit if job volume grows by orders of magnitude.
- Wallet UI kits are mostly React; Stage 3 uses framework-agnostic libraries
  (viem, `@wagmi/core`, Reown AppKit web components) inside Angular.
