"""Venue read endpoints (ADR-0008; ROADMAP Phase 2 "First Light", Phase 7 menu).

A venue is a projection of ``identity.establishment`` -- one Organization
operating at one Place. Only current (non-retired) Establishments are served;
closed/expired venues and venues with non-current parents are hidden (ADR-0012).
Reads Identity models directly (``apps`` is the composition root, ADR-0004); it
never mutates them. A venue's menu is read from ``gold.current_menu`` through
:mod:`packages.helios_core.gold.menu_read` (ADR-0008 §9).

The list's filters (ADR-0018 §A) are each one index-backed predicate:
``has_menu`` a semi-join on ``ix_gold_current_menu_scope``, ``organization``
``ix_establishment_organization_subject_id``, and ``area`` a price-index cell
range on ``ix_place_latitude_longitude``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Annotated, Any, cast

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy import and_, exists, func, not_, or_, select
from sqlalchemy.orm import (
    Session,  # noqa: TC002 - FastAPI resolves this at runtime for Depends
    aliased,
)

from apps.api.db import get_session
from apps.api.errors import ApiError, NotFoundError
from apps.api.item_ids import ItemId, encode_item_id
from apps.api.pagination import BIGINT_MAX, DEFAULT_LIMIT, MAX_LIMIT, decode_cursor, encode_cursor
from apps.api.schemas import (
    AreaKind,
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
from packages.helios_core.gold.menu_read import (
    CurrentMenuRow,
    MenuFamily,
    current_menu_rows,
    has_served_menu,
    menu_family,
    menu_source_urls,
)
from packages.helios_core.gold.price_index import ALL_AREA, AREA_KIND, GRID_STEPS, grid_cell
from packages.helios_core.identity.models import (
    Establishment,
    Organization,
    Place,
    SubjectCurrentness,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import ColumnElement, Select
    from sqlalchemy.orm.util import AliasedClass

    from apps.api.schemas import Channel, MenuScope, PriceState, SourceKind

router = APIRouter(prefix="/venues", tags=["venues"])

# Documented per ADR-0008 SS4 error contract (R37): a malformed/overflowing
# ``cursor`` maps to 400, and both routes' query/path validation maps to 422.
_LIST_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "The cursor is malformed."},
    422: {
        "model": ErrorResponse,
        "description": "A query parameter failed validation, area is not a canonical "
        "area_key of area_kind, or area_kind is given without area.",
    },
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
        organization_id=organization.subject_id,
        organization_kind=organization.organization_kind,
        address=place.address,
        latitude=float(place.latitude) if place.latitude is not None else None,
        longitude=float(place.longitude) if place.longitude is not None else None,
        operating_status=establishment.operating_status,
        valid_from=establishment.valid_from,
        valid_to=establishment.valid_to,
    )


def _current_venue_select(
    establishment: type[Establishment] | AliasedClass[Establishment] = Establishment,
    organization: type[Organization] | AliasedClass[Organization] = Organization,
    place: type[Place] | AliasedClass[Place] = Place,
) -> Select[tuple[Establishment, Organization, Place]]:
    """Current venues; pass aliases to correlate a second copy as a subquery."""
    current = aliased(SubjectCurrentness)
    org_current = aliased(SubjectCurrentness)
    place_current = aliased(SubjectCurrentness)
    return (
        select(establishment, organization, place)
        .join(organization, organization.subject_id == establishment.organization_subject_id)
        .join(place, place.subject_id == establishment.place_subject_id)
        .join(current, current.subject_id == establishment.subject_id)
        .join(org_current, org_current.subject_id == organization.subject_id)
        .join(place_current, place_current.subject_id == place.subject_id)
        .where(
            current.is_current.is_(True),
            org_current.is_current.is_(True),
            place_current.is_current.is_(True),
            establishment.operating_status != "closed",
            or_(establishment.valid_to.is_(None), establishment.valid_to > func.now()),
        )
    )


def _sole_current_venue() -> ColumnElement[bool]:
    """The listed venue is its Organization's one current venue (ADR-0005 §11)."""
    peer = aliased(Establishment)
    peer_select = (
        _current_venue_select(peer, aliased(Organization), aliased(Place))
        .with_only_columns(peer.subject_id)
        .where(
            peer.organization_subject_id == Establishment.organization_subject_id,
            peer.subject_id != Establishment.subject_id,
        )
    )
    return not_(exists(peer_select))


