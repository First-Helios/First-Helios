"""Database-backed smoke test for the active bounded-context models.

Exercises the Postgres service that CI spins up. The `session` fixture (see
`conftest.py`) applies migrations, wraps each test in a transaction, and skips
locally when no test database is reachable. Strict mode fails instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import select

from packages.helios_core.identity import Organization, create_organization
from packages.helios_core.provenance import Source

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def test_bronze_and_identity_round_trip(session: Session) -> None:
    namespace = f"smoke-{uuid4().hex}"
    source = Source(namespace=namespace, kind="smoke")
    organization = create_organization(
        session,
        canonical_name="Smoke Test Organization",
        name_fingerprint=f"smoke-{uuid4().hex}",
    )
    session.add(source)
    session.commit()

    fetched_source = session.scalar(select(Source).where(Source.namespace == namespace))
    fetched_organization = session.get(Organization, organization.id)
    assert fetched_source is not None
    assert fetched_organization is not None
    assert fetched_organization.subject_id == organization.id
