"""Published transaction contracts for the Bronze provenance module.

The Identity resolver uses these contracts instead of importing Bronze ORM
models.  Every command flushes its writes but leaves the transaction owned by
the caller so a Bronze observation and its Identity decision are atomic.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from packages.helios_core.provenance.models import (
    Capture,
    Evidence,
    Source,
    SourceEndpoint,
    SourceRecord,
    SourceRecordVersion,
)
from packages.helios_core.provenance.validation import (
    canonicalize_http_url as canonicalize_http_url,
)
from packages.helios_core.provenance.validation import (
    canonicalize_source_url,
    excerpt_hash,
    validate_outcome,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class BronzeObservation:
    """One source-faithful record observation entering deterministic resolution."""

    source_namespace: str
    source_kind: str
    external_key: str
    observed_at: datetime
    content_hash: str
    source_payload: Mapping[str, Any]
    evidence_locator: str
    source_url: str
    fetched_at: datetime | None = None
    identity_match_url: str | None = None
    capture_content_hash: str | None = None
    bundle_path: str | None = None
    capture_outcome: Literal["succeeded", "rejected"] = "succeeded"
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class PersistedBronzeObservation:
    """Database identities created or reused for a Bronze observation."""

    source_id: int
    source_endpoint_id: int
    source_record_id: int
    source_record_version_id: int
    capture_id: int
    evidence_id: int
    identity_match_url: str | None
    source_record_created: bool
    observation_created: bool


type CanonicalProvenanceKey = tuple[str | CanonicalProvenanceKey, ...]


def _immutable_key(value: list[Any]) -> CanonicalProvenanceKey:
    """Freeze versioned, orderable keys (missing Capture is (), missing strings '').

    The relevant Bronze string constraints exclude empty values, so these absence
    representations are lossless. Timestamps in keys are explicit UTC strings.
    """
    return tuple(_immutable_key(part) if isinstance(part, list) else part for part in value)


@dataclass(frozen=True, slots=True)
class RecordVersionReference:
    """Immutable Bronze identity and observation, without source payload copying."""

    id: int
    source_record_id: int
    capture_id: int | None
    observed_at: datetime
    content_hash: str
    source_namespace: str
    external_key: str
    canonical_key: CanonicalProvenanceKey


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    """One immutable factual locator; target ownership is checked separately."""

    id: int
    source_record_version_id: int | None
    capture_id: int | None
    locator: str
    excerpt_hash: str
    canonical_key: CanonicalProvenanceKey


def get_record_version(session: Session, version_id: int) -> RecordVersionReference:
    """Look up committed input for downstream interpretation; missing IDs fail.

    Callers must supply already committed Bronze input. This read does not
    commit, acquire admission locks, or establish semantic truth of the payload.
    """
    row = (
        session.execute(text("SELECT * FROM bronze.record_version_info(:id)"), {"id": version_id})
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ValueError(f"unknown Bronze version {version_id}")
    fields = dict(row)
    fields["canonical_key"] = _immutable_key(fields["canonical_key"])
    return RecordVersionReference(**fields)


def get_evidence(session: Session, evidence_id: int) -> EvidenceReference:
    """Return a frozen Evidence lookup and canonical key, excluding surrogate IDs."""
    row = (
        session.execute(text("SELECT * FROM bronze.evidence_info(:id)"), {"id": evidence_id})
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ValueError(f"unknown Bronze Evidence {evidence_id}")
    fields = dict(row)
    fields["canonical_key"] = _immutable_key(fields["canonical_key"])
    return EvidenceReference(**fields)


def evidence_supports_version(session: Session, evidence_id: int, version_id: int) -> bool:
    """True only for the exact version or its non-null Capture, never merely its URL."""
    return bool(
        session.scalar(
            text("SELECT bronze.evidence_supports_version(:evidence, :version)"),
            {"evidence": evidence_id, "version": version_id},
        )
    )


def _require_trimmed(value: str, label: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{label} must be nonblank and trimmed")


def _persist_source_record_observation(
    session: Session,
    observation: BronzeObservation,
) -> PersistedBronzeObservation:
    """Persist one immutable Bronze observation, reusing stable identities.

    A repeated source namespace or ``(source, external_key)`` reuses the
    existing immutable row. Retrying the exact same immutable observation
    reuses its Capture, Version, and Evidence; a later observation appends.
    """
    _require_trimmed(observation.source_namespace, "source namespace")
    _require_trimmed(observation.source_kind, "source kind")
    _require_trimmed(observation.external_key, "external key")
    _require_trimmed(observation.content_hash, "record content hash")
    _require_trimmed(observation.evidence_locator, "Evidence locator")
    _require_trimmed(observation.capture_outcome, "capture outcome")
    if observation.capture_content_hash is not None:
        _require_trimmed(observation.capture_content_hash, "capture content hash")
    if observation.bundle_path is not None:
        _require_trimmed(observation.bundle_path, "capture bundle path")
    if observation.observed_at.utcoffset() is None:
        raise ValueError("observed at requires an aware timestamp")
    if observation.fetched_at is not None and observation.fetched_at.utcoffset() is None:
        raise ValueError("fetched at requires an aware timestamp")

    session.execute(
        insert(Source)
        .values(namespace=observation.source_namespace, kind=observation.source_kind)
        .on_conflict_do_nothing(index_elements=[Source.namespace])
    )
    source = session.scalar(select(Source).where(Source.namespace == observation.source_namespace))
    if source is None:  # pragma: no cover - INSERT/SELECT is atomic in PostgreSQL
        raise RuntimeError("failed to create or reuse Bronze Source")
    if source.kind != observation.source_kind:
        raise ValueError(
            f"Source {observation.source_namespace!r} already has kind {source.kind!r}"
        )

    inserted_record_id = session.scalar(
        insert(SourceRecord)
        .values(source_id=source.id, external_key=observation.external_key)
        .on_conflict_do_nothing(index_elements=[SourceRecord.source_id, SourceRecord.external_key])
        .returning(SourceRecord.id)
    )
    source_record = session.scalar(
        select(SourceRecord).where(
            SourceRecord.source_id == source.id,
            SourceRecord.external_key == observation.external_key,
        )
    )
    if source_record is None:  # pragma: no cover - INSERT/SELECT is atomic in PostgreSQL
        raise RuntimeError("failed to create or reuse Bronze Source Record")

    endpoint = _endpoint(session, source.id, canonicalize_source_url(observation.source_url))
    match_url = (
        canonicalize_http_url(observation.identity_match_url)
        if observation.identity_match_url
        else None
    )
    match_endpoint = _endpoint(session, source.id, match_url, lock=True) if match_url else None
    evidence_hash = excerpt_hash(dict(observation.source_payload), observation.evidence_locator)

    # FOR NO KEY UPDATE serializes exact-retry detection between concurrent
    # observers of one record (so an identical retry stays idempotent and new
    # observations stay append-only) while remaining compatible with the FOR
    # KEY SHARE locks that FK checks from new versions and Identity events
    # take. It is the same lock Identity decisions take on the record, so
    # Identity's resolver acquires it before calling this function, after its
    # Subjects (see ``packages.helios_core.identity.commands``, "Lock order").
    source_record = session.scalar(
        select(SourceRecord)
        .where(SourceRecord.id == source_record.id)
        .with_for_update(key_share=True)
    )
    if source_record is None:  # pragma: no cover - the immutable row was just selected
        raise RuntimeError("Bronze Source Record disappeared during observation")

    fetched_at = observation.fetched_at or observation.observed_at
    endpoint_id = endpoint.id
    existing = session.execute(
        select(SourceRecordVersion, Capture, Evidence)
        .join(Capture, Capture.id == SourceRecordVersion.capture_id)
        .join(Evidence, Evidence.source_record_version_id == SourceRecordVersion.id)
        .where(
            SourceRecordVersion.source_record_id == source_record.id,
            SourceRecordVersion.source_id == source.id,
            SourceRecordVersion.observed_at == observation.observed_at,
            SourceRecordVersion.content_hash == observation.content_hash,
            SourceRecordVersion.identity_match_endpoint_id
            == (match_endpoint.id if match_endpoint else None),
            SourceRecordVersion.source_payload == dict(observation.source_payload),
            Capture.source_id == source.id,
            Capture.source_endpoint_id == endpoint_id,
            Capture.fetched_at == fetched_at,
            Capture.content_hash == observation.capture_content_hash,
            Capture.bundle_path == observation.bundle_path,
            Capture.outcome == observation.capture_outcome,
            Capture.reason_code == observation.reason_code,
            Evidence.locator == observation.evidence_locator,
            Evidence.excerpt_hash == evidence_hash,
        )
        .order_by(SourceRecordVersion.id, Evidence.id)
        .limit(1)
    ).one_or_none()
    if existing is not None:
        version, capture, evidence = existing
        return PersistedBronzeObservation(
            source_id=source.id,
            source_endpoint_id=endpoint_id,
            source_record_id=source_record.id,
            source_record_version_id=version.id,
            capture_id=capture.id,
            evidence_id=evidence.id,
            identity_match_url=match_url,
            source_record_created=inserted_record_id is not None,
            observation_created=False,
        )

    capture = Capture(
        source_id=source.id,
        source_endpoint_id=endpoint_id,
        fetched_at=fetched_at,
        content_hash=observation.capture_content_hash,
        bundle_path=observation.bundle_path,
        outcome=observation.capture_outcome,
        reason_code=observation.reason_code,
    )
    session.add(capture)
    session.flush()

    version = SourceRecordVersion(
        source_id=source.id,
        source_record_id=source_record.id,
        capture_id=capture.id,
        observed_at=observation.observed_at,
        content_hash=observation.content_hash,
        source_payload=deepcopy(dict(observation.source_payload)),
        identity_match_endpoint_id=match_endpoint.id if match_endpoint else None,
    )
    session.add(version)
    session.flush()

    evidence = Evidence(
        source_record_version_id=version.id,
        locator=observation.evidence_locator,
        excerpt_hash=evidence_hash,
    )
    session.add(evidence)
    session.flush()

    return PersistedBronzeObservation(
        source_id=source.id,
        source_endpoint_id=endpoint.id,
        source_record_id=source_record.id,
        source_record_version_id=version.id,
        capture_id=capture.id,
        evidence_id=evidence.id,
        identity_match_url=match_url,
        source_record_created=inserted_record_id is not None,
        observation_created=True,
    )


def source_record_ids_for_identity_match_url(
    session: Session,
    canonical_url: str,
    source_namespace: str,
) -> tuple[int, ...]:
    """Return record IDs observed at one exact canonical Source Endpoint."""
    statement = (
        select(SourceRecordVersion.source_record_id)
        .join(SourceEndpoint, SourceEndpoint.id == SourceRecordVersion.identity_match_endpoint_id)
        .join(Source, Source.id == SourceEndpoint.source_id)
        .where(SourceEndpoint.canonical_uri == canonical_url, Source.namespace == source_namespace)
        .distinct()
        .order_by(SourceRecordVersion.source_record_id)
    )
    return tuple(session.scalars(statement))


def find_source_record_id(
    session: Session,
    source_namespace: str,
    external_key: str,
) -> int | None:
    """Return an existing ``(source, external_key)`` record ID, taking no lock."""
    return session.scalar(
        select(SourceRecord.id)
        .join(Source, Source.id == SourceRecord.source_id)
        .where(
            Source.namespace == source_namespace,
            SourceRecord.external_key == external_key,
        )
    )


def lock_source_endpoint(session: Session, canonical_url: str, source_namespace: str) -> bool:
    """Lock an existing Source Endpoint with the lock observation persistence takes.

    Returns ``False`` when no endpoint exists yet; persistence then creates it.
    """
    return (
        session.scalar(
            select(SourceEndpoint.id)
            .join(Source, Source.id == SourceEndpoint.source_id)
            .where(
                SourceEndpoint.canonical_uri == canonical_url, Source.namespace == source_namespace
            )
            .with_for_update(key_share=True)
        )
        is not None
    )


def lock_source_record(session: Session, source_record_id: int) -> bool:
    """Lock a Source Record for a same-transaction downstream decision.

    Identity resolution serializes on the durable Bronze record rather than
    on a mutable Silver projection.  Keeping that lookup here lets Identity
    depend on a provenance contract instead of importing provenance ORM
    models directly.
    """
    return (
        session.scalar(
            select(SourceRecord.id)
            .where(SourceRecord.id == source_record_id)
            .with_for_update(key_share=True)
        )
        is not None
    )


def _endpoint(session: Session, source_id: int, url: str, *, lock: bool = False) -> SourceEndpoint:
    session.execute(
        insert(SourceEndpoint)
        .values(source_id=source_id, canonical_uri=url, endpoint_kind=url.split(":", 1)[0])
        .on_conflict_do_nothing(
            index_elements=[SourceEndpoint.source_id, SourceEndpoint.canonical_uri]
        )
    )
    query = select(SourceEndpoint).where(
        SourceEndpoint.source_id == source_id, SourceEndpoint.canonical_uri == url
    )
    if lock:
        query = query.with_for_update(key_share=True)
    return session.scalars(query).one()


def persist_source_record_observation(
    session: Session, observation: BronzeObservation
) -> PersistedBronzeObservation:
    """Validate before writes and make the complete Bronze operation atomic."""
    if observation.observed_at.utcoffset() is None:
        raise ValueError("observed at requires an aware timestamp")
    if observation.fetched_at is not None and observation.fetched_at.utcoffset() is None:
        raise ValueError("fetched at requires an aware timestamp")
    canonicalize_source_url(observation.source_url)
    if observation.identity_match_url is not None:
        canonicalize_http_url(observation.identity_match_url)
    validate_outcome(observation.capture_outcome, observation.reason_code)
    if observation.capture_outcome not in {"succeeded", "rejected"}:
        raise ValueError("observations must succeed or be rejected")
    if observation.capture_outcome == "rejected" and observation.identity_match_url is not None:
        raise ValueError("rejected observations cannot match Identity")
    excerpt_hash(dict(observation.source_payload), observation.evidence_locator)
    with session.begin_nested():
        return _persist_source_record_observation(session, observation)


@dataclass(frozen=True, slots=True)
class CaptureReference:
    id: int
    source_url: str
    endpoint_kind: str
    fetched_at: datetime
    content_hash: str | None
    outcome: str
    reason_code: str | None


def latest_capture_at(session: Session, namespace: str, url: str) -> CaptureReference | None:
    row = session.execute(
        select(Capture, SourceEndpoint)
        .join(SourceEndpoint, SourceEndpoint.id == Capture.source_endpoint_id)
        .join(Source, Source.id == Capture.source_id)
        .where(
            Source.namespace == namespace,
            SourceEndpoint.canonical_uri == canonicalize_source_url(url),
        )
        .order_by(Capture.fetched_at.desc(), Capture.id.desc())
        .limit(1)
    ).one_or_none()
    return _capture_reference(*row) if row else None


def _capture_reference(capture: Capture, endpoint: SourceEndpoint) -> CaptureReference:
    return CaptureReference(
        capture.id,
        endpoint.canonical_uri,
        endpoint.endpoint_kind,
        capture.fetched_at,
        capture.content_hash,
        capture.outcome,
        capture.reason_code,
    )


def source_endpoint_for_evidence(session: Session, evidence_id: int) -> CaptureReference:
    evidence = session.get(Evidence, evidence_id)
    if evidence is None:
        raise ValueError("unknown Evidence")
    capture_id = evidence.capture_id
    if evidence.source_record_version_id is not None:
        version = session.get(SourceRecordVersion, evidence.source_record_version_id)
        if version is not None:
            capture_id = version.capture_id
    capture = session.get(Capture, capture_id) if capture_id is not None else None
    if capture is None:
        raise ValueError("Evidence has no Capture")
    endpoint = session.get(SourceEndpoint, capture.source_endpoint_id)
    if endpoint is None:
        raise ValueError("Capture has no endpoint")
    return _capture_reference(capture, endpoint)


def source_record_is_rejected_only(session: Session, source_record_id: int) -> bool:
    """Block rejected-only records, preserving admission of legacy uncaptured Versions.

    SourceRecordVersion.capture_id remains nullable by contract. Such a Version
    is not a rejected observation; S6 does not change the existing raw admission
    API for it. A subsequent successful Version also permits normal admission.
    """
    outcomes = session.scalars(
        select(Capture.outcome)
        .select_from(SourceRecordVersion)
        .outerjoin(Capture, Capture.id == SourceRecordVersion.capture_id)
        .where(SourceRecordVersion.source_record_id == source_record_id)
    ).all()
    return bool(outcomes) and all(outcome == "rejected" for outcome in outcomes)


def record_capture_attempt(
    session: Session,
    *,
    source_namespace: str,
    source_kind: str,
    source_url: str,
    fetched_at: datetime,
    outcome: Literal["failed", "skipped"],
    reason_code: str,
    content_hash: str | None = None,
) -> CaptureReference:
    """Record one unsuccessful site attempt; no record, Version or Identity state."""
    url = canonicalize_source_url(source_url)
    validate_outcome(outcome, reason_code)
    if outcome not in {"failed", "skipped"}:
        raise ValueError("attempts must be failed or skipped")
    for value, label in ((source_namespace, "namespace"), (source_kind, "kind")):
        _require_trimmed(value, label)
    if fetched_at.utcoffset() is None:
        raise ValueError("fetched at requires an aware timestamp")
    if content_hash is not None:
        _require_trimmed(content_hash, "content hash")
    with session.begin_nested():
        session.execute(
            insert(Source)
            .values(namespace=source_namespace, kind=source_kind)
            .on_conflict_do_nothing(index_elements=[Source.namespace])
        )
        source = session.scalars(select(Source).where(Source.namespace == source_namespace)).one()
        if source.kind != source_kind:
            raise ValueError("Source kind mismatch")
        endpoint = _endpoint(session, source.id, url)
        capture = Capture(
            source_id=source.id,
            source_endpoint_id=endpoint.id,
            fetched_at=fetched_at,
            outcome=outcome,
            reason_code=reason_code,
            content_hash=content_hash,
        )
        session.add(capture)
        session.flush()
        return _capture_reference(capture, endpoint)
