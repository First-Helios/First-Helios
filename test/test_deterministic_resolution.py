"""Plan 0002 Step 4 deterministic Bronze-first resolution behavior."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from packages.helios_core.identity import (
    CurrentResolution,
    DecisionMetadata,
    Organization,
    Place,
    ResolutionEvent,
    Subject,
    SubjectNotEligibleError,
    assign_source_record,
    create_establishment,
    create_organization,
    create_place,
    mark_subject_eligible,
    record_subject_change,
    remap_source_record,
    require_eligible_subject,
    resolve_source_record_observation,
    unassign_source_record,
)
from packages.helios_core.provenance import (
    BronzeObservation,
    Capture,
    Evidence,
    Source,
    SourceRecord,
    SourceRecordVersion,
    canonicalize_http_url,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from sqlalchemy.orm import Session


def _observation(
    *,
    namespace: str,
    external_key: str,
    observed_at: datetime | None = None,
    canonical_url: str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> BronzeObservation:
    token = uuid4().hex
    return BronzeObservation(
        source_namespace=namespace,
        source_kind="discovery",
        external_key=external_key,
        observed_at=observed_at or datetime.now(UTC),
        content_hash=f"sha256:record-{token}",
        source_payload=dict(payload or {"id": external_key, "name": "Source Name"}),
        evidence_locator="$",
        evidence_excerpt_hash=f"sha256:evidence-{token}",
        canonical_url=canonical_url,
        endpoint_kind="https",
        capture_content_hash=f"sha256:capture-{token}",
        bundle_path=f"captures/{token}.json",
    )


def _decision(method: str = "test-explicit-resolution") -> DecisionMetadata:
    now = datetime.now(UTC)
    return DecisionMetadata(
        confidence=Decimal("1"),
        method=method,
        method_version="1",
        actor_class="rule",
        decided_at=now,
        effective_at=now,
    )


def test_canonical_url_normalization_is_exact_and_conservative() -> None:
    assert canonicalize_http_url(" HTTPS://Example.COM:443 ") == "https://example.com/"
    assert (
        canonicalize_http_url("http://Example.COM:8080/A/?b=2&a=1#section")
        == "http://example.com:8080/A/?b=2&a=1"
    )
    assert canonicalize_http_url("https://example.com/A") != canonicalize_http_url(
        "https://example.com/a"
    )
    assert canonicalize_http_url("https://example.com/a") != canonicalize_http_url(
        "https://example.com/a/"
    )


@pytest.mark.parametrize(
    "url",
    [
        "",
        "ftp://example.test/file",
        "https://user:secret@example.test/",
        "https://example.test/a path",
    ],
)
def test_canonical_url_rejects_unsafe_or_non_http_values(url: str) -> None:
    with pytest.raises(ValueError):
        canonicalize_http_url(url)


def test_unmatched_observation_is_bronze_first_and_explicitly_unresolved(
    session: Session,
) -> None:
    namespace = f"step4-unmatched-{uuid4().hex}"
    subject_count_before = session.scalar(select(func.count()).select_from(Subject))
    source_payload = {
        "id": "candidate-1",
        "name": "Source Spelling",
        "website": "HTTPS://Example.TEST:443/original#source-fragment",
        "nested": {"source": True, "values": [3, 1, 2]},
    }
    result = resolve_source_record_observation(
        session,
        observation=_observation(
            namespace=namespace,
            external_key="candidate-1",
            payload=source_payload,
        ),
        decided_at=datetime.now(UTC),
    )

    current = session.get(CurrentResolution, result.source_record_id)
    version = session.get(SourceRecordVersion, result.source_record_version_id)
    assert current is not None
    assert (result.state, current.state, current.subject_id) == (
        "unresolved",
        "unresolved",
        None,
    )
    assert result.match_basis is None
    assert len(result.appended_event_ids) == 1
    assert version is not None and version.source_payload == source_payload
    assert session.scalar(select(func.count()).select_from(Subject)) == subject_count_before, (
        "unmatched input must not manufacture a placeholder Subject"
    )


def test_external_key_reuses_stable_bronze_and_identity_rows(
    session: Session,
) -> None:
    namespace = f"step4-key-{uuid4().hex}"
    first_time = datetime.now(UTC)
    first = resolve_source_record_observation(
        session,
        observation=_observation(
            namespace=namespace,
            external_key="stable-key",
            observed_at=first_time,
            payload={"id": "stable-key", "revision": 1},
        ),
        decided_at=first_time,
    )
    target = create_organization(
        session,
        canonical_name="Stable Organization",
        name_fingerprint="stable organization",
    )
    assign_source_record(
        session,
        source_record_id=first.source_record_id,
        to_subject_id=target.id,
        decision=_decision(),
        evidence_ids=[first.evidence_id],
    )
    session.commit()

    second_time = first_time + timedelta(minutes=5)
    second = resolve_source_record_observation(
        session,
        observation=_observation(
            namespace=namespace,
            external_key="stable-key",
            observed_at=second_time,
            payload={"id": "stable-key", "revision": 2},
        ),
        decided_at=second_time,
    )

    assert second.source_id == first.source_id
    assert second.source_record_id == first.source_record_id
    assert not second.source_record_created
    assert second.state == "resolved"
    assert second.subject_id == target.id
    assert second.match_basis == "external_key"
    assert second.appended_event_ids == ()
    assert (
        session.scalar(
            select(func.count())
            .select_from(SourceRecordVersion)
            .where(SourceRecordVersion.source_record_id == first.source_record_id)
        )
        == 2
    )
    assert (
        session.scalar(
            select(func.count())
            .select_from(ResolutionEvent)
            .where(ResolutionEvent.source_record_id == first.source_record_id)
        )
        == 2
    )


def test_identical_observation_retry_reuses_immutable_bronze_rows(
    session: Session,
) -> None:
    observation = _observation(
        namespace=f"step4-retry-{uuid4().hex}",
        external_key="stable-key",
        canonical_url="https://retry.example.test/menu",
    )
    first = resolve_source_record_observation(
        session,
        observation=observation,
        decided_at=datetime.now(UTC),
    )
    retry = resolve_source_record_observation(
        session,
        observation=observation,
        decided_at=datetime.now(UTC),
    )

    assert first.observation_created
    assert not retry.observation_created
    assert (
        retry.capture_id,
        retry.source_record_version_id,
        retry.evidence_id,
    ) == (
        first.capture_id,
        first.source_record_version_id,
        first.evidence_id,
    )
    assert session.scalar(select(func.count()).select_from(Capture)) == 1
    assert session.scalar(select(func.count()).select_from(SourceRecordVersion)) == 1
    assert session.scalar(select(func.count()).select_from(Evidence)) == 1

    later = replace(observation, observed_at=observation.observed_at + timedelta(minutes=1))
    new_observation = resolve_source_record_observation(
        session,
        observation=later,
        decided_at=datetime.now(UTC),
    )
    assert new_observation.observation_created
    assert new_observation.source_record_version_id != first.source_record_version_id
    assert session.scalar(select(func.count()).select_from(SourceRecordVersion)) == 2


def test_unique_canonical_url_assigns_without_using_name_as_identity(
    session: Session,
) -> None:
    token = uuid4().hex
    namespace = f"step4-url-{token}"
    url = f"https://restaurant-{token}.example.test/menu"
    anchor = resolve_source_record_observation(
        session,
        observation=_observation(
            namespace=namespace,
            external_key="anchor",
            canonical_url=url,
        ),
        decided_at=datetime.now(UTC),
    )
    target = create_organization(
        session,
        canonical_name="Common Restaurant Name",
        name_fingerprint="common restaurant name",
        organization_kind="brand",
    )
    assign_source_record(
        session,
        source_record_id=anchor.source_record_id,
        to_subject_id=target.id,
        decision=_decision(),
        evidence_ids=[anchor.evidence_id],
    )
    session.commit()

    matched = resolve_source_record_observation(
        session,
        observation=_observation(
            namespace=namespace,
            external_key="new-record",
            canonical_url=url.upper().replace("/MENU", "/menu"),
            payload={"name": "A Different Source Spelling"},
        ),
        decided_at=datetime.now(UTC),
    )

    assert matched.state == "resolved"
    assert matched.subject_id == target.id
    assert matched.match_basis == "canonical_url"
    assert len(matched.appended_event_ids) == 2
    organization = session.get(Organization, target.id)
    subject = session.get(Subject, target.id)
    assert organization is not None
    assert subject is not None and subject.readiness == "eligible"


def test_ambiguous_canonical_url_never_assigns_by_url_alone(
    session: Session,
) -> None:
    token = uuid4().hex
    namespace = f"step4-ambiguous-{token}"
    url = f"https://shared-{token}.example.test/"
    first = resolve_source_record_observation(
        session,
        observation=_observation(
            namespace=namespace,
            external_key="first",
            canonical_url=url,
        ),
        decided_at=datetime.now(UTC),
    )
    first_subject = create_organization(session)
    assign_source_record(
        session,
        source_record_id=first.source_record_id,
        to_subject_id=first_subject.id,
        decision=_decision(),
        evidence_ids=[first.evidence_id],
    )

    second = resolve_source_record_observation(
        session,
        observation=_observation(
            namespace=namespace,
            external_key="second",
            canonical_url=url,
        ),
        decided_at=datetime.now(UTC),
    )
    assert second.subject_id == first_subject.id
    second_subject = create_organization(session)
    remap_source_record(
        session,
        source_record_id=second.source_record_id,
        from_subject_id=first_subject.id,
        to_subject_id=second_subject.id,
        decision=_decision("explicit-remap"),
        evidence_ids=[second.evidence_id],
    )
    session.commit()

    unmatched = resolve_source_record_observation(
        session,
        observation=_observation(
            namespace=namespace,
            external_key="third",
            canonical_url=url,
        ),
        decided_at=datetime.now(UTC),
    )
    current = session.get(CurrentResolution, unmatched.source_record_id)
    assert current is not None
    assert (unmatched.state, current.state, unmatched.subject_id) == (
        "unresolved",
        "unresolved",
        None,
    )
    assert unmatched.match_basis is None
    assert len(unmatched.appended_event_ids) == 1


def test_needs_review_survives_later_reobservation(
    session: Session,
) -> None:
    token = uuid4().hex
    namespace = f"step4-review-{token}"
    url = f"https://review-{token}.example.test/"
    anchor = resolve_source_record_observation(
        session,
        observation=_observation(
            namespace=namespace,
            external_key="anchor",
            canonical_url=url,
        ),
        decided_at=datetime.now(UTC),
    )
    target = create_organization(session)
    assign_source_record(
        session,
        source_record_id=anchor.source_record_id,
        to_subject_id=target.id,
        decision=_decision(),
        evidence_ids=[anchor.evidence_id],
    )
    candidate = resolve_source_record_observation(
        session,
        observation=_observation(
            namespace=namespace,
            external_key="candidate",
            canonical_url=url,
        ),
        decided_at=datetime.now(UTC),
    )
    loaded_current = session.get(CurrentResolution, candidate.source_record_id)
    assert loaded_current is not None and loaded_current.state == "resolved"
    unassign_source_record(
        session,
        source_record_id=candidate.source_record_id,
        from_subject_id=target.id,
        decision=_decision("explicit-unassign"),
        evidence_ids=[candidate.evidence_id],
    )

    event_count_before = session.scalar(
        select(func.count())
        .select_from(ResolutionEvent)
        .where(ResolutionEvent.source_record_id == candidate.source_record_id)
    )
    reobserved = resolve_source_record_observation(
        session,
        observation=_observation(
            namespace=namespace,
            external_key="candidate",
            canonical_url=url,
            payload={"id": "candidate", "revision": 2},
        ),
        decided_at=datetime.now(UTC),
    )
    event_count_after = session.scalar(
        select(func.count())
        .select_from(ResolutionEvent)
        .where(ResolutionEvent.source_record_id == candidate.source_record_id)
    )

    assert reobserved.state == "needs_review"
    assert reobserved.subject_id is None
    assert reobserved.appended_event_ids == ()
    assert event_count_after == event_count_before
    assert (
        session.scalar(
            select(func.count())
            .select_from(SourceRecordVersion)
            .where(SourceRecordVersion.source_record_id == candidate.source_record_id)
        )
        == 2
    )


def test_readiness_requires_meaningful_features_not_organization_name_alone(
    session: Session,
) -> None:
    organization = create_organization(
        session,
        canonical_name="Name Is Not Identity",
        name_fingerprint="name is not identity",
        organization_kind="brand",
    )
    with pytest.raises(SubjectNotEligibleError, match="meaningful typed identity"):
        mark_subject_eligible(session, organization.id)

    blank_place = create_place(session)
    with pytest.raises(SubjectNotEligibleError, match="meaningful typed identity"):
        mark_subject_eligible(session, blank_place.id)

    addressed_place = create_place(session, address="100 Typed Feature St")
    assert mark_subject_eligible(session, addressed_place.id).readiness == "eligible"
    place = session.get(Place, addressed_place.id)
    assert place is not None
    place.address = None
    session.flush()
    with pytest.raises(SubjectNotEligibleError):
        require_eligible_subject(session, addressed_place.id)


def test_organization_readiness_tracks_current_resolved_source_keys(
    session: Session,
) -> None:
    namespace = f"step4-readiness-key-{uuid4().hex}"
    observation = resolve_source_record_observation(
        session,
        observation=_observation(
            namespace=namespace,
            external_key="identity-key",
        ),
        decided_at=datetime.now(UTC),
    )
    organization = create_organization(
        session,
        canonical_name="Keyed Organization",
        name_fingerprint="keyed organization",
    )

    assign_source_record(
        session,
        source_record_id=observation.source_record_id,
        to_subject_id=organization.id,
        decision=_decision(),
        evidence_ids=[observation.evidence_id],
    )
    assert organization.readiness == "eligible"
    assert require_eligible_subject(session, organization.id).id == organization.id

    unassign_source_record(
        session,
        source_record_id=observation.source_record_id,
        from_subject_id=organization.id,
        decision=_decision("remove-only-key"),
        evidence_ids=[observation.evidence_id],
    )
    assert organization.readiness == "provisional"
    with pytest.raises(SubjectNotEligibleError):
        require_eligible_subject(session, organization.id)

    assign_source_record(
        session,
        source_record_id=observation.source_record_id,
        to_subject_id=organization.id,
        decision=_decision("restore-key"),
        evidence_ids=[observation.evidence_id],
    )
    assert organization.readiness == "eligible"
    assert require_eligible_subject(session, organization.id).id == organization.id


def test_establishment_readiness_requires_eligible_parents_and_tracks_loss(
    session: Session,
) -> None:
    observation = resolve_source_record_observation(
        session,
        observation=_observation(
            namespace=f"step4-establishment-{uuid4().hex}",
            external_key="organization-key",
        ),
        decided_at=datetime.now(UTC),
    )
    organization = create_organization(
        session,
        canonical_name="Ready Organization",
        name_fingerprint="ready organization",
    )
    place = create_place(session, address="100 Ready Parent St")
    assign_source_record(
        session,
        source_record_id=observation.source_record_id,
        to_subject_id=organization.id,
        decision=_decision(),
        evidence_ids=[observation.evidence_id],
    )
    mark_subject_eligible(session, place.id)
    establishment = create_establishment(
        session,
        organization_subject_id=organization.id,
        place_subject_id=place.id,
        valid_from=datetime.now(UTC),
    )
    assert mark_subject_eligible(session, establishment.id).readiness == "eligible"
    assert require_eligible_subject(session, establishment.id).id == establishment.id

    unassign_source_record(
        session,
        source_record_id=observation.source_record_id,
        from_subject_id=organization.id,
        decision=_decision("remove-parent-key"),
        evidence_ids=[observation.evidence_id],
    )
    with pytest.raises(SubjectNotEligibleError):
        require_eligible_subject(session, establishment.id)


def test_retired_exact_key_remaps_to_unique_lineage_successor(
    session: Session,
) -> None:
    observation = _observation(
        namespace=f"step4-lineage-{uuid4().hex}",
        external_key="restaurant-key",
    )
    first = resolve_source_record_observation(
        session,
        observation=observation,
        decided_at=datetime.now(UTC),
    )
    survivor = create_organization(session)
    loser = create_organization(session)
    assign_source_record(
        session,
        source_record_id=first.source_record_id,
        to_subject_id=loser.id,
        decision=_decision(),
        evidence_ids=[first.evidence_id],
    )
    record_subject_change(
        session,
        operation="merge",
        input_subject_ids=[survivor.id, loser.id],
        output_subject_ids=[survivor.id],
        decision=_decision("merge-duplicates"),
        evidence_ids=[first.evidence_id],
    )

    resolved = resolve_source_record_observation(
        session,
        observation=replace(
            observation,
            observed_at=observation.observed_at + timedelta(minutes=1),
        ),
        decided_at=datetime.now(UTC),
    )
    assert (resolved.state, resolved.subject_id, resolved.match_basis) == (
        "resolved",
        survivor.id,
        "external_key_lineage",
    )
    assert len(resolved.appended_event_ids) == 1


def test_retired_exact_key_without_unique_successor_needs_review(
    session: Session,
) -> None:
    observation = _observation(
        namespace=f"step4-retired-{uuid4().hex}",
        external_key="restaurant-key",
    )
    first = resolve_source_record_observation(
        session,
        observation=observation,
        decided_at=datetime.now(UTC),
    )
    retired = create_organization(session)
    assign_source_record(
        session,
        source_record_id=first.source_record_id,
        to_subject_id=retired.id,
        decision=_decision(),
        evidence_ids=[first.evidence_id],
    )
    record_subject_change(
        session,
        operation="retire",
        input_subject_ids=[retired.id],
        output_subject_ids=[],
        decision=_decision("retire-invalid-subject"),
        evidence_ids=[first.evidence_id],
    )

    resolved = resolve_source_record_observation(
        session,
        observation=replace(
            observation,
            observed_at=observation.observed_at + timedelta(minutes=1),
        ),
        decided_at=datetime.now(UTC),
    )
    assert (resolved.state, resolved.subject_id, resolved.match_basis) == (
        "needs_review",
        None,
        None,
    )
    assert len(resolved.appended_event_ids) == 1


def test_source_namespace_kind_and_endpoint_ownership_are_stable(
    session: Session,
) -> None:
    token = uuid4().hex
    namespace = f"step4-stable-{token}"
    url = f"https://stable-{token}.example.test/"
    resolve_source_record_observation(
        session,
        observation=_observation(
            namespace=namespace,
            external_key="first",
            canonical_url=url,
        ),
        decided_at=datetime.now(UTC),
    )
    session.commit()

    conflicting_kind = _observation(
        namespace=namespace,
        external_key="second",
        canonical_url=url,
    )
    conflicting_kind = replace(conflicting_kind, source_kind="different-kind")
    with pytest.raises(ValueError, match="already has kind"):
        resolve_source_record_observation(
            session,
            observation=conflicting_kind,
            decided_at=datetime.now(UTC),
        )
    session.rollback()

    other_namespace = f"step4-other-{token}"
    with pytest.raises(ValueError, match="belongs to another Source"):
        resolve_source_record_observation(
            session,
            observation=_observation(
                namespace=other_namespace,
                external_key="first",
                canonical_url=url,
            ),
            decided_at=datetime.now(UTC),
        )
    session.rollback()

    assert (
        session.scalar(
            select(func.count()).select_from(Source).where(Source.namespace == namespace)
        )
        == 1
    )
    assert (
        session.scalar(
            select(func.count())
            .select_from(SourceRecord)
            .join(Source, Source.id == SourceRecord.source_id)
            .where(Source.namespace == namespace)
        )
        == 1
    )
