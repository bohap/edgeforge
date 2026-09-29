"""Worker entry point: ``edgeforge-worker [queue ...]``."""

import sys

from edgeforge.core.config import get_settings
from edgeforge.core.logging import configure_logging
from edgeforge.jobs.app import create_app


def main(argv: list[str] | None = None) -> None:
    settings = get_settings()
    configure_logging(settings)
    queues = (argv if argv is not None else sys.argv[1:]) or None
    create_app(settings).run_worker(queues=queues)
