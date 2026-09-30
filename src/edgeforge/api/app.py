"""HTTP API for the web app: ``uv run edgeforge serve``."""

from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from edgeforge.api.routes import RatingsCache, router
from edgeforge.core.db import default_session_factory


def create_app(session_factory: sessionmaker[Session] | None = None) -> FastAPI:
    app = FastAPI(title="EdgeForge", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.session_factory = session_factory or default_session_factory()
    app.state.ratings_cache = RatingsCache()
    app.include_router(router)
    return app
