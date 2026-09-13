"""Database-enforced invariants for the Bronze provenance foundation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from packages.helios_core.provenance import (
    Capture,
    Evidence,
    Source,
    SourceEndpoint,
    SourceRecord,
    SourceRecordVersion,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _source(session: Session, namespace: str = "overture", kind: str = "dataset") -> Source:
    source = Source(namespace=namespace, kind=kind)
    session.add(source)
    session.commit()
    return source


def _endpoint(
    session: Session,
    source: Source,
    canonical_uri: str = "https://example.test/data",
) -> SourceEndpoint:
    endpoint = SourceEndpoint(
        source_id=source.id,
        canonical_uri=canonical_uri,
        endpoint_kind="https",
    )
    session.add(endpoint)
    session.commit()
    return endpoint


def _record(
    session: Session,
    source: Source,
    external_key: str = "place/123",
) -> SourceRecord:
    record = SourceRecord(source_id=source.id, external_key=external_key)
    session.add(record)
    session.commit()
    return record


def _capture(
    session: Session,
    source: Source,
    endpoint: SourceEndpoint | None = None,
) -> Capture:
    capture = Capture(
        source_id=source.id,
        source_endpoint_id=endpoint.id if endpoint else None,
        fetched_at=datetime.now(UTC),
        content_hash="sha256:capture",
        bundle_path="captures/example.json",
        outcome="succeeded",
    )
    session.add(capture)
    session.commit()
    return capture


def _version(
    session: Session,
    record: SourceRecord,
    capture: Capture | None = None,
    *,
    observed_at: datetime | None = None,
) -> SourceRecordVersion:
    version = SourceRecordVersion(
        source_id=record.source_id,
        source_record_id=record.id,
        capture_id=capture.id if capture else None,
        observed_at=observed_at or datetime.now(UTC),
        content_hash="sha256:version",
        source_payload={"id": record.external_key, "name": "Unresolved Place"},
    )
    session.add(version)
    session.commit()
    return version


def _assert_rejects(session: Session, obj: Any) -> None:
    session.add(obj)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def _assert_sql_rejects(session: Session, statement: str, **params: object) -> None:
    with pytest.raises(DBAPIError):
        session.execute(text(statement), params)
        session.commit()
    session.rollback()


def test_source_namespace_is_canonical_and_unique(session: Session) -> None:
    _source(session)
    _assert_rejects(session, Source(namespace="overture", kind="other"))
    _assert_rejects(session, Source(namespace=" overture ", kind="dataset"))


def test_endpoint_identity_is_canonical_and_unique(session: Session) -> None:
    source = _source(session)
    _endpoint(session, source)
    _assert_rejects(
        session,
        SourceEndpoint(
            source_id=source.id,
            canonical_uri="https://example.test/data",
            endpoint_kind="mirror",
        ),
    )
    _assert_rejects(
        session,
        SourceEndpoint(
            source_id=source.id,
            canonical_uri=" https://example.test/other ",
            endpoint_kind="https",
        ),
    )


def test_capture_endpoint_must_belong_to_capture_source(session: Session) -> None:
    first = _source(session)
    second = _source(session, namespace="osm")
    endpoint = _endpoint(session, first)
    _assert_rejects(
        session,
        Capture(
            source_id=second.id,
            source_endpoint_id=endpoint.id,
            fetched_at=datetime.now(UTC),
            outcome="succeeded",
        ),
    )


@pytest.mark.parametrize(
    ("content_hash", "bundle_path"),
    [("", "captures/example.json"), ("sha256:value", " ")],
)
def test_capture_rejects_blank_optional_locators(
    session: Session,
    content_hash: str,
    bundle_path: str,
) -> None:
    source = _source(session)
    _assert_rejects(
        session,
        Capture(
            source_id=source.id,
            fetched_at=datetime.now(UTC),
            content_hash=content_hash,
            bundle_path=bundle_path,
            outcome="succeeded",
        ),
    )


def test_source_record_key_is_canonical_and_unique_per_source(session: Session) -> None:
    source = _source(session)
    _record(session, source)
    _assert_rejects(session, SourceRecord(source_id=source.id, external_key="place/123"))
    _assert_rejects(session, SourceRecord(source_id=source.id, external_key=" place/456 "))


def test_same_external_key_is_valid_in_different_source_namespaces(session: Session) -> None:
    first = _source(session)
    second = _source(session, namespace="osm")
    _record(session, first)
    _record(session, second)


def test_source_record_can_remain_unresolved_without_a_subject(session: Session) -> None:
    source = _source(session)
    record = _record(session, source)

    assert record.id is not None
    assert {fk.column.table.schema for fk in SourceRecord.__table__.foreign_keys} == {"bronze"}


def test_repeated_observations_append_record_versions(session: Session) -> None:
    source = _source(session)
    record = _record(session, source)
    observed_at = datetime.now(UTC)
    _version(session, record, observed_at=observed_at)
    _version(session, record, observed_at=observed_at + timedelta(minutes=5))

    count = session.scalar(
        select(func.count())
        .select_from(SourceRecordVersion)
        .where(SourceRecordVersion.source_record_id == record.id)
    )
    assert count == 2


def test_record_version_capture_must_share_the_records_source(session: Session) -> None:
    first = _source(session)
    second = _source(session, namespace="osm")
    record = _record(session, first)
    capture = _capture(session, second)
    _assert_rejects(
        session,
        SourceRecordVersion(
            source_id=first.id,
            source_record_id=record.id,
            capture_id=capture.id,
            observed_at=datetime.now(UTC),
            content_hash="sha256:version",
            source_payload={"id": record.external_key},
        ),
    )


def test_record_version_rejects_blank_content_hash(session: Session) -> None:
    source = _source(session)
    record = _record(session, source)
    _assert_rejects(
        session,
        SourceRecordVersion(
            source_id=source.id,
            source_record_id=record.id,
            observed_at=datetime.now(UTC),
            content_hash=" ",
            source_payload={"id": record.external_key},
        ),
    )


@pytest.mark.parametrize(
    ("with_version", "with_capture"),
    [(False, False), (True, True)],
)
def test_evidence_requires_exactly_one_target(
    session: Session,
    with_version: bool,
    with_capture: bool,
) -> None:
    source = _source(session)
    capture = _capture(session, source)
    record = _record(session, source)
    version = _version(session, record, capture)
    _assert_rejects(
        session,
        Evidence(
            source_record_version_id=version.id if with_version else None,
            capture_id=capture.id if with_capture else None,
            locator="$.name",
            excerpt_hash="sha256:excerpt",
        ),
    )


@pytest.mark.parametrize(
    ("locator", "excerpt_hash"),
    [("", "sha256:excerpt"), ("$.name", " ")],
)
def test_evidence_rejects_blank_locator_fields(
    session: Session,
    locator: str,
    excerpt_hash: str,
) -> None:
    source = _source(session)
    capture = _capture(session, source)
    _assert_rejects(
        session,
        Evidence(
            capture_id=capture.id,
            locator=locator,
            excerpt_hash=excerpt_hash,
        ),
    )


def test_source_endpoint_and_record_identity_keys_reject_updates(session: Session) -> None:
    source = _source(session)
    endpoint = _endpoint(session, source)
    record = _record(session, source)

    _assert_sql_rejects(
        session,
        "UPDATE bronze.source SET namespace = 'renamed' WHERE id = :id",
        id=source.id,
    )
    _assert_sql_rejects(
        session,
        "UPDATE bronze.source_endpoint SET canonical_uri = :uri WHERE id = :id",
        id=endpoint.id,
        uri="https://example.test/renamed",
    )
    _assert_sql_rejects(
        session,
        "UPDATE bronze.source_record SET external_key = 'place/999' WHERE id = :id",
        id=record.id,
    )


def test_capture_version_and_evidence_reject_updates(session: Session) -> None:
    source = _source(session)
    capture = _capture(session, source)
    record = _record(session, source)
    version = _version(session, record, capture)
    evidence = Evidence(
        source_record_version_id=version.id,
        locator="$.name",
        excerpt_hash="sha256:excerpt",
    )
    session.add(evidence)
    session.commit()

    _assert_sql_rejects(
        session,
        "UPDATE bronze.capture SET outcome = 'failed' WHERE id = :id",
        id=capture.id,
    )
    _assert_sql_rejects(
        session,
        "UPDATE bronze.source_record_version SET content_hash = 'changed' WHERE id = :id",
        id=version.id,
    )
    _assert_sql_rejects(
        session,
        "UPDATE bronze.evidence SET locator = '$.other' WHERE id = :id",
        id=evidence.id,
    )


def test_every_bronze_provenance_row_rejects_delete(session: Session) -> None:
    source = _source(session)
    endpoint = _endpoint(session, source)
    capture = _capture(session, source, endpoint)
    record = _record(session, source)
    version = _version(session, record, capture)
    evidence = Evidence(
        source_record_version_id=version.id,
        locator="$.name",
        excerpt_hash="sha256:excerpt",
    )
    session.add(evidence)
    session.commit()

    rows = {
        "evidence": evidence.id,
        "source_record_version": version.id,
        "capture": capture.id,
        "source_record": record.id,
        "source_endpoint": endpoint.id,
        "source": source.id,
    }
    for table_name, row_id in rows.items():
        _assert_sql_rejects(
            session,
            f"DELETE FROM bronze.{table_name} WHERE id = :id",
            id=row_id,
        )
