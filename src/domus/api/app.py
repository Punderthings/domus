"""Application factory: ``uvicorn domus.api.app:create_app --factory``."""

from fastapi import FastAPI
from sqlalchemy import Engine

from domus import __version__
from domus.api.routers import (
    admin,
    assets,
    auth,
    canvases,
    documents,
    maintenance,
    sample,
    space,
)
from domus.api.security import LoginRateLimiter
from domus.api.spa import mount_spa
from domus.config import Settings, get_settings
from domus.db import make_engine, make_session_factory
from domus.migrate import upgrade

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    """Build the app. Migrates the database to the latest schema first."""
    settings = settings or get_settings()
    engine = engine or make_engine(settings.resolved_database_url())
    upgrade(engine)

    app = FastAPI(
        title="Domus",
        version=__version__,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.login_limiter = LoginRateLimiter(
        settings.login_max_failures, settings.login_window_seconds
    )

    @app.get(f"{API_PREFIX}/health", tags=["meta"])
    def health() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok", "version": __version__}

    for module in (auth, space, assets, maintenance, documents, canvases, admin, sample):
        app.include_router(module.router, prefix=API_PREFIX)
    # The feed lives outside /api/v1 so calendar URLs stay short and stable.
    app.include_router(maintenance.calendar_router)
    # Last, so the front end's catch-all route never shadows the API.
    mount_spa(app)
    return app
