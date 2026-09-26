"""Pydantic v2 wire models for the read API (ADR-0008).

The wire format is a contract, kept deliberately separate from the SQLAlchemy
ORM: a column rename must not silently become a breaking API change. Field names
are ``snake_case``; timestamps serialize as ISO-8601 UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, WithJsonSchema, field_serializer

#: A custom serializer's own return-type annotation drives the published
#: schema for that field in serialization mode (pydantic ignores the field's
#: declared type there), so a bare ``str``/``str | None`` return type would
#: drop the ``format: date-time`` hint OpenAPI consumers rely on. Carry it on
#: the return annotation instead so the documented schema doesn't regress
#: (R37).
_DateTimeStr = Annotated[str, WithJsonSchema({"type": "string", "format": "date-time"})]

#: Stable, documented error codes clients switch on (ADR-0008 SS4). Declared as
#: a Literal (not a bare ``str``) so both runtime validation and the published
#: OpenAPI schema enumerate the exact set (R37).
ErrorCode = Literal[
    "not_found",
    "validation_error",
    "invalid_cursor",
    "method_not_allowed",
    "service_unavailable",
    "internal_error",
]


def _utc_iso(value: datetime) -> str:
    """Render a datetime as ISO-8601 UTC with a literal ``Z`` offset.

    Naive datetimes are treated as already UTC (the DB stores UTC); aware
    datetimes are converted. Either way the wire format is always UTC,
    regardless of the DB session's ``TimeZone`` setting (R50).
    """
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")


class VenueResponse(BaseModel):
    """A venue: one Organization operating at one Place (an Establishment)."""

    id: int
    name: str | None
    organization_kind: str
    address: str | None
    latitude: float | None
    longitude: float | None
    operating_status: str
    valid_from: datetime
    valid_to: datetime | None

    @field_serializer("valid_from")
    def _serialize_valid_from(self, value: datetime) -> _DateTimeStr:
        return _utc_iso(value)

    @field_serializer("valid_to")
    def _serialize_valid_to(self, value: datetime | None) -> _DateTimeStr | None:
        return _utc_iso(value) if value is not None else None


class VenueList(BaseModel):
    """A cursor-paginated page of venues; ``next_cursor`` is null on the last."""

    items: list[VenueResponse]
    next_cursor: str | None


class ErrorResponse(BaseModel):
    """The uniform error body returned by every non-2xx response."""

    detail: str
    code: ErrorCode
    trace_id: str
