"""Database-backed smoke test for the ORM models.

Exercises the Postgres service that CI spins up. The `session` fixture (see
`conftest.py`) applies migrations, wraps each test in a transaction, and skips
cleanly when no test database is reachable.

Constraint-level tests for the venue-identity graph live in
`test_venue_identity_schema.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from packages.helios_core.db.models import Venue

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def test_venue_round_trip(session: Session) -> None:
    venue = Venue(
        name="Torchy's Tacos",
        address_raw="1822 S Congress Ave, Austin, TX 78704",
        street="1822 S Congress Ave",
        city="Austin",
        region="TX",
        postal_code="78704",
        country="US",
        lat=30.2472,
        lng=-97.7500,
    )
    session.add(venue)
    session.commit()
    session.refresh(venue)

    assert venue.id is not None
    assert venue.created_at is not None
    assert venue.updated_at is not None
    # Server-side defaults, not Python-side ones.
    assert venue.status == "unknown"
    assert venue.first_seen_at is not None
    assert venue.last_seen_at is not None

    fetched = session.execute(select(Venue).filter_by(name="Torchy's Tacos")).scalar_one()
    assert fetched.address_raw is not None
    assert fetched.address_raw.endswith("Austin, TX 78704")
    assert fetched.city == "Austin"
