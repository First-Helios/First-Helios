"""Committed fixtures and independent inventories for provider contract tests."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import text

from packages.helios_core.identity import (
    DecisionMetadata,
    SubjectChange,
    SubjectChangeMember,
    admit_source_record,
    assign_source_record,
    create_adjudication,
    create_establishment,
    create_organization,
    create_place,
    mark_subject_eligible,
)
from packages.helios_core.identity.contracts import ResolvedScopeRequest
from packages.helios_core.provenance.contracts import (
    BronzeObservation,
    PersistedBronzeObservation,
    persist_source_record_observation,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

PROVIDER_FUNCTIONS = {
    "bronze": {
        "capture_business_key",
        "record_version_info",
        "evidence_info",
        "evidence_supports_version",
    },
    "identity": {
        "scope_dependencies",
        "subject_feature_ready",
        "has_pending_lineage",
        "lock_scope_inputs",
        "require_resolved_scopes",
    },
}
PARENT = "91f4c2a7d6e8"
HEAD = "b72e6a90c431"


def migrate(*args: str) -> str:
    return subprocess.run(
        ["alembic", *args], env=os.environ.copy(), check=True, capture_output=True, text=True
    ).stdout


def decision() -> DecisionMetadata:
    return DecisionMetadata(
        confidence=Decimal("1"),
        method="provider-test",
        method_version="1",
        actor_class="rule",
        decided_at=datetime.now(UTC),
        effective_at=datetime.now(UTC),
    )


def observation() -> BronzeObservation:
    token = uuid4().hex
    return BronzeObservation(
        source_namespace=f"provider-{token}",
        source_kind="fixture",
        external_key=token,
        observed_at=datetime.now(UTC),
        content_hash=f"sha256:{token}",
        source_payload={"id": token},
        evidence_locator="$.id",
        evidence_excerpt_hash=f"sha256:evidence-{token}",
        canonical_url=f"https://{token}.example.test/menu",
        capture_content_hash=f"sha256:capture-{token}",
        bundle_path=f"fixture/{token}",
    )


@dataclass(frozen=True)
class ScopeFixture:
    organization: ResolvedScopeRequest
    establishment: ResolvedScopeRequest
    place_id: int
    shared_input: PersistedBronzeObservation
    local_input: PersistedBronzeObservation


def seed_scope(session: Session) -> ScopeFixture:
    """Caller commits before any tested provider admission."""
    shared = persist_source_record_observation(session, observation())
    local = persist_source_record_observation(session, observation())
    place = create_place(session, address="123 Test Street")
    mark_subject_eligible(session, place.id)
    org = create_organization(session, canonical_name="Test", name_fingerprint="test")
    admit_source_record(
        session,
        source_record_id=shared.source_record_id,
        decision=decision(),
        evidence_ids=(shared.evidence_id,),
    )
    org_event = assign_source_record(
        session,
        source_record_id=shared.source_record_id,
        to_subject_id=org.id,
        decision=decision(),
        evidence_ids=(shared.evidence_id,),
    )
    establishment = create_establishment(
        session,
        organization_subject_id=org.id,
        place_subject_id=place.id,
        valid_from=datetime(2020, 1, 1, tzinfo=UTC),
        operating_status="closed",
    )
    mark_subject_eligible(session, establishment.id)
    admit_source_record(
        session,
        source_record_id=local.source_record_id,
        decision=decision(),
        evidence_ids=(local.evidence_id,),
    )
    local_event = assign_source_record(
        session,
        source_record_id=local.source_record_id,
        to_subject_id=establishment.id,
        decision=decision(),
        evidence_ids=(local.evidence_id,),
    )
    return ScopeFixture(
        ResolvedScopeRequest(org.id, shared.source_record_id, org_event.id),
        ResolvedScopeRequest(establishment.id, local.source_record_id, local_event.id),
        place.id,
        shared,
        local,
    )


def pending_change(
    session: Session,
    subject_id: int,
    kind: str,
    operation: str = "retire",
    *,
    members: bool = True,
) -> SubjectChange:
    adjudication = create_adjudication(
        session, actor="fixture", rationale="provider test", decided_at=datetime.now(UTC)
    )
    change = SubjectChange(
        operation=operation,
        adjudication_id=adjudication.id,
        confidence=Decimal("1"),
        method="provider-test",
        method_version="1",
        actor_class="human",
        decided_at=datetime.now(UTC),
        effective_at=datetime.now(UTC),
    )
    session.add(change)
    session.flush()
    if members:
        session.add(
            SubjectChangeMember(
                subject_change_id=change.id,
                subject_id=subject_id,
                subject_kind=kind,
                role="input",
            )
        )
        session.flush()
    return change


def raw_admit(session: Session, *requests: ResolvedScopeRequest) -> list[dict[str, object]]:
    return [
        dict(row)
        for row in session.execute(
            text(
                "SELECT * FROM identity.require_resolved_scopes("
                "CAST(:s AS bigint[]), CAST(:r AS bigint[]), CAST(:e AS bigint[]))"
            ),
            {
                "s": [r.subject_id for r in requests],
                "r": [r.source_record_id for r in requests],
                "e": [r.resolution_event_id for r in requests],
            },
        ).mappings()
    ]
