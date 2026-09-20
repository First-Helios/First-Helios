"""Dev seed so the read endpoints return real data before discovery exists.

Phase 2 "First Light" proves the DB -> API -> deploy path; there is no venue
discovery yet (Phase 4), so this inserts a small, fixed set of Austin venues via
the published Identity commands. Not production code and not idempotent -- point
it at a dev/`*_test` database. Run: ``python -m apps.api.seed``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from packages.helios_core.db.session import get_sessionmaker
from packages.helios_core.identity.commands import (
    create_establishment,
    create_organization,
    create_place,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class _SampleVenue:
    name: str
    organization_kind: str
    address: str
    latitude: str
    longitude: str
    operating_status: str


_SAMPLE_VENUES: tuple[_SampleVenue, ...] = (
    _SampleVenue(
        "Franklin Barbecue",
        "brand",
        "900 E 11th St, Austin, TX 78702",
        "30.2701",
        "-97.7313",
        "open",
    ),
    _SampleVenue(
        "Torchy's Tacos", "brand", "1311 S 1st St, Austin, TX 78704", "30.2515", "-97.7548", "open"
    ),
    _SampleVenue(
        "Home Slice Pizza",
        "operating_identity",
        "1415 S Congress Ave, Austin, TX 78704",
        "30.2489",
        "-97.7500",
        "open",
    ),
    _SampleVenue(
        "Veracruz All Natural",
        "operating_identity",
        "1704 E Cesar Chavez St, Austin, TX 78702",
        "30.2596",
        "-97.7248",
        "open",
    ),
    _SampleVenue(
        "Kerbey Lane Cafe",
        "brand",
        "3704 Kerbey Ln, Austin, TX 78731",
        "30.3079",
        "-97.7559",
        "unknown",
    ),
)


def seed_sample_venues(session: Session) -> list[int]:
    """Create the sample venues and return their Establishment subject ids.

    Flushes but does not commit; the caller owns the transaction.
    """
    valid_from = datetime(2024, 1, 1, tzinfo=UTC)
    created: list[int] = []
    for venue in _SAMPLE_VENUES:
        organization = create_organization(
            session,
            canonical_name=venue.name,
            name_fingerprint=venue.name.lower().replace(" ", ""),
            organization_kind=venue.organization_kind,
        )
        place = create_place(
            session,
            address=venue.address,
            latitude=Decimal(venue.latitude),
            longitude=Decimal(venue.longitude),
        )
        establishment = create_establishment(
            session,
            organization_subject_id=organization.id,
            place_subject_id=place.id,
            valid_from=valid_from,
            operating_status=venue.operating_status,
        )
        created.append(establishment.id)
    return created


def main() -> None:
    """Seed a dev database and commit."""
    with get_sessionmaker()() as session:
        ids = seed_sample_venues(session)
        session.commit()
    print(f"seeded {len(ids)} venues: {ids}")  # noqa: T201 - dev CLI output


if __name__ == "__main__":
    main()
