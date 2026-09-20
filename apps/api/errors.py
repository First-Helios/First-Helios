"""Uniform error contract for the read API (ADR-0008).

Every non-2xx response body is ``{detail, code, trace_id}``. ``code`` is a
stable, documented string clients switch on; ``detail`` is human prose that may
change. ``trace_id`` is the per-request id assigned by the observability
middleware, so a user-reported error is greppable in the logs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from apps.api.schemas import ErrorResponse

if TYPE_CHECKING:
    from fastapi import FastAPI

ErrorCode = Literal["not_found", "validation_error", "invalid_cursor", "internal_error"]


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


def _trace_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else "unknown"


def _body(request: Request, code: ErrorCode, detail: str) -> ErrorResponse:
    return ErrorResponse(detail=detail, code=code, trace_id=_trace_id(request))


def _render(request: Request, status_code: int, code: ErrorCode, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=_body(request, code, detail).model_dump(),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach handlers so every error path returns the uniform body."""

    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return _render(request, exc.status_code, exc.code, exc.detail)

    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _render(
            request,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "validation_error",
            "request parameters failed validation",
        )

    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code: ErrorCode = (
            "not_found" if exc.status_code == status.HTTP_404_NOT_FOUND else ("internal_error")
        )
        detail = exc.detail if isinstance(exc.detail, str) else "request could not be served"
        return _render(request, exc.status_code, code, detail)

    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        return _render(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "an unexpected error occurred",
        )

    app.add_exception_handler(ApiError, handle_api_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, handle_validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, handle_unexpected)
