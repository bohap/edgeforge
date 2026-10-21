"""HTTP API and web app: ``uv run edgeforge serve``."""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from procrastinate.app import WorkerOptions
from sqlalchemy.orm import Session, sessionmaker

from edgeforge.api import sync
from edgeforge.api.routes import RatingsCache, router
from edgeforge.core.config import get_settings
from edgeforge.core.db import default_session_factory
from edgeforge.core.logging import get_logger
from edgeforge.jobs.app import create_app as create_jobs_app

log = get_logger(__name__)

# Jobs still running at shutdown are aborted after this many seconds and retried later.
WORKER_SHUTDOWN_TIMEOUT = 10.0

# Production build of web/ (``npm run build``) when running from a checkout.
DEFAULT_WEB_DIR = Path(__file__).resolve().parents[3] / "web" / "dist" / "web" / "browser"


def create_app(
    session_factory: sessionmaker[Session] | None = None,
    web_dir: Path | None = DEFAULT_WEB_DIR,
    *,
    run_worker: bool = False,
    worker_queues: list[str] | None = None,
) -> FastAPI:
    """With ``run_worker``, the process also runs a job worker (on ``worker_queues``, default
    all), so data syncs and the periodic refresh need no separate ``edgeforge-worker``."""
    app = FastAPI(
        title="EdgeForge",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=_worker_lifespan(worker_queues) if run_worker else None,
    )
    app.state.session_factory = session_factory or default_session_factory()
    app.state.ratings_cache = RatingsCache()
    app.include_router(router)
    app.include_router(sync.router)
    if web_dir is not None and (web_dir / "index.html").is_file():
        _serve_web(app, web_dir.resolve())
    return app


def _worker_lifespan(
    queues: list[str] | None,
) -> Callable[[FastAPI], contextlib.AbstractAsyncContextManager[None]]:
    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        jobs = create_jobs_app(get_settings())
        async with jobs.open_async():
            options: WorkerOptions = {
                "install_signal_handlers": False,
                "shutdown_graceful_timeout": WORKER_SHUTDOWN_TIMEOUT,
            }
            if queues is not None:
                options["queues"] = queues
            worker = asyncio.create_task(jobs.run_worker_async(**options))
            log.info("embedded_worker_started")
            try:
                yield
            finally:
                worker.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await worker
                log.info("embedded_worker_stopped")

    return lifespan


def _serve_web(app: FastAPI, root: Path) -> None:
    """Static files of the Angular build; any other path gets index.html so client-side
    routes (``/EPL/compare?...``) work on reload."""

    @app.get("/{path:path}", include_in_schema=False)
    def web(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404)
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})
