"""Helios API — FastAPI application entrypoint (ADR-0008).

Operational probes (`/healthz`, `/readyz`) stay unversioned; all domain routes
mount under `/v1`. Conventions (cursor pagination, uniform error body, request
correlation, CORS) are wired here so every route inherits them.
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from apps.api.errors import register_exception_handlers, render_error
from apps.api.observability import REQUEST_ID_HEADER, configure_logging, request_context_middleware
from apps.api.routes import venues
from apps.api.schemas import ErrorResponse
from packages.helios_core.config import get_settings
from packages.helios_core.db.session import get_engine

configure_logging()

app = FastAPI(title="Helios API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_allow_origins,
    allow_methods=["GET"],
    allow_headers=["*"],
    # Without this, cross-origin JavaScript can read a response's body but
    # not its X-Request-ID header, so a reported error can't be correlated
    # to a log line from the browser side (R46).
    expose_headers=[REQUEST_ID_HEADER],
)
app.middleware("http")(request_context_middleware)
register_exception_handlers(app)

app.include_router(venues.router, prefix="/v1")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness probe. The process is up; does not touch the database."""
    return {"status": "ok"}


@app.get(
    "/readyz",
    responses={503: {"model": ErrorResponse, "description": "The database is not reachable."}},
)
def readyz(request: Request) -> JSONResponse:
    """Readiness probe. Confirms the database is reachable."""
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        structlog.get_logger("helios.api").exception("readyz_failed")
        return render_error(
            request,
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "service_unavailable",
            "database is not reachable",
        )
    return JSONResponse(status_code=200, content={"status": "ok"})
