"""S14 schema tightening (R53, R54, R56, R60, R63): DB guards and contract checks."""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from packages.helios_core.identity import create_organization
from packages.helios_core.provenance.contracts import persist_source_record_observation
from test.guard_support import raises_guard
from test.provider_support import decision, observation

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

CHECK_VIOLATION = "23514"
BRONZE_TABLES = (
    "source",
    "source_endpoint",
    "source_record",
    "capture",
    "source_record_version",
    "evidence",
)
# Python's str.strip() whitespace, which the Python contracts trim.
PYTHON_WHITESPACE = "".join(chr(c) for c in range(sys.maxunicode + 1) if chr(c).isspace())


def _assert_check_rejects(session: Session, statement: str, **params: object) -> None:
    with pytest.raises(IntegrityError) as error, session.begin_nested():
        session.execute(text(statement), params)
    assert getattr(error.value.orig, "sqlstate", None) == CHECK_VIOLATION, error.value


def _naive(field: str) -> dict[str, Any]:
    return {field: datetime(2026, 9, 24, 12, 0)}  # noqa: DTZ001


def _bronze_rows(session: Session) -> dict[str, int]:
    persisted = persist_source_record_observation(session, observation())
    return {
        "source": persisted.source_id,
        "source_endpoint": persisted.source_endpoint_id or 0,
        "source_record": persisted.source_record_id,
        "capture": persisted.capture_id,
        "source_record_version": persisted.source_record_version_id,
        "evidence": persisted.evidence_id,
    }


# --- R53: TRUNCATE --------------------------------------------------------


@pytest.mark.parametrize("table", BRONZE_TABLES)
def test_bronze_tables_reject_truncate(session: Session, table: str) -> None:
    # CASCADE reaches past FK refusals, so only Bronze's own trigger can stop it.
    with (
        raises_guard(rf"bronze\.{table} is immutable and cannot be truncated"),
        session.begin_nested(),
    ):
        session.execute(text(f"TRUNCATE bronze.{table} CASCADE"))


# --- R54: every column is immutable ----------------------------------------


@pytest.mark.parametrize(
    ("table", "assignment"),
    [
        ("source", "kind = 'renamed'"),
        ("source_endpoint", "endpoint_kind = 'mirror'"),
        ("source_record", "first_seen_at = first_seen_at - interval '1 day'"),
        # A no-op rewrite is still a write to immutable provenance.
        ("source", "namespace = namespace"),
    ],
)
def test_bronze_rows_reject_any_update(session: Session, table: str, assignment: str) -> None:
    rows = _bronze_rows(session)
    with (
        raises_guard(rf"bronze\.{table} is immutable and cannot be updated"),
        session.begin_nested(),
    ):
        session.execute(
            text(f"UPDATE bronze.{table} SET {assignment} WHERE id = :id"), {"id": rows[table]}
        )


# --- R60: Unicode-aware text checks, kinds/outcome, finite times -----------


def test_bronze_whitespace_matches_python_strip(session: Session) -> None:
    assert session.scalar(text("SELECT bronze.whitespace()")) == PYTHON_WHITESPACE
    assert session.scalar(text("SELECT menu.whitespace()")) == PYTHON_WHITESPACE


def test_no_bronze_or_identity_check_trims_ascii_only(session: Session) -> None:
    ascii_only = session.scalars(
        text(
            """
            SELECT n.nspname || '.' || con.conname
            FROM pg_constraint con
            JOIN pg_namespace n ON n.oid = con.connamespace
            WHERE con.contype = 'c'
              AND n.nspname IN ('bronze', 'identity')
              AND pg_get_constraintdef(con.oid) ~ 'btrim\\([^,()]*(\\([^()]*\\)[^,()]*)?\\)'
            """
        )
    ).all()
    assert ascii_only == []


