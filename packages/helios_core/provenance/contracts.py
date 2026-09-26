"""Published transaction contracts for the Bronze provenance module.

The Identity resolver uses these contracts instead of importing Bronze ORM
models.  Every command flushes its writes but leaves the transaction owned by
the caller so a Bronze observation and its Identity decision are atomic.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

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
    evidence_excerpt_hash: str
    fetched_at: datetime | None = None
    canonical_url: str | None = None
    endpoint_kind: str = "https"
    capture_content_hash: str | None = None
    bundle_path: str | None = None
    capture_outcome: str = "succeeded"


@dataclass(frozen=True, slots=True)
class PersistedBronzeObservation:
    """Database identities created or reused for a Bronze observation."""

    source_id: int
    source_endpoint_id: int | None
    source_record_id: int
    source_record_version_id: int
    capture_id: int
    evidence_id: int
    canonical_url: str | None
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


def canonicalize_http_url(url: str) -> str:
    """Return a deliberately conservative canonical HTTP(S) URL.

    Scheme and host case, an empty path, default ports, and fragments are not
    resource identity.  Path escaping, query ordering, and trailing slashes
    are left untouched because normalizing those can merge distinct source
    resources.
    """
    candidate = url.strip()
    if not candidate or any(character.isspace() for character in candidate):
        raise ValueError("canonical URL must be nonblank and contain no whitespace")

    parsed = urlsplit(candidate)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or parsed.hostname is None:
        raise ValueError("canonical URL must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("canonical URL must not contain user information")

    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("canonical URL has an invalid port") from exc

    try:
        host = parsed.hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("canonical URL has an invalid host") from exc
    if ":" in host:
        host = f"[{host}]"

    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = host if port is None or default_port else f"{host}:{port}"
    path = parsed.path or "/"
    return urlunsplit((scheme, netloc, path, parsed.query, ""))


def _require_trimmed(value: str, label: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{label} must be nonblank and trimmed")


def persist_source_record_observation(
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
    _require_trimmed(observation.evidence_excerpt_hash, "Evidence excerpt hash")
    _require_trimmed(observation.endpoint_kind, "endpoint kind")
    _require_trimmed(observation.capture_outcome, "capture outcome")
    if observation.capture_content_hash is not None:
        _require_trimmed(observation.capture_content_hash, "capture content hash")
    if observation.bundle_path is not None:
        _require_trimmed(observation.bundle_path, "capture bundle path")

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

    canonical_url = (
        canonicalize_http_url(observation.canonical_url)
        if observation.canonical_url is not None
        else None
    )
    endpoint: SourceEndpoint | None = None
    if canonical_url is not None:
        session.execute(
            insert(SourceEndpoint)
            .values(
                source_id=source.id,
                canonical_uri=canonical_url,
                endpoint_kind=observation.endpoint_kind,
            )
            .on_conflict_do_nothing(index_elements=[SourceEndpoint.canonical_uri])
        )
        # FOR NO KEY UPDATE serializes deterministic URL resolution while
        # remaining compatible with Capture's FK key-share lock. Identity's
        # resolver takes this lock itself, after its Subjects and before any
        # Source Record, so here it is normally already held.
        endpoint = session.scalar(
            select(SourceEndpoint)
            .where(SourceEndpoint.canonical_uri == canonical_url)
            .with_for_update(key_share=True)
        )
        if endpoint is None:  # pragma: no cover - INSERT/SELECT is atomic in PostgreSQL
            raise RuntimeError("failed to create or reuse Bronze Source Endpoint")
        if endpoint.source_id != source.id:
            raise ValueError(f"canonical URL {canonical_url!r} already belongs to another Source")
        if endpoint.endpoint_kind != observation.endpoint_kind:
            raise ValueError(
                f"canonical URL {canonical_url!r} already has endpoint kind "
                f"{endpoint.endpoint_kind!r}"
            )

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
    endpoint_id = endpoint.id if endpoint is not None else None
    existing = session.execute(
        select(SourceRecordVersion, Capture, Evidence)
        .join(Capture, Capture.id == SourceRecordVersion.capture_id)
        .join(Evidence, Evidence.source_record_version_id == SourceRecordVersion.id)
        .where(
            SourceRecordVersion.source_record_id == source_record.id,
            SourceRecordVersion.source_id == source.id,
            SourceRecordVersion.observed_at == observation.observed_at,
            SourceRecordVersion.content_hash == observation.content_hash,
            SourceRecordVersion.source_payload == dict(observation.source_payload),
            Capture.source_id == source.id,
            Capture.source_endpoint_id == endpoint_id,
            Capture.fetched_at == fetched_at,
            Capture.content_hash == observation.capture_content_hash,
            Capture.bundle_path == observation.bundle_path,
            Capture.outcome == observation.capture_outcome,
            Evidence.locator == observation.evidence_locator,
            Evidence.excerpt_hash == observation.evidence_excerpt_hash,
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
            canonical_url=canonical_url,
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
    )
    session.add(version)
    session.flush()

    evidence = Evidence(
        source_record_version_id=version.id,
        locator=observation.evidence_locator,
        excerpt_hash=observation.evidence_excerpt_hash,
    )
    session.add(evidence)
    session.flush()

    return PersistedBronzeObservation(
        source_id=source.id,
        source_endpoint_id=endpoint.id if endpoint is not None else None,
        source_record_id=source_record.id,
        source_record_version_id=version.id,
        capture_id=capture.id,
        evidence_id=evidence.id,
        canonical_url=canonical_url,
        source_record_created=inserted_record_id is not None,
        observation_created=True,
    )


def source_record_ids_for_canonical_url(
    session: Session,
    canonical_url: str,
) -> tuple[int, ...]:
    """Return record IDs observed at one exact canonical Source Endpoint."""
    statement = (
        select(SourceRecordVersion.source_record_id)
        .join(Capture, Capture.id == SourceRecordVersion.capture_id)
        .join(SourceEndpoint, SourceEndpoint.id == Capture.source_endpoint_id)
        .where(SourceEndpoint.canonical_uri == canonical_url)
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


def lock_source_endpoint(session: Session, canonical_url: str) -> bool:
    """Lock an existing Source Endpoint with the lock observation persistence takes.

    Returns ``False`` when no endpoint exists yet; persistence then creates it.
    """
    return (
        session.scalar(
            select(SourceEndpoint.id)
            .where(SourceEndpoint.canonical_uri == canonical_url)
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
