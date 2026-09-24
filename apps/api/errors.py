"""Uniform error contract for the read API (ADR-0008).

Every non-2xx response body is ``{detail, code, trace_id}``. ``code`` is a
stable, documented enum (:data:`apps.api.schemas.ErrorCode`) clients switch
on; ``detail`` is human prose that may change. ``trace_id`` is the per-request
id assigned by the observability middleware, so a user-reported error is
greppable in the logs.

``render_error`` is exported for use outside these handlers too --
``observability.py`` calls it directly for unhandled exceptions, and
``main.py`` for ``/readyz`` -- see :func:`register_exception_handlers` for why
that matters for unhandled exceptions specifically.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from apps.api.schemas import ErrorCode, ErrorResponse

if TYPE_CHECKING:
    from collections.abc import Mapping

    from fastapi import FastAPI


class ApiError(Exception):
    """A handled error that maps to the uniform error body."""

    def __init__(self, status_code: int, code: ErrorCode, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code: ErrorCode = code
        self.detail = detail


class NotFoundError(ApiError):
    """A single addressed resource does not exist (an empty list is not this)."""

    def __init__(self, detail: str) -> None:
        super().__init__(status.HTTP_404_NOT_FOUND, "not_found", detail)


class InvalidCursorError(ApiError):
    """A pagination cursor is malformed or does not decode."""

    def __init__(self, detail: str = "cursor is malformed") -> None:
        super().__init__(status.HTTP_400_BAD_REQUEST, "invalid_cursor", detail)


def trace_id(request: Request) -> str:
    """The per-request id bound by the observability middleware, or "unknown"."""
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else "unknown"


def error_body(request: Request, code: ErrorCode, detail: str) -> ErrorResponse:
    return ErrorResponse(detail=detail, code=code, trace_id=trace_id(request))


def render_error(
    request: Request,
    status_code: int,
    code: ErrorCode,
    detail: str,
    *,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Build the uniform error envelope as a response."""
    return JSONResponse(
        status_code=status_code,
        content=error_body(request, code, detail).model_dump(),
        headers=dict(headers) if headers else None,
    )


def _http_exception_code(status_code: int) -> ErrorCode:
    if status_code == status.HTTP_404_NOT_FOUND:
        return "not_found"
    if status_code == status.HTTP_405_METHOD_NOT_ALLOWED:
        return "method_not_allowed"
    if 400 <= status_code < 500:
        return "validation_error"
    return "internal_error"


def register_exception_handlers(app: FastAPI) -> None:
    """Attach handlers so every error path returns the uniform body.

    A bare ``Exception`` handler is registered too, but only as a defence in
    depth. FastAPI routes a generic ``Exception`` handler through Starlette's
    ``ServerErrorMiddleware``, which sits *outside* every user middleware
    (CORS, request-id) -- a response built there can never carry those
    headers (R42). ``request_context_middleware`` (``observability.py``)
    catches unhandled exceptions itself, one layer in, and calls
    :func:`render_error` directly so the headers still apply; that path
    handles every real request. This handler only matters if some future
    change ever let an exception bypass that middleware.
    """

    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return render_error(request, exc.status_code, exc.code, exc.detail)

    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return render_error(
            request,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "validation_error",
            "request parameters failed validation",
        )

    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _http_exception_code(exc.status_code)
        detail = exc.detail if isinstance(exc.detail, str) else "request could not be served"
        return render_error(request, exc.status_code, code, detail, headers=exc.headers)

    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        return render_error(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "an unexpected error occurred",
        )

    app.add_exception_handler(ApiError, handle_api_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, handle_validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, handle_unexpected)
