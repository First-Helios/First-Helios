"""Venue read endpoints (ADR-0008; ROADMAP Phase 2 "First Light").

A venue is a projection of ``identity.establishment`` -- one Organization
operating at one Place. Only current (non-retired) Establishments are served;
``operating_status`` is surfaced, never used to silently hide a closed venue.
Reads Identity models directly (``apps`` is the composition root, ADR-0004); it
never mutates them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import select
from sqlalchemy.orm import Session  # noqa: TC002 - FastAPI resolves this at runtime for Depends

from apps.api.db import get_session
from apps.api.errors import NotFoundError
from apps.api.pagination import BIGINT_MAX, DEFAULT_LIMIT, MAX_LIMIT, decode_cursor, encode_cursor
from apps.api.schemas import ErrorResponse, VenueList, VenueResponse
from packages.helios_core.identity.models import (
    Establishment,
    Organization,
    Place,
    SubjectCurrentness,
)

if TYPE_CHECKING:
    from sqlalchemy import Select

router = APIRouter(prefix="/venues", tags=["venues"])

# Documented per ADR-0008 SS4 error contract (R37): a malformed/overflowing
# ``cursor`` maps to 400, and both routes' query/path validation maps to 422.
_LIST_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "The cursor is malformed."},
    422: {"model": ErrorResponse, "description": "A query parameter failed validation."},
}
_GET_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "No current venue has this id."},
    422: {"model": ErrorResponse, "description": "venue_id is out of range."},
}


def _to_venue(
    establishment: Establishment, organization: Organization, place: Place
) -> VenueResponse:
    return VenueResponse(
        id=establishment.subject_id,
        name=organization.canonical_name,
        organization_kind=organization.organization_kind,
        address=place.address,
        latitude=float(place.latitude) if place.latitude is not None else None,
        longitude=float(place.longitude) if place.longitude is not None else None,
        operating_status=establishment.operating_status,
        valid_from=establishment.valid_from,
        valid_to=establishment.valid_to,
    )


def _current_venue_select() -> Select[tuple[Establishment, Organization, Place]]:
    return (
        select(Establishment, Organization, Place)
        .join(Organization, Organization.subject_id == Establishment.organization_subject_id)
        .join(Place, Place.subject_id == Establishment.place_subject_id)
        .join(SubjectCurrentness, SubjectCurrentness.subject_id == Establishment.subject_id)
        .where(SubjectCurrentness.is_current.is_(True))
    )


@router.get(
    "",
    response_model=VenueList,
    summary="List venues (cursor-paginated)",
    responses=_LIST_RESPONSES,
)
def list_venues(
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query()] = None,
) -> VenueList:
    """Return one page of current venues ordered by id, with an opaque cursor."""
    after = decode_cursor(cursor) if cursor is not None else None
    statement = _current_venue_select()
    if after is not None:
        statement = statement.where(Establishment.subject_id > after)
    statement = statement.order_by(Establishment.subject_id).limit(limit + 1)
    rows = session.execute(statement).tuples().all()

    has_more = len(rows) > limit
    page = rows[:limit]
    items = [
        _to_venue(establishment, organization, place) for establishment, organization, place in page
    ]
    next_cursor = encode_cursor(page[-1][0].subject_id) if has_more and page else None
    return VenueList(items=items, next_cursor=next_cursor)


@router.get(
    "/{venue_id}",
    response_model=VenueResponse,
    summary="Get one venue by id",
    responses=_GET_RESPONSES,
)
def get_venue(
    venue_id: Annotated[int, Path(ge=0, le=BIGINT_MAX)],
    session: Annotated[Session, Depends(get_session)],
) -> VenueResponse:
    """Return a single current venue, or 404 if no such current Establishment."""
    statement = _current_venue_select().where(Establishment.subject_id == venue_id)
    row = session.execute(statement).tuples().one_or_none()
    if row is None:
        raise NotFoundError(f"venue {venue_id} not found")
    establishment, organization, place = row
    return _to_venue(establishment, organization, place)
