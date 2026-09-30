# Roadmap

EdgeForge is a personal tool first. The current goal is the simplest useful thing: for an
upcoming match, put the numbers side by side that would otherwise be looked up by hand
(xG, recent form, head-to-head) and add a rough estimated probability. Everything below is
deliberately deferred until the simple version is in daily use.

## Now: match comparison

- `edgeforge compare`: both teams' xG for and against, goals and results over the last
  5 / 10 / N matches (overall and home or away), and the head-to-head record.
- Estimated probabilities for 1X2, both teams to score and over/under 2.5 from the existing
  goal model, shown next to the raw numbers, never instead of them.

## What we already know

Walk-forward backtests on 2024/25 and 2025/26 (Understat data, football-data.co.uk prices):

- The goal model (time-decayed Dixon-Coles on a blend of xG and goals) beats base rates on
  1X2 in all five leagues tested (EPL, La Liga, Bundesliga, Serie A, Ligue 1).
- It never beats the market's closing prices. In the blend test (`p ∝ opening^w1 · model^w2`)
  the model weight is about zero or negative everywhere (EPL 1X2 −0.03, totals +0.23; the
  other leagues are negative on both).
- Over/under 2.5 carries almost no signal from team ratings alone.
- Power recalibration does not remove the favourite–longshot pattern.

So the numbers are useful as a summary of form, not as a source of betting edge.

## Model extensions (later, maybe)

Roughly in the order they would help:

1. **Lineups and injuries.** The main information the market has and the model lacks.
   Needs a provider for confirmed lineups and absences, then player-weighted ratings.
2. **Player goal model.** Anytime scorer probabilities from player xG shares and expected
   minutes (the player and shot data is already ingested).
3. **Favourite–longshot test.** Sharpening opening prices looked slightly better than
   closing prices in La Liga, the Bundesliga and Serie A. Untested hypothesis; needs a
   proper out-of-sample check before anyone relies on it.
4. **Confidence score.** Separate from probability: data coverage, model agreement with the
   market, sample size.
5. **More markets and leagues.** Corners and cards need new data; more leagues need
   provider coverage.
6. **Other sports.** Same layers (raw, core, features, model, markets) per sport.

## Product extensions (later, maybe)

- Web UI (Angular) and an admin view of ingestion, data quality and job runs.
- Polymarket prices as another market source.
- Wallet integration and order placement, only with explicit limits and confirmation.
- Observability stack (OpenTelemetry, Grafana, Sentry) once something runs unattended.

The original full plan is kept in the "EdgeForge Platform Plan" artifact and
[ADR 0001](adr/0001-technology-stack.md).
