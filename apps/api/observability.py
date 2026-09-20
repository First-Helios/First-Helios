"""Structured logging and per-request correlation ids (ADR-0008).

``structlog`` emits JSON in staging/prod and human-readable lines in dev. Each
request is tagged with a request id (propagated from an inbound ``X-Request-ID``
or freshly minted) that is bound to the log context and returned to the client
as ``X-Request-ID`` and as ``trace_id`` in any error body.
"""

from __future__ import annotations

import logging
import sys
import uuid
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"


def configure_logging(*, json_logs: bool | None = None) -> None:
    """Configure structlog once at startup.

    ``json_logs`` defaults to JSON when stdout is not a TTY (staging/prod) and
    human-readable rendering when it is (local dev).
    """
    use_json = json_logs if json_logs is not None else not sys.stdout.isatty()
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if use_json else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )


async def request_context_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Assign/propagate a request id, bind it to logs, and echo it back."""
    request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
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
        raise
    response.headers[REQUEST_ID_HEADER] = request_id
    logger.info("request_completed", status_code=response.status_code)
    return response
