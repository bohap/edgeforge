"""Command line: ``edgeforge backfill understat --seasons 2021-2026 [--leagues EPL,La_liga]``."""

import argparse
import sys

from edgeforge.core.config import get_settings
from edgeforge.core.db import default_session_factory
from edgeforge.core.logging import configure_logging, get_logger
from edgeforge.ingestion.understat import enqueue_league
from edgeforge.ops.models import Severity
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
    backfill.add_argument("provider", choices=["understat"])
    backfill.add_argument("--seasons", type=parse_seasons, required=True)
    backfill.add_argument("--leagues", type=parse_leagues, default=list(League))
    commands.add_parser("dq", help="run data-quality checks and print open issues per check")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(get_settings())
    if args.command == "dq":
        return run_dq()
    queued = skipped = 0
    with default_session_factory().begin() as session:
        for league in args.leagues:
            for season in args.seasons:
                if enqueue_league(session, league, season) is None:
                    skipped += 1
                else:
                    queued += 1
    log.info("backfill_queued", provider=args.provider, queued=queued, already_queued=skipped)
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
