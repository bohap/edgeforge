"""Command line: ``edgeforge serve``, ``compare``, ``backfill``, ``backtest`` and ``dq``."""

import argparse
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from edgeforge.backtest.market import compare_with_market, market_blend_test
from edgeforge.backtest.recalibrate import recalibrate
from edgeforge.backtest.walk_forward import run_backtest
from edgeforge.catalog.models import Competition
from edgeforge.catalog.reference import UNDERSTAT_COMPETITIONS
from edgeforge.compare.report import render
from edgeforge.compare.service import compare_match, fit_ratings
from edgeforge.core.config import get_settings
from edgeforge.core.db import default_session_factory
from edgeforge.core.logging import configure_logging, get_logger
from edgeforge.features.gateway import upcoming_fixtures
from edgeforge.football.teams import TeamLookupError, find_team, team_names
from edgeforge.ingestion.football_data import enqueue_season
from edgeforge.ingestion.understat import enqueue_league
from edgeforge.models.football_goals.model import GoalModelConfig
from edgeforge.ops.models import Severity
from edgeforge.providers.football_data_uk.client import DIVISIONS
from edgeforge.providers.understat.client import League
from edgeforge.quality.checks import CHECKS, run_checks

log = get_logger(__name__)


def parse_seasons(value: str) -> list[int]:
    """``2024`` → [2024]; ``2021-2026`` → [2021, ..., 2026]."""
    first, _, last = value.partition("-")
    start, end = int(first), int(last or first)
    if end < start:
        raise argparse.ArgumentTypeError(f"season range {value!r} is reversed")
    return list(range(start, end + 1))


