"""Command line: ``edgeforge backfill understat --seasons 2021-2026 [--leagues EPL,La_liga]``."""

import argparse
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from edgeforge.backtest.market import compare_with_market, market_blend_test
from edgeforge.backtest.recalibrate import recalibrate
from edgeforge.backtest.walk_forward import run_backtest
from edgeforge.catalog.models import Competition
from edgeforge.catalog.reference import UNDERSTAT_COMPETITIONS
from edgeforge.core.config import get_settings
from edgeforge.core.db import default_session_factory
from edgeforge.core.logging import configure_logging, get_logger
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
    return parser


def _utc_date(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(get_settings())
    if args.command == "dq":
        return run_dq()
    if args.command == "backtest":
        return run_backtest_command(args)
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
