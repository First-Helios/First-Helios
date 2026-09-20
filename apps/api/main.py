"""Helios API — FastAPI application entrypoint (ADR-0008).

Operational probes (`/healthz`, `/readyz`) stay unversioned; all domain routes
mount under `/v1`. Conventions (cursor pagination, uniform error body, request
correlation, CORS) are wired here so every route inherits them.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from apps.api.errors import register_exception_handlers
from apps.api.observability import configure_logging, request_context_middleware
from apps.api.routes import venues
from packages.helios_core.config import get_settings
from packages.helios_core.db.session import get_engine

configure_logging()

app = FastAPI(title="Helios API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_allow_origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.middleware("http")(request_context_middleware)
register_exception_handlers(app)

app.include_router(venues.router, prefix="/v1")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe. The process is up; does not touch the database."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> JSONResponse:
    """Readiness probe. Confirms the database is reachable."""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse(status_code=200, content={"status": "ok"})
