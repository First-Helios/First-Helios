"""Historical Bronze fixtures, deliberately independent of current ORM columns."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sqlalchemy import text

from packages.helios_core.provenance.contracts import PersistedBronzeObservation
from packages.helios_core.provenance.validation import excerpt_hash

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from packages.helios_core.provenance.contracts import BronzeObservation


def legacy_observation(
    session: Session, observation: BronzeObservation
) -> PersistedBronzeObservation:
    """Insert one unique fixture using only the pre-S6 schema."""

    def row(sql: str, **values: object) -> int:
        return int(session.execute(text(sql + " RETURNING id"), values).scalar_one())

    source = row(
        "INSERT INTO bronze.source(namespace, kind) VALUES (:n, :k)",
        n=observation.source_namespace,
        k=observation.source_kind,
    )
    endpoint = row(
        "INSERT INTO bronze.source_endpoint(source_id, canonical_uri, endpoint_kind) VALUES (:s, :u, 'https')",
        s=source,
        u=observation.source_url,
    )
    record = row(
        "INSERT INTO bronze.source_record(source_id, external_key) VALUES (:s, :k)",
        s=source,
        k=observation.external_key,
    )
    capture = row(
        "INSERT INTO bronze.capture(source_id, source_endpoint_id, fetched_at, content_hash, outcome) VALUES (:s, :e, :t, :h, 'succeeded')",
        s=source,
        e=endpoint,
        t=observation.observed_at,
        h=observation.capture_content_hash,
    )
    version = row(
        "INSERT INTO bronze.source_record_version(source_id, source_record_id, capture_id, observed_at, content_hash, source_payload) VALUES (:s, :r, :c, :t, :h, CAST(:p AS jsonb))",
        s=source,
        r=record,
        c=capture,
        t=observation.observed_at,
        h=observation.content_hash,
        p=json.dumps(dict(observation.source_payload)),
    )
    evidence = row(
        "INSERT INTO bronze.evidence(source_record_version_id, locator, excerpt_hash) VALUES (:v, :l, :h)",
        v=version,
        l=observation.evidence_locator,
        h=excerpt_hash(dict(observation.source_payload), observation.evidence_locator),
    )
    return PersistedBronzeObservation(
        source,
        endpoint,
        record,
        version,
        capture,
        evidence,
        observation.identity_match_url,
        True,
        True,
    )
