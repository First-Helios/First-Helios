"""Helios API — FastAPI application entrypoint."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from packages.helios_core.db.session import get_engine

app = FastAPI(title="Helios API")


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
