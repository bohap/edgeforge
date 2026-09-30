"""HTTP API and web app: ``uv run edgeforge serve``."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, sessionmaker

from edgeforge.api.routes import RatingsCache, router
from edgeforge.core.db import default_session_factory

# Production build of web/ (``npm run build``) when running from a checkout.
DEFAULT_WEB_DIR = Path(__file__).resolve().parents[3] / "web" / "dist" / "web" / "browser"


def create_app(
    session_factory: sessionmaker[Session] | None = None, web_dir: Path | None = DEFAULT_WEB_DIR
) -> FastAPI:
    app = FastAPI(title="EdgeForge", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.session_factory = session_factory or default_session_factory()
    app.state.ratings_cache = RatingsCache()
    app.include_router(router)
    if web_dir is not None and (web_dir / "index.html").is_file():
        _serve_web(app, web_dir.resolve())
    return app


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
