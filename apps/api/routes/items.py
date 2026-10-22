"""Menu item price-history endpoint (ADR-0018 §B; ADR-0008 Amendment 3).

``GET /v1/items/{item_id}/price-history`` serves the accepted observation trail
behind one menu node's prices. Gold holds current answers only, so the trail is
read from committed Menu through
:func:`packages.helios_core.domains.menu.history.price_history`, the selector's
history mode; this route only decodes the id and shapes the wire.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any, cast

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session  # noqa: TC002 - FastAPI resolves this at runtime for Depends

from apps.api.db import get_session
from apps.api.errors import NotFoundError
from apps.api.item_ids import decode_item_id
from apps.api.schemas import (
    ErrorResponse,
    PriceHistoryPointResponse,
    PriceHistoryResponse,
    PriceTrailResponse,
)
from packages.helios_core.domains.menu.history import price_history
from packages.helios_core.domains.menu.selection import TargetRef

if TYPE_CHECKING:
    from apps.api.schemas import HistoryState, SourceKind
    from packages.helios_core.domains.menu.contracts import NodeKind
    from packages.helios_core.domains.menu.history import HistoryPoint, PriceTrail

router = APIRouter(prefix="/items", tags=["items"])

# Real item_ids are about 150-300 characters (ADR-0018 §B4); this only bounds
# the work a junk path can cause.
_MAX_ITEM_ID_LENGTH = 4096

_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {
        "model": ErrorResponse,
        "description": "The item_id names no target its scope ever priced.",
    },
    422: {"model": ErrorResponse, "description": "item_id is malformed."},
}


def _point(point: HistoryPoint) -> PriceHistoryPointResponse:
    return PriceHistoryPointResponse(
        known_from=point.known_from,
        state=cast("HistoryState", point.state),
        amount_minor=point.amount_minor,
        observed_at=point.observed_at,
        source_kind=cast("SourceKind | None", point.source_kind),
        confidence=float(point.confidence) if point.confidence is not None else None,
    )


def _trail(trail: PriceTrail) -> PriceTrailResponse:
    context = trail.context
    return PriceTrailResponse(
        channel=context.channel,
        service_period=context.service_period,
        valid_from=context.valid_from,
        valid_to=context.valid_to,
        currency_code=trail.currency_code,
        points=[_point(point) for point in trail.points],
    )


@router.get(
    "/{item_id}/price-history",
    response_model=PriceHistoryResponse,
    summary="Get the accepted price trail behind a menu node",
    responses=_RESPONSES,
)
def get_price_history(
    item_id: Annotated[str, Path(min_length=1, max_length=_MAX_ITEM_ID_LENGTH)],
    session: Annotated[Session, Depends(get_session)],
) -> PriceHistoryResponse:
    """Return one trail per effective context and currency, oldest point first.

    ``item_id`` is the ``id`` of a node in ``GET /v1/venues/{id}/menu``. A point
    is emitted each time a newly accepted page changed the node's accepted local
    answer: its state, amount and the page it came from. A trail usually ends
    ``absent`` once a newer capture of the menu is accepted: each capture's
    nodes are their own targets, so the trail shows when a price was accepted,
    corrected, withdrawn or superseded, not the dish's price across captures.
    Computed live from committed Menu, so ``as_of`` is the request instant and
    the item keeps its history after it leaves the current menu.
    """
    item = decode_item_id(item_id)
    trails = price_history(
        session,
        subject_id=item.subject_id,
        subject_kind=item.subject_kind,
        source_record_id=item.source_record_id,
        root_key=item.root_key,
        target=TargetRef(kind=cast("NodeKind", item.target_kind), native_path=item.target_path),
    )
    if trails is None:
        raise NotFoundError("item not found")
    return PriceHistoryResponse(
        item_id=item_id,
        as_of=datetime.now(UTC),
        trails=[_trail(trail) for trail in trails],
    )