def _has_menu() -> ColumnElement[bool]:
    """``GET /v1/venues/{id}/menu`` would return a menu (ADR-0018 §A1)."""
    return or_(
        has_served_menu(Establishment.subject_id, "establishment"),
        and_(
            has_served_menu(Establishment.organization_subject_id, "organization"),
            _sole_current_venue(),
        ),
    )


class InvalidAreaError(ApiError):
    """An ``area`` that is not a canonical price-index ``area_key`` of its ``area_kind``."""

    def __init__(self, detail: str = "area is not a canonical area_key of area_kind") -> None:
        super().__init__(status.HTTP_422_UNPROCESSABLE_CONTENT, "validation_error", detail)


def _area_cell(area: str, step: Decimal) -> tuple[Decimal, Decimal]:
    """The south-west corner of a canonical ``area_key`` ("30.26,-97.75") at ``step``."""
    parts = area.split(",")
    if len(parts) != 2:
        raise InvalidAreaError
    try:
        latitude, longitude = Decimal(parts[0]), Decimal(parts[1])
    except InvalidOperation as exc:
        raise InvalidAreaError from exc
    if not (latitude.is_finite() and longitude.is_finite()):
        raise InvalidAreaError
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise InvalidAreaError
    key, cell_lat, cell_lon = grid_cell(latitude, longitude, step)
    if key != area:
        raise InvalidAreaError
    return cell_lat, cell_lon


def _in_area(area_kind: str, area: str) -> ColumnElement[bool]:
    """The venue's Place point lies in the area, the rule the refresh places by.

    A grid cell is the half-open range ``grid_cell`` floors into; ``all`` is
    every Place with a point (ADR-0007 Amendment 3, OQ2).
    """
    if area_kind == ALL_AREA:
        if area != ALL_AREA:
            raise InvalidAreaError
        return and_(Place.latitude.is_not(None), Place.longitude.is_not(None))
    step = GRID_STEPS[area_kind]
    cell_lat, cell_lon = _area_cell(area, step)
    return and_(
        Place.latitude >= cell_lat,
        Place.latitude < cell_lat + step,
        Place.longitude >= cell_lon,
        Place.longitude < cell_lon + step,
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
    has_menu: Annotated[
        bool | None,
        Query(
            description="Only venues whose menu endpoint would (true) or would not (false) "
            "return a menu, as of the last Gold refresh."
        ),
    ] = None,
    organization: Annotated[
        int | None,
        Query(ge=0, le=BIGINT_MAX, description="Only venues of this organization_id."),
    ] = None,
    area: Annotated[
        str | None,
        Query(
            max_length=64,
            description="Only venues whose point lies in this price-index area_key of "
            'area_kind (a cell named by its south-west corner, e.g. "30.26,-97.75"; '
            '"all" with area_kind=all, every venue with a point).',
        ),
    ] = None,
    area_kind: Annotated[
        AreaKind | None,
        Query(
            description="The price-index area kind area is a key of (default "
            "latlon_grid_0p01). Requires area."
        ),
    ] = None,
) -> VenueList:
    """Return one page of current venues ordered by id, with an opaque cursor.

    Filters are ANDed. The cursor does not carry them: send the same filters
    with every page. A filter that matches nothing is ``200`` with ``items: []``.
    The ``area`` list is geographic: every current venue whose point is in the
    area, not only the price index's contributors.
    """
    if area_kind is not None and area is None:
        raise InvalidAreaError("area_kind requires area")
    after = decode_cursor(cursor) if cursor is not None else None
    statement = _current_venue_select()
    if has_menu is not None:
        statement = statement.where(_has_menu() if has_menu else not_(_has_menu()))
    if organization is not None:
        statement = statement.where(Establishment.organization_subject_id == organization)
    if area is not None:
        statement = statement.where(_in_area(area_kind or AREA_KIND, area))
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