@pytest.mark.parametrize("value", ["\t", " ", "rule\t", "　rule"])
def test_bronze_kinds_and_outcome_must_be_trimmed(session: Session, value: str) -> None:
    rows = _bronze_rows(session)
    _assert_check_rejects(
        session,
        "INSERT INTO bronze.source (namespace, kind) VALUES ('s14-kind', :v)",
        v=value,
    )
    _assert_check_rejects(
        session,
        "INSERT INTO bronze.source (namespace, kind) VALUES (:v, 'dataset')",
        v=value,
    )
    _assert_check_rejects(
        session,
        "INSERT INTO bronze.source_endpoint (source_id, canonical_uri, endpoint_kind)"
        " VALUES (:s, 'https://s14.example.test/', :v)",
        s=rows["source"],
        v=value,
    )
    _assert_check_rejects(
        session,
        "INSERT INTO bronze.capture (source_id, fetched_at, outcome) VALUES (:s, now(), :v)",
        s=rows["source"],
        v=value,
    )


@pytest.mark.parametrize("instant", ["infinity", "-infinity"])
def test_bronze_times_must_be_finite(session: Session, instant: str) -> None:
    rows = _bronze_rows(session)
    _assert_check_rejects(
        session,
        "INSERT INTO bronze.capture (source_id, fetched_at, outcome)"
        " VALUES (:s, CAST(:t AS timestamptz), 'succeeded')",
        s=rows["source"],
        t=instant,
    )
    _assert_check_rejects(
        session,
        "INSERT INTO bronze.source_record (source_id, external_key, first_seen_at)"
        " VALUES (:s, 's14-infinite', CAST(:t AS timestamptz))",
        s=rows["source"],
        t=instant,
    )
    _assert_check_rejects(
        session,
        "INSERT INTO bronze.source_record_version"
        " (source_id, source_record_id, observed_at, content_hash, source_payload)"
        " VALUES (:s, :r, CAST(:t AS timestamptz), 'sha256:x', '{}')",
        s=rows["source"],
        r=rows["source_record"],
        t=instant,
    )


def test_blank_evidence_locator_with_unicode_space_is_rejected(session: Session) -> None:
    rows = _bronze_rows(session)
    _assert_check_rejects(
        session,
        "INSERT INTO bronze.evidence (capture_id, locator, excerpt_hash)"
        " VALUES (:c, :v, 'sha256:x')",
        c=rows["capture"],
        v=" \t",
    )


# --- R63: invisible organization names -------------------------------------


@pytest.mark.parametrize("name", ["​", " ‍﻿", "\t"])
def test_organization_name_needs_visible_content(session: Session, name: str) -> None:
    with pytest.raises(IntegrityError) as error, session.begin_nested():
        create_organization(session, canonical_name=name, name_fingerprint="s14")
    assert getattr(error.value.orig, "sqlstate", None) == CHECK_VIOLATION


# --- R56: Python contracts -------------------------------------------------


@pytest.mark.parametrize(
    "confidence",
    [
        0.5,
        True,
        1,
        Decimal("0.123456"),
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("1.000001"),
    ],
)
def test_decision_confidence_requires_exact_five_place_decimal(confidence: Any) -> None:
    with pytest.raises(ValueError, match="confidence"):
        replace(decision(), confidence=confidence)


@pytest.mark.parametrize("confidence", [Decimal("0"), Decimal("0.12345"), Decimal("1.00000")])
def test_decision_confidence_accepts_stored_scale(confidence: Decimal) -> None:
    assert replace(decision(), confidence=confidence).confidence == confidence


@pytest.mark.parametrize("field", ["decided_at", "effective_at"])
def test_decision_times_must_be_aware(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        replace(decision(), **_naive(field))


@pytest.mark.parametrize("field", ["observed_at", "fetched_at"])
def test_bronze_observation_times_must_be_aware(field: str) -> None:
    naive = replace(observation(), **_naive(field))
    with pytest.raises(ValueError, match=field.replace("_", " ")):
        # Validation precedes any database access.
        persist_source_record_observation(None, naive)  # type: ignore[arg-type]
