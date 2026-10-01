"""Venue read endpoints (ADR-0008; ROADMAP Phase 2 "First Light", Phase 7 menu).

A venue is a projection of ``identity.establishment`` -- one Organization
operating at one Place. Only current (non-retired) Establishments are served;
closed/expired venues and venues with non-current parents are hidden (ADR-0012).
Reads Identity models directly (``apps`` is the composition root, ADR-0004); it
never mutates them. A venue's menu is read from ``gold.current_menu`` through
:mod:`packages.helios_core.gold.menu_read` (ADR-0008 §9).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any, cast

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import (
    Session,  # noqa: TC002 - FastAPI resolves this at runtime for Depends
    aliased,
)

from apps.api.db import get_session
from apps.api.errors import NotFoundError
from apps.api.pagination import BIGINT_MAX, DEFAULT_LIMIT, MAX_LIMIT, decode_cursor, encode_cursor
from apps.api.schemas import (
    ErrorResponse,
    MenuItemResponse,
    MenuOptionResponse,
    MenuPriceResponse,
    MenuResponse,
    MenuSectionResponse,
    VenueList,
    VenueMenuResponse,
    VenueResponse,
)
from packages.helios_core.gold.menu_read import CurrentMenuRow, current_menu_rows
from packages.helios_core.identity.models import (
    Establishment,
    Organization,
    Place,
    SubjectCurrentness,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import Select

    from apps.api.schemas import Channel, MenuScope, PriceState, SourceKind

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
    org_current = aliased(SubjectCurrentness)
    place_current = aliased(SubjectCurrentness)
    return (
        select(Establishment, Organization, Place)
        .join(Organization, Organization.subject_id == Establishment.organization_subject_id)
        .join(Place, Place.subject_id == Establishment.place_subject_id)
        .join(SubjectCurrentness, SubjectCurrentness.subject_id == Establishment.subject_id)
        .join(org_current, org_current.subject_id == Organization.subject_id)
        .join(place_current, place_current.subject_id == Place.subject_id)
        .where(
            SubjectCurrentness.is_current.is_(True),
            org_current.is_current.is_(True),
            place_current.is_current.is_(True),
            Establishment.operating_status != "closed",
            or_(Establishment.valid_to.is_(None), Establishment.valid_to > func.now()),
        )
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


_MENU_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "No current venue has this id."},
    422: {"model": ErrorResponse, "description": "venue_id is out of range."},
}

_Path = tuple[tuple[str, str], ...]


def _price(row: CurrentMenuRow, now: datetime) -> MenuPriceResponse:
    observed = row.price_observed_at
    return MenuPriceResponse(
        state=cast("PriceState", row.price_state),
        amount_minor=row.amount_minor,
        currency_code=row.currency_code,
        channel=cast("Channel", row.channel),
        service_period=row.service_period,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        observed_at=observed,
        # An age: an observation after the request instant is fresh, not negative.
        age_seconds=max(0, int((now - observed).total_seconds())) if observed else None,
        source_kind=cast("SourceKind | None", row.price_source_kind),
        confidence=float(row.price_confidence) if row.price_confidence is not None else None,
    )


def _option(
    options: dict[_Path, MenuOptionResponse], path: _Path, parent: list[MenuOptionResponse]
) -> MenuOptionResponse:
    """The variant/modifier at ``path``, created under ``parent`` on first sight."""
    option = options.get(path)
    if option is None:
        option = options[path] = MenuOptionResponse(key=path[-1][1], name=None, prices=[])
        parent.append(option)
    return option


def _shape_menu(rows: Sequence[CurrentMenuRow], now: datetime) -> list[MenuSectionResponse]:
    """Nest one family's rows by native path: sections -> items -> variants.

    Groups by the full native path (a pinned-base prefix included), so equal keys
    under different parents never merge; the wire ``key`` is the node's own
    native key. Nested sections are listed flat, each under its innermost key.
    Names come only from a node's own Gold row (first one in row order).
    """
    sections: dict[_Path, MenuSectionResponse] = {}
    items: dict[_Path, MenuItemResponse] = {}
    options: dict[_Path, MenuOptionResponse] = {}
    for row in rows:
        path = row.target_path
        last_section = max(i for i, (kind, _) in enumerate(path) if kind == "section")
        section_path = path[: last_section + 1]
        section = sections.get(section_path)
        if section is None:
            section = sections[section_path] = MenuSectionResponse(
                key=section_path[-1][1], name=None, prices=[], items=[], modifiers=[]
            )
        rest = path[last_section + 1 :]
        price = _price(row, now)
        if not rest:  # a section-level price
            section.name = section.name or row.content_name
            section.prices.append(price)
            continue
        if rest[0][0] == "modifier":  # a section-level modifier
            option = _option(options, path, section.modifiers)
            option.name = option.name or row.content_name
            option.prices.append(price)
            continue
        item_path = path[: last_section + 2]
        item = items.get(item_path)
        if item is None:
            item = items[item_path] = MenuItemResponse(
                key=item_path[-1][1],
                name=None,
                description=None,
                prices=[],
                variants=[],
                modifiers=[],
            )
            section.items.append(item)
        if len(rest) == 1:  # the item's own price
            item.name = item.name or row.content_name
            item.description = item.description or row.content_description
            item.prices.append(price)
            continue
        parent = item.variants if rest[1][0] == "variant" else item.modifiers
        option = _option(options, path, parent)
        option.name = option.name or row.content_name
        option.prices.append(price)
    return list(sections.values())


@router.get(
    "/{venue_id}/menu",
    response_model=VenueMenuResponse,
    summary="Get a venue's current menu",
    responses=_MENU_RESPONSES,
)
def get_venue_menu(
    venue_id: Annotated[int, Path(ge=0, le=BIGINT_MAX)],
    session: Annotated[Session, Depends(get_session)],
) -> VenueMenuResponse:
    """Return the venue's current menu from Gold, or 404 if no such current venue.

    The venue's own (Establishment) menus come first. Its Organization's menus
    follow, labelled ``organization``, only when this venue is the
    Organization's one current venue: a chain's shared menu is never fanned out
    to its locations (ADR-0005 §11). Every price carries ``observed_at``, its
    age at request time and its source kind; ``as_of`` is the oldest Gold
    refresh instant behind the served rows. A current venue with no menu in
    Gold is ``200`` with ``menus: []``.
    """
    venue = session.execute(
        _current_venue_select()
        .with_only_columns(Establishment.organization_subject_id)
        .where(Establishment.subject_id == venue_id)
    ).one_or_none()
    if venue is None:
        raise NotFoundError(f"venue {venue_id} not found")
    organization_id = venue.organization_subject_id
    organization_venues = session.scalar(
        select(func.count()).select_from(
            _current_venue_select()
            .with_only_columns(Establishment.subject_id)
            .where(Establishment.organization_subject_id == organization_id)
            .subquery()
        )
    )
    scopes = [(venue_id, "establishment")]
    if organization_venues == 1:
        scopes.append((organization_id, "organization"))

    rows = current_menu_rows(session, scopes)
    now = datetime.now(UTC)
    families: dict[tuple[str, int, str], list[CurrentMenuRow]] = {}
    for row in rows:
        families.setdefault((row.subject_kind, row.source_record_id, row.root_key), []).append(row)
    menus = [
        MenuResponse(scope=cast("MenuScope", kind), sections=_shape_menu(family, now))
        for (kind, _, _), family in families.items()
    ]
    as_of = min((row.effective_instant for row in rows), default=None)
    return VenueMenuResponse(venue_id=venue_id, as_of=as_of, menus=menus)