def _item_id(row: CurrentMenuRow) -> str:
    """The ``item_id`` of the target a Gold row prices (ADR-0018 §B4)."""
    return encode_item_id(
        ItemId(
            subject_kind=cast("MenuScope", row.subject_kind),
            subject_id=row.subject_id,
            source_record_id=row.source_record_id,
            root_key=row.root_key,
            target_path=row.target_path,
        )
    )


def _option(
    options: dict[_Path, MenuOptionResponse],
    row: CurrentMenuRow,
    parent: list[MenuOptionResponse],
) -> MenuOptionResponse:
    """The variant/modifier ``row`` prices, created under ``parent`` on first sight."""
    path = row.target_path
    option = options.get(path)
    if option is None:
        option = options[path] = MenuOptionResponse(
            id=_item_id(row), key=path[-1][1], name=None, prices=[]
        )
        parent.append(option)
    return option


def _shape_menu(rows: Sequence[CurrentMenuRow], now: datetime) -> list[MenuSectionResponse]:
    """Nest one family's rows by native path: sections -> items -> variants.

    Groups by the full native path (a pinned-base prefix included), so equal keys
    under different parents never merge; the wire ``key`` is the node's own
    native key. Nested sections are listed flat, each under its innermost key.
    A section or item takes its name from its rows' ``section_name`` /
    ``item_name`` (ADR-0006 Amendment 1), which every row on its path carries,
    else from its own row's ``content_name``; first non-null in row order.
    ``id`` comes only from a node's own Gold row: a node with no row of its own
    has none.
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
                id=None, key=section_path[-1][1], name=None, prices=[], items=[], modifiers=[]
            )
        section.name = section.name or row.section_name
        rest = path[last_section + 1 :]
        price = _price(row, now)
        if not rest:  # a section-level price
            section.id = section.id or _item_id(row)
            section.name = section.name or row.content_name
            section.prices.append(price)
            continue
        if rest[0][0] == "modifier":  # a section-level modifier
            option = _option(options, row, section.modifiers)
            option.name = option.name or row.content_name
            option.prices.append(price)
            continue
        item_path = path[: last_section + 2]
        item = items.get(item_path)
        if item is None:
            item = items[item_path] = MenuItemResponse(
                id=None,
                key=item_path[-1][1],
                name=None,
                description=None,
                prices=[],
                variants=[],
                modifiers=[],
            )
            section.items.append(item)
        item.name = item.name or row.item_name
        if len(rest) == 1:  # the item's own price
            item.id = item.id or _item_id(row)
            item.name = item.name or row.content_name
            item.description = item.description or row.content_description
            item.prices.append(price)
            continue
        parent = item.variants if rest[1][0] == "variant" else item.modifiers
        option = _option(options, row, parent)
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
    refresh instant behind the served rows. Each menu's ``source_url`` is the
    page its most recent price was read from, resolved at request time in one
    provenance read for the whole request (ADR-0008 Amendment 4). A current
    venue with no menu in Gold is ``200`` with ``menus: []``.
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
    families: dict[MenuFamily, list[CurrentMenuRow]] = {}
    for row in rows:
        families.setdefault(menu_family(row), []).append(row)
    source_urls = menu_source_urls(session, rows)
    menus = [
        MenuResponse(
            scope=cast("MenuScope", family[0]),
            source_url=source_urls[family],
            sections=_shape_menu(family_rows, now),
        )
        for family, family_rows in families.items()
    ]
    as_of = min((row.effective_instant for row in rows), default=None)
    return VenueMenuResponse(venue_id=venue_id, as_of=as_of, menus=menus)
