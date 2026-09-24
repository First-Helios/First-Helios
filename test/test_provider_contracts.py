"""Provider-only admission proofs; these do not implement or validate Menu."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, asdict, replace
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from packages.helios_core.identity import (
    SubjectChangeMember,
    SubjectNotEligibleError,
    create_establishment,
    create_organization,
    create_place,
    mark_subject_eligible,
    remap_source_record,
    unassign_source_record,
)
from packages.helios_core.identity.contracts import (
    ResolvedScopeRequest,
    current_resolved_scopes,
    require_resolved_scopes,
    subject_meets_readiness_policy,
)
from packages.helios_core.provenance import Capture, Evidence, SourceRecordVersion
from packages.helios_core.provenance.contracts import (
    evidence_supports_version,
    get_evidence,
    get_record_version,
)
from test.provider_support import (
    ScopeFixture,
    decision,
    held_write_locks,
    migrate,
    pending_change,
    raw_admit,
    seed_scope,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


@pytest.fixture
def scopes(disposable_database_engine: Engine) -> tuple[sessionmaker[Session], ScopeFixture]:
    migrate("upgrade", "head")
    factory = sessionmaker(disposable_database_engine, expire_on_commit=False)
    with factory.begin() as session:
        fixture = seed_scope(session)
    return factory, fixture


def assert_rejected(session: Session, request: ResolvedScopeRequest) -> None:
    # The read-only check must agree with the guard on every rejection.
    assert current_resolved_scopes(session, (request,)) == (None,)
    with pytest.raises(SubjectNotEligibleError), session.begin_nested():
        require_resolved_scopes(session, (request,))
    with pytest.raises(DBAPIError) as error, session.begin_nested():
        raw_admit(session, request)
    assert getattr(error.value.orig, "sqlstate", None) == "23514"


def test_batch_python_sql_parity_and_parent_expansion(
    scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    factory, fixture = scopes
    with factory() as session:
        requests = (fixture.establishment, fixture.organization, fixture.establishment)
        results = require_resolved_scopes(session, requests)
        assert [asdict(r) for r in results] == raw_admit(session, *requests)
        assert current_resolved_scopes(session, requests) == results
        assert results[0].organization_subject_id == fixture.organization.subject_id
        assert results[0].place_subject_id == fixture.place_id
        assert results[0].operating_status == "closed"  # Closure is not retirement.
        assert results[1].place_subject_id is None
        assert session.scalar(
            text("SELECT identity.scope_dependencies(CAST(:s AS bigint[]))"),
            {"s": [fixture.establishment.subject_id]},
        ) == sorted(
            [
                fixture.place_id,
                fixture.organization.subject_id,
                fixture.establishment.subject_id,
            ]
        )
        with pytest.raises(FrozenInstanceError):
            results[0].kind = "place"  # type: ignore[misc]


@pytest.mark.parametrize(
    "address,coordinates,expected",
    [
        (None, False, False),
        ("", False, False),
        (" \t\r\n", False, False),
        ("\x1c\x85\u00a0\u1680\u2000\u2028\u202f\u205f\u3000", False, False),
        ("\u200b", False, True),
        (" Test ", False, True),
        (None, True, True),
    ],
)
def test_place_feature_policy_preserved_and_provisional_promotion(
    scopes: tuple[sessionmaker[Session], ScopeFixture],
    address: str | None,
    coordinates: bool,
    expected: bool,
) -> None:
    factory, _ = scopes
    with factory() as session:
        place = create_place(
            session,
            address=address,
            latitude=Decimal("0") if coordinates else None,
            longitude=Decimal("0") if coordinates else None,
        )
        assert place.readiness == "provisional"
        assert subject_meets_readiness_policy(session, place.id) is expected
        assert (
            session.scalar(text("SELECT identity.subject_feature_ready(:id)"), {"id": place.id})
            is expected
        )
        if expected:
            assert mark_subject_eligible(session, place.id).readiness == "eligible"
        else:
            with pytest.raises(SubjectNotEligibleError):
                mark_subject_eligible(session, place.id)


@pytest.mark.parametrize("kind", ["organization", "establishment"])
def test_promotion_does_not_require_prior_eligibility(
    scopes: tuple[sessionmaker[Session], ScopeFixture], kind: str
) -> None:
    factory, fixture = scopes
    request = getattr(fixture, kind)
    with factory() as session:
        session.execute(
            text("UPDATE identity.subject SET readiness='provisional' WHERE id=:id"),
            {"id": request.subject_id},
        )
        assert subject_meets_readiness_policy(session, request.subject_id)
        assert_rejected(session, request)
        mark_subject_eligible(session, request.subject_id)
        assert require_resolved_scopes(session, (request,))[0].subject_id == request.subject_id


@pytest.mark.parametrize(
    "defect",
    [
        "provisional",
        "parent_provisional",
        "parent_feature",
        "org_feature",
        "parent_retired",
        "retired",
        "stale_event",
        "wrong_record",
        "wrong_subject",
        "missing_subject",
        "place",
        "unresolved",
        "needs_review",
        "zero_event",
    ],
)
def test_admission_rejects_each_live_invariant(
    scopes: tuple[sessionmaker[Session], ScopeFixture], defect: str
) -> None:
    factory, fixture = scopes
    request = fixture.establishment
    with factory() as session:
        if defect in {"provisional", "parent_provisional"}:
            target = request.subject_id if defect == "provisional" else fixture.place_id
            session.execute(
                text("UPDATE identity.subject SET readiness='provisional' WHERE id=:id"),
                {"id": target},
            )
        elif defect == "parent_feature":
            session.execute(
                text("UPDATE identity.place SET address=NULL WHERE subject_id=:id"),
                {"id": fixture.place_id},
            )
        elif defect == "org_feature":
            session.execute(
                text(
                    "UPDATE identity.organization SET canonical_name=NULL, "
                    "name_fingerprint=NULL WHERE subject_id=:id"
                ),
                {"id": fixture.organization.subject_id},
            )
        elif defect in {"retired", "parent_retired"}:
            target = request.subject_id if defect == "retired" else fixture.place_id
            pending_change(session, target, "establishment" if defect == "retired" else "place")
            session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        elif defect == "stale_event":
            request = replace(request, resolution_event_id=fixture.organization.resolution_event_id)
        elif defect == "wrong_record":
            request = replace(request, source_record_id=fixture.organization.source_record_id)
        elif defect == "wrong_subject":
            request = replace(request, subject_id=fixture.organization.subject_id)
        elif defect == "missing_subject":
            request = replace(request, subject_id=9223372036854775807)
        elif defect == "place":
            request = replace(request, subject_id=fixture.place_id)
        elif defect == "needs_review":
            unassign_source_record(
                session,
                source_record_id=request.source_record_id,
                from_subject_id=request.subject_id,
                decision=decision(),
                evidence_ids=(fixture.local_input.evidence_id,),
            )
        elif defect in {"unresolved", "zero_event"}:
            # New immutable Bronze record, deliberately not admitted/assigned.
            from packages.helios_core.identity import admit_source_record
            from packages.helios_core.provenance.contracts import persist_source_record_observation
            from test.provider_support import observation

            bronze = persist_source_record_observation(session, observation())
            if defect == "unresolved":
                admit_source_record(
                    session,
                    source_record_id=bronze.source_record_id,
                    decision=decision(),
                    evidence_ids=(bronze.evidence_id,),
                )
            request = replace(request, source_record_id=bronze.source_record_id)
        assert_rejected(session, request)


@pytest.mark.parametrize("target", ["establishment", "organization", "place"])
@pytest.mark.parametrize("admit_first", [False, True])
@pytest.mark.parametrize("force", [False, True])
def test_pending_lineage_orderings_and_real_commit(
    scopes: tuple[sessionmaker[Session], ScopeFixture],
    target: str,
    admit_first: bool,
    force: bool,
) -> None:
    factory, fixture = scopes
    target_id = fixture.place_id if target == "place" else getattr(fixture, target).subject_id
    with factory.begin() as session:
        if admit_first:
            accepted = require_resolved_scopes(session, (fixture.establishment,))
            assert accepted[0].subject_id == fixture.establishment.subject_id
        pending_change(session, target_id, target)
        if force:
            session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        assert_rejected(session, fixture.establishment)
        # Real outer COMMIT applies pending lineage; never rechecks earlier admission.
    with factory() as session:
        assert (
            session.scalar(
                text("SELECT is_current FROM identity.subject_currentness WHERE subject_id=:id"),
                {"id": target_id},
            )
            is False
        )
        assert_rejected(session, fixture.establishment)


def test_pending_merge_survivor_and_parent_membership(
    scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    factory, fixture = scopes
    with factory.begin() as session:
        other = create_organization(session)
        change = pending_change(session, fixture.organization.subject_id, "organization", "merge")
        session.add_all(
            [
                SubjectChangeMember(
                    subject_change_id=change.id,
                    subject_id=other.id,
                    subject_kind="organization",
                    role="input",
                ),
                SubjectChangeMember(
                    subject_change_id=change.id,
                    subject_id=fixture.organization.subject_id,
                    subject_kind="organization",
                    role="output",
                ),
            ]
        )
        session.flush()
        assert_rejected(session, fixture.establishment)
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        assert require_resolved_scopes(session, (fixture.establishment,))


def test_pending_change_without_member_does_not_name_scope_but_cannot_commit(
    scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    factory, fixture = scopes
    with factory() as session:
        pending_change(session, fixture.establishment.subject_id, "establishment", members=False)
        assert require_resolved_scopes(session, (fixture.establishment,))
        with pytest.raises(DBAPIError):
            session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        session.rollback()
    with factory() as session:
        pending_change(session, fixture.establishment.subject_id, "establishment", members=False)
        with pytest.raises(DBAPIError):
            session.commit()
        session.rollback()


@pytest.mark.parametrize("admit_first", [False, True])
def test_remap_ordering_preserves_prior_admission(
    scopes: tuple[sessionmaker[Session], ScopeFixture], admit_first: bool
) -> None:
    factory, fixture = scopes
    with factory.begin() as session:
        other = create_establishment(
            session,
            organization_subject_id=fixture.organization.subject_id,
            place_subject_id=fixture.place_id,
            valid_from=decision().effective_at,
        )
        mark_subject_eligible(session, other.id)
        if admit_first:
            assert require_resolved_scopes(session, (fixture.establishment,))
        event = remap_source_record(
            session,
            source_record_id=fixture.establishment.source_record_id,
            from_subject_id=fixture.establishment.subject_id,
            to_subject_id=other.id,
            decision=decision(),
            evidence_ids=(fixture.local_input.evidence_id,),
        )
        assert_rejected(session, fixture.establishment)
        new_request = ResolvedScopeRequest(
            other.id, fixture.establishment.source_record_id, event.id
        )
        assert_rejected(session, new_request)
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    with factory() as session:
        assert current_resolved_scopes(session, (fixture.establishment,)) == (None,)
        admitted = require_resolved_scopes(session, (new_request,))
        assert admitted
        assert current_resolved_scopes(session, (new_request,)) == admitted


@pytest.mark.parametrize(
    "arrays",
    [
        (None, [], []),
        ([], [], []),
        ([1], [], [1]),
        ([None], [1], [1]),
        ([1], [-1], [1]),
        ([1], [1], [None]),
        ([[1]], [1], [1]),
    ],
)
def test_sql_batch_fails_closed_on_invalid_shape(
    scopes: tuple[sessionmaker[Session], ScopeFixture], arrays: tuple[object, ...]
) -> None:
    factory, _ = scopes
    with factory() as session, pytest.raises(DBAPIError) as error:
        session.execute(
            text(
                "SELECT * FROM identity.require_resolved_scopes("
                "CAST(:s AS bigint[]), CAST(:r AS bigint[]), CAST(:e AS bigint[]))"
            ),
            dict(zip(("s", "r", "e"), arrays, strict=True)),
        )
    assert getattr(error.value.orig, "sqlstate", None) == "22023"


def test_bronze_frozen_lookups_ownership_and_canonical_keys(
    scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    factory, fixture = scopes
    with factory.begin() as session:
        capture_evidence = Evidence(
            capture_id=fixture.local_input.capture_id, locator="$.menu", excerpt_hash="sha256:menu"
        )
        session.add(capture_evidence)
        original = session.get(SourceRecordVersion, fixture.local_input.source_record_version_id)
        assert original is not None
        duplicate = SourceRecordVersion(
            source_id=original.source_id,
            source_record_id=original.source_record_id,
            capture_id=original.capture_id,
            observed_at=original.observed_at,
            content_hash=original.content_hash,
            source_payload=original.source_payload,
        )
        session.add(duplicate)
        session.flush()
        duplicate_evidence = Evidence(
            source_record_version_id=duplicate.id,
            locator="$.id",
            excerpt_hash=f"different-{uuid4().hex}",
        )
        session.add(duplicate_evidence)
    with factory() as session:
        version = get_record_version(session, original.id)
        evidence = get_evidence(session, fixture.local_input.evidence_id)
        assert version.canonical_key == get_record_version(session, duplicate.id).canonical_key
        assert evidence.canonical_key != get_evidence(session, duplicate_evidence.id).canonical_key
        assert evidence_supports_version(session, evidence.id, version.id)
        assert evidence_supports_version(session, capture_evidence.id, version.id)
        assert evidence_supports_version(session, capture_evidence.id, duplicate.id)
        assert not evidence_supports_version(session, evidence.id, duplicate.id)
        assert not evidence_supports_version(session, fixture.shared_input.evidence_id, version.id)
        assert not evidence_supports_version(session, 9223372036854775807, version.id)
        assert not evidence_supports_version(session, evidence.id, 9223372036854775807)
        raw_version = (
            session.execute(
                text("SELECT * FROM bronze.record_version_info(:id)"), {"id": version.id}
            )
            .mappings()
            .one()
        )
        assert raw_version["canonical_key"] == json.loads(json.dumps(version.canonical_key))
        assert raw_version["source_record_id"] == version.source_record_id
        assert raw_version["observed_at"] == version.observed_at
        raw_evidence = (
            session.execute(text("SELECT * FROM bronze.evidence_info(:id)"), {"id": evidence.id})
            .mappings()
            .one()
        )
        assert raw_evidence["canonical_key"] == json.loads(json.dumps(evidence.canonical_key))
        before = (version.canonical_key, evidence.canonical_key)
        session.execute(text("SET LOCAL TIME ZONE 'Pacific/Auckland'"))
        assert before == (
            get_record_version(session, version.id).canonical_key,
            get_evidence(session, evidence.id).canonical_key,
        )
        hash(version.canonical_key)  # Nested arrays are recursively frozen.
        hash(evidence.canonical_key)
        with pytest.raises(FrozenInstanceError):
            version.content_hash = "changed"  # type: ignore[misc]
        with pytest.raises(ValueError):
            get_record_version(session, 9223372036854775807)
        with pytest.raises(ValueError):
            get_evidence(session, 9223372036854775807)


def test_uncaptured_version_support_has_no_capture_fallback(
    scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    factory, fixture = scopes
    with factory.begin() as session:
        original = session.get(SourceRecordVersion, fixture.local_input.source_record_version_id)
        assert original is not None
        uncaptured = SourceRecordVersion(
            source_id=original.source_id,
            source_record_id=original.source_record_id,
            observed_at=original.observed_at,
            content_hash=original.content_hash,
            source_payload={},
        )
        session.add(uncaptured)
        session.flush()
        support = Evidence(source_record_version_id=uncaptured.id, locator="$", excerpt_hash="hash")
        capture_support = Evidence(
            capture_id=fixture.local_input.capture_id, locator="$", excerpt_hash="capture-hash"
        )
        session.add_all((support, capture_support))
    with factory() as session:
        version = get_record_version(session, uncaptured.id)
        assert version.capture_id is None
        captured = get_record_version(session, fixture.local_input.source_record_version_id)
        assert sorted((captured.canonical_key, version.canonical_key))[0] == version.canonical_key
        assert version.canonical_key[-1] == ()
        assert evidence_supports_version(session, support.id, uncaptured.id)
        assert not evidence_supports_version(session, capture_support.id, uncaptured.id)


def test_forged_eligible_parent_without_resolved_feature_is_rejected(
    scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    factory, fixture = scopes
    with factory() as session:
        unassign_source_record(
            session,
            source_record_id=fixture.organization.source_record_id,
            from_subject_id=fixture.organization.subject_id,
            decision=decision(),
            evidence_ids=(fixture.shared_input.evidence_id,),
        )
        session.execute(
            text("UPDATE identity.subject SET readiness='eligible' WHERE id=:id"),
            {"id": fixture.organization.subject_id},
        )
        assert not subject_meets_readiness_policy(session, fixture.organization.subject_id)
        assert_rejected(session, fixture.establishment)


@pytest.mark.parametrize("missing", ["source_endpoint_id", "content_hash", "bundle_path"])
def test_optional_capture_key_fields_have_total_order(
    scopes: tuple[sessionmaker[Session], ScopeFixture],
    missing: str,
) -> None:
    factory, fixture = scopes
    with factory.begin() as session:
        original = session.get(SourceRecordVersion, fixture.local_input.source_record_version_id)
        capture = session.get(Capture, fixture.local_input.capture_id)
        assert original is not None and capture is not None
        partial = Capture(
            source_id=capture.source_id,
            source_endpoint_id=capture.source_endpoint_id,
            content_hash=capture.content_hash,
            bundle_path=capture.bundle_path,
            fetched_at=capture.fetched_at,
            outcome=capture.outcome,
        )
        setattr(partial, missing, None)
        session.add(partial)
        session.flush()
        version = SourceRecordVersion(
            source_id=original.source_id,
            source_record_id=original.source_record_id,
            capture_id=partial.id,
            observed_at=original.observed_at,
            content_hash=original.content_hash,
            source_payload=original.source_payload,
        )
        session.add(version)
    with factory() as session:
        full_key = get_record_version(session, original.id).canonical_key
        partial_key = get_record_version(session, version.id).canonical_key
        assert sorted((full_key, partial_key)) == [partial_key, full_key]


def test_python_batch_rejects_empty_and_non_integer_requests(
    scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    factory, fixture = scopes
    with factory() as session:
        with pytest.raises(ValueError):
            require_resolved_scopes(session, ())
        with pytest.raises(ValueError):
            require_resolved_scopes(session, (replace(fixture.establishment, subject_id=True),))


@pytest.mark.parametrize("admit_first", [False, True])
def test_split_same_transaction_ordering_with_forced_checks(
    scopes: tuple[sessionmaker[Session], ScopeFixture],
    admit_first: bool,
) -> None:
    factory, fixture = scopes
    with factory.begin() as session:
        if admit_first:
            assert require_resolved_scopes(session, (fixture.establishment,))
        change = pending_change(session, fixture.establishment.subject_id, "establishment", "split")
        for _ in range(2):
            output = create_establishment(
                session,
                organization_subject_id=fixture.organization.subject_id,
                place_subject_id=fixture.place_id,
                valid_from=decision().effective_at,
            )
            session.add(
                SubjectChangeMember(
                    subject_change_id=change.id,
                    subject_id=output.id,
                    subject_kind="establishment",
                    role="output",
                )
            )
        session.flush()
        assert_rejected(session, fixture.establishment)
        session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        assert_rejected(session, fixture.establishment)


def test_read_only_scope_check_takes_no_locks(
    scopes: tuple[sessionmaker[Session], ScopeFixture],
) -> None:
    """The selection-side check runs in a READ ONLY transaction, takes no
    row/advisory locks, and reports each request independently in order.
    """
    factory, fixture = scopes
    missing = replace(fixture.establishment, subject_id=9223372036854775807)
    with factory() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        results = current_resolved_scopes(
            session, (missing, fixture.establishment, fixture.organization)
        )
        assert results[0] is None
        assert results[1] is not None
        assert results[1].subject_id == fixture.establishment.subject_id
        assert results[1].operating_status == "closed"  # Closure is not retirement.
        assert results[2] is not None
        assert results[2].subject_id == fixture.organization.subject_id
        assert held_write_locks(session) == []
        assert current_resolved_scopes(session, ()) == ()
    with factory() as session:
        admitted = require_resolved_scopes(session, (fixture.establishment,))
        assert held_write_locks(session) != []  # the writer guard does lock
    assert (results[1],) == admitted
