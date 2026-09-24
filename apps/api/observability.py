"""Structured logging and per-request correlation ids (ADR-0008).

``structlog`` emits JSON in staging/prod and human-readable lines in dev. Each
request is tagged with a request id (propagated from an inbound
``X-Request-ID`` when it looks safe, freshly minted otherwise -- see
``_inbound_request_id``) that is bound to the log context and returned to the
client as ``X-Request-ID`` and as ``trace_id`` in any error body.

Unhandled exceptions are caught and rendered into the uniform error envelope
*here*, not by an app-level ``Exception`` handler. FastAPI/Starlette route a
bare ``Exception`` handler through ``ServerErrorMiddleware``, which wraps
every user middleware -- including this one and ``CORSMiddleware`` -- so a
response built there never carries the ``X-Request-ID``/CORS headers those
middlewares add (R42). Catching the exception here, one layer inside
``ServerErrorMiddleware``, is what lets the response carry both.
"""

from __future__ import annotations

import logging
import re
import sys
import uuid
from typing import TYPE_CHECKING

import structlog
from fastapi import status

from apps.api.errors import render_error
from packages.helios_core.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"

# A client-supplied X-Request-ID is only trusted verbatim when it's short and
# made of characters that are safe to echo into logs, JSON bodies, and
# response headers; anything else (oversized, control/CRLF characters, ...)
# is replaced with a freshly minted id instead of trusted (R99).
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

# Uvicorn configures these loggers itself (with propagate=False) before our
# app module is imported; re-pointing them at the root handler here runs
# *after* that (uvicorn imports the app, which runs this, after its own
# logging.config.dictConfig call), so it wins.
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def configure_logging(*, json_logs: bool | None = None) -> None:
    """Configure structlog once at startup, and route stdlib/uvicorn logs through it.

    ``json_logs`` defaults to JSON when stdout is not a TTY (staging/prod) and
    human-readable rendering when it is (local dev). Without this, uvicorn's
    own request/error logs (including a 500's traceback, which uvicorn also
    logs by default) render in a different, unstructured format with no
    ``request_id`` -- and can duplicate ours (R48).
    """
    use_json = json_logs if json_logs is not None else not sys.stdout.isatty()
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if use_json else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(logging.INFO)

    # Send uvicorn's own logs (access, error, startup) through the same
    # formatter instead of the differently-formatted handlers it installs
    # for itself, so the whole process emits one consistent log stream.
    for name in _UVICORN_LOGGERS:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True


def _inbound_request_id(request: Request) -> str:
    value = request.headers.get(REQUEST_ID_HEADER)
    if value is not None and _SAFE_REQUEST_ID.fullmatch(value):
        return value
    return uuid.uuid4().hex


def _apply_cors_headers(request: Request, response: Response) -> None:
    """Add the CORS headers ``CORSMiddleware`` never got a chance to (R42).

    A no-op when they're already present: every response that passed through
    ``CORSMiddleware`` normally (everything except the 500s rendered in the
    ``except`` branch below) already has them.
    """
    if "access-control-allow-origin" in response.headers:
        return
    origin = request.headers.get("origin")
    if origin is not None and origin in get_settings().cors_allow_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"


async def request_context_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Assign/propagate a request id, bind it to logs, and echo it back.

    Also catches unhandled exceptions and renders the uniform error envelope
    -- see the module docstring for why that has to happen here rather than
    in an app-level exception handler.
    """
    request_id = _inbound_request_id(request)
    request.state.request_id = request_id
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
    )
    logger = structlog.get_logger("helios.api")
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("request_failed")
        response = render_error(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "an unexpected error occurred",
        )
    response.headers[REQUEST_ID_HEADER] = request_id
    _apply_cors_headers(request, response)
    logger.info("request_completed", status_code=response.status_code)
    return response