def parse_leagues(value: str) -> list[League]:
    try:
        return [League(code.strip()) for code in value.split(",") if code.strip()]
    except ValueError as exc:
        valid = ", ".join(league.value for league in League)
        raise argparse.ArgumentTypeError(f"{exc}; valid leagues: {valid}") from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="edgeforge")
    commands = parser.add_subparsers(dest="command", required=True)
    backfill = commands.add_parser("backfill", help="queue historical ingestion jobs")
    backfill.add_argument("provider", choices=["understat", "football-data"])
    backfill.add_argument("--seasons", type=parse_seasons, required=True)
    backfill.add_argument("--leagues", type=parse_leagues, default=list(League))
    commands.add_parser("dq", help="run data-quality checks and print open issues per check")
    backtest = commands.add_parser("backtest", help="walk-forward backtest of the goal model")
    backtest.add_argument("--competition", required=True, help="competition code, e.g. EPL")
    backtest.add_argument("--from", dest="start", type=_utc_date, required=True)
    backtest.add_argument("--to", dest="end", type=_utc_date, required=True)
    backtest.add_argument("--half-life", type=float, default=180.0)
    backtest.add_argument("--xg-weight", type=float, default=0.7)
    backtest.add_argument(
        "--recalibrate", action="store_true", help="apply walk-forward power recalibration"
    )
    backtest.add_argument(
        "--blend-test",
        type=_utc_date,
        metavar="HOLDOUT_START",
        help="with --market: test whether the model adds information beyond opening prices",
    )
    backtest.add_argument(
        "--market",
        metavar="BOOKMAKER",
        help="also score against this bookmaker's prices, e.g. market_average or pinnacle",
    )
    compare = commands.add_parser(
        "compare", help="compare two teams: form, xG, head-to-head and estimated probabilities"
    )
    compare.add_argument("--competition", required=True, help="competition code, e.g. EPL")
    compare.add_argument("--home", help="home team name (with --away); default: all fixtures")
    compare.add_argument("--away", help="away team name")
    compare.add_argument(
        "--days", type=int, default=7, help="without --home/--away: fixtures in the next N days"
    )
    compare.add_argument("--last", type=parse_windows, default=[5, 10], help="e.g. 5,10,20")
    compare.add_argument(
        "--as-of", type=_utc_date, help="use only data known at this date (default: now)"
    )
    serve = commands.add_parser("serve", help="run the web app and its API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    return parser


def parse_windows(value: str) -> list[int]:
    """``5,10`` → [5, 10]."""
    windows = [int(part) for part in value.split(",") if part.strip()]
    if not windows or min(windows) < 1:
        raise argparse.ArgumentTypeError("--last needs positive integers, e.g. 5,10")
    return windows


def _utc_date(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(get_settings())
    if args.command == "dq":
        return run_dq()
    if args.command == "backtest":
        return run_backtest_command(args)
    if args.command == "compare":
        return run_compare(args)
    if args.command == "serve":
        return run_serve(args)
    queued = skipped = 0
    with default_session_factory().begin() as session:
        for league in args.leagues:
            for season in args.seasons:
                if args.provider == "understat":
                    job = enqueue_league(session, league, season)
                else:
                    code = UNDERSTAT_COMPETITIONS[league.value].code
                    if code not in DIVISIONS:
                        log.warning("no_football_data_division", league=league.value)
                        continue
                    job = enqueue_season(session, code, season)
                if job is None:
                    skipped += 1
                else:
                    queued += 1
    log.info("backfill_queued", provider=args.provider, queued=queued, already_queued=skipped)
    return 0


def run_backtest_command(args: argparse.Namespace) -> int:
    config = GoalModelConfig(half_life_days=args.half_life, xg_weight=args.xg_weight)
    with default_session_factory()() as session:
        competition = session.scalars(
            select(Competition.id).where(Competition.code == args.competition)
        ).one()
        result = run_backtest(session, competition, args.start, args.end, config=config)
    if args.recalibrate:
        result = recalibrate(result)
    print(f"{'market':14} {'n':>5} {'logloss':>8} {'base':>8} {'brier':>7} {'base':>7} {'ece':>6}")
    for s in result.scores():
        print(
            f"{s.market:14} {s.predictions:5} {s.model_log_loss:8.4f} {s.base_log_loss:8.4f} "
            f"{s.model_brier:7.4f} {s.base_brier:7.4f} {s.model_ece:6.3f}"
        )
    if args.market:
        with default_session_factory()() as session:
            comparisons = compare_with_market(session, result, bookmaker=args.market)
        for c in comparisons:
            print(
                f"\n{c.market} vs {c.bookmaker} closing prices ({c.matches} matches): "
                f"model log loss {c.model_log_loss:.4f}, market {c.market_log_loss:.4f}"
            )
            header = ("price", "edge", "bets", "roi", "±se", "odds", "clv")
            print("  {:8} {:>5} {:>5} {:>7} {:>6} {:>5} {:>7}".format(*header))
            for sim in c.simulations:
                clv = "" if sim.closing_line_value is None else f"{sim.closing_line_value:+.3f}"
                print(
                    f"  {sim.price_type:8} {sim.min_edge:5.2f} {sim.bets:5} {sim.roi:+7.3f} "
                    f"{sim.roi_standard_error:6.3f} {sim.average_odds:5.2f} {clv:>7}"
                )
    if args.market and args.blend_test:
        with default_session_factory()() as session:
            blends = market_blend_test(session, result, args.blend_test, bookmaker=args.market)
        print(f"\nDoes the model add information beyond {args.market} opening prices?")
        for b in blends:
            print(
                f"  {b.market:14} n={b.matches} model {b.model_log_loss:.4f}  "
                f"opening {b.opening_log_loss:.4f}  blend {b.blend_log_loss:.4f}  "
                f"closing {b.closing_log_loss:.4f}  weights market={b.market_weight:.2f} "
                f"model={b.model_weight:.2f}"
            )
    return 0


def run_compare(args: argparse.Namespace) -> int:
    if (args.home is None) != (args.away is None):
        print("give both --home and --away, or neither", file=sys.stderr)
        return 2
    as_of = args.as_of or datetime.now(UTC)
    with default_session_factory()() as session:
        competition = session.scalars(
            select(Competition.id).where(Competition.code == args.competition)
        ).one_or_none()
        if competition is None:
            print(f"unknown competition {args.competition!r}", file=sys.stderr)
            return 2
        if args.home is not None:
            try:
                pairs = [(find_team(session, args.home), find_team(session, args.away))]
            except TeamLookupError as exc:
                print(exc, file=sys.stderr)
                return 2
            kickoffs: list[datetime | None] = [None]
        else:
            fixtures = upcoming_fixtures(
                session, as_of, as_of + timedelta(days=args.days), competition_id=competition
            )
            if not fixtures:
                print(f"no {args.competition} fixtures in the next {args.days} days")
                return 0
            pairs = [(f.home_team_id, f.away_team_id) for f in fixtures]
            kickoffs = [f.kickoff_at for f in fixtures]
        ratings = fit_ratings(session, competition, as_of)
        names = team_names(session, {team for pair in pairs for team in pair})
        reports = []
        for (home, away), kickoff in zip(pairs, kickoffs, strict=True):
            comparison = compare_match(
                session, home, away, as_of, windows=args.last, ratings=ratings
            )
            report = render(comparison, names)
            if kickoff is not None:
                report = f"{kickoff:%a %Y-%m-%d %H:%M} UTC  {report}"
            reports.append(report)
    print(f"\n\n{'=' * 70}\n\n".join(reports))
    return 0


def run_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from edgeforge.api.app import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port, log_config=None)
    return 0


def run_dq() -> int:
    """Exit code 1 when any error-severity check has open issues."""
    with default_session_factory().begin() as session:
        summary = run_checks(session)
    for check in CHECKS:
        print(
            f"{check.severity.value:8} {check.code:24} {summary[check.code]:6}  {check.description}"
        )
    errors = sum(summary[c.code] for c in CHECKS if c.severity is Severity.ERROR)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
