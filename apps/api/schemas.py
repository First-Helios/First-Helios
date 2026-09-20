"""Pydantic v2 wire models for the read API (ADR-0008).

The wire format is a contract, kept deliberately separate from the SQLAlchemy
ORM: a column rename must not silently become a breaking API change. Field names
are ``snake_case``; timestamps serialize as ISO-8601 UTC.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


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


class VenueList(BaseModel):
    """A cursor-paginated page of venues; ``next_cursor`` is null on the last."""

    items: list[VenueResponse]
    next_cursor: str | None


class ErrorResponse(BaseModel):
    """The uniform error body returned by every non-2xx response."""

    detail: str
    code: str
    trace_id: str
