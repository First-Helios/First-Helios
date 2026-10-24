"""The ``boundary`` query parameter: a drawn area, ``lat,lon;lat,lon;…`` (ADR-0020 §1).

One parser and one ray cast serve every endpoint that takes a boundary (the
price index's area summary and items, and the venue list), so they can never
disagree on which points a boundary holds.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Query, status

from apps.api.errors import ApiError
from packages.helios_core.gold.price_index import Boundary, BoundaryError, parse_boundary


class InvalidBoundaryError(ApiError):
    """A ``boundary`` that breaks a rule of ADR-0020 §1; ``detail`` names the rule."""

    def __init__(self, detail: str) -> None:
        super().__init__(status.HTTP_422_UNPROCESSABLE_CONTENT, "validation_error", detail)


BOUNDARY_DESCRIPTION = (
    "A drawn area: 3-50 corners as lat,lon pairs separated by ';' (WGS 84 degrees, plain "
    "decimals with at most 6 decimals), in any order or orientation; a final corner equal "
    "to the first is dropped. At most 1,200 characters and a bounding box of at most 2° of "
    "latitude and of longitude. A point is inside by even-odd ray casting, so a boundary "
    "that crosses itself is accepted; on an axis-aligned rectangle the south and west edges "
    "are inside and the north and east edges are not."
)

BoundaryQuery = Annotated[str, Query(description=BOUNDARY_DESCRIPTION)]


def boundary_param(value: str) -> Boundary:
    """Parse a ``boundary`` parameter, or raise :class:`InvalidBoundaryError` (422)."""
    try:
        return parse_boundary(value)
    except BoundaryError as exc:
        raise InvalidBoundaryError(str(exc)) from exc
