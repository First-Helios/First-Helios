"""
tests/HeliosDeployment/test_schema_storage.py — Dev Req §2: Schema & Storage Requirements

Validates:
    §2.1 — Forward-compatible sp_events table (column types, indexes, constraints)
    §2.2 — Session epochs table (UNIQUE token, nullable contributor_id)
    §2.3 — Quarantine table (UUID PK, JSONB payload, redaction_types)
    §2.4 — Burn pool table (month_key, expires_at)
    §2.5 — Contributors table (opaque uuid, no PII)
    §2.6 — Migration strategy (additive, no changes to existing tables)
"""

import json
import uuid

from core.models.spiritpool import BurnPool, Contributor, Quarantine, SessionEpoch, SpEvent


# ── §2.1 Forward-Compatible sp_events table ──────────────────────────────────


class TestSpEventsSchema:
    """Dev Req §2.1 — sp_events acceptance criteria."""

    def test_64_char_hex_session_token(self, db):
        """64-char hex session_token stores without truncation or error."""
        hex_token = "a" * 64
        ev = SpEvent(
            event_id=str(uuid.uuid4()),
            session_token=hex_token,
            epoch_id=1,
            event_type="job_listing",
            payload={"test": True},
            source_type="extension",
            pipeline_version=1,
        )
        db.add(ev)
        db.flush()

        result = db.query(SpEvent).filter_by(event_id=ev.event_id).one()
        assert result.session_token == hex_token
        assert len(result.session_token) == 64

    def test_36_char_uuid_session_token(self, db):
        """36-char UUID session_token stores without error."""
        uuid_token = str(uuid.uuid4())
        ev = SpEvent(
            event_id=str(uuid.uuid4()),
            session_token=uuid_token,
            epoch_id=1,
            event_type="salary_signal",
            payload={"wage": 25.00},
            source_type="extension",
            pipeline_version=1,
        )
        db.add(ev)
        db.flush()

        result = db.query(SpEvent).filter_by(event_id=ev.event_id).one()
        assert result.session_token == uuid_token

    def test_large_epoch_id(self, db):
        """epoch_id = 999999 stores without overflow."""
        ev = SpEvent(
            event_id=str(uuid.uuid4()),
            session_token="test-token",
            epoch_id=999999,
            event_type="job_listing",
            payload={"test": True},
            source_type="extension",
            pipeline_version=1,
        )
        db.add(ev)
        db.flush()

        result = db.query(SpEvent).filter_by(event_id=ev.event_id).one()
        assert result.epoch_id == 999999

    def test_unknown_jsonb_fields_preserved(self, db):
        """Unknown JSONB fields in payload preserved exactly."""
        payload = {
            "known_field": "value",
            "future_era_field": {"nested": True, "version": 3},
            "another_unknown": [1, 2, 3],
        }
        ev = SpEvent(
            event_id=str(uuid.uuid4()),
            session_token="test-token",
            epoch_id=1,
            event_type="business_review",
            payload=payload,
            source_type="extension",
            pipeline_version=1,
        )
        db.add(ev)
        db.flush()

        result = db.query(SpEvent).filter_by(event_id=ev.event_id).one()
        # SQLite stores JSONB as text; compare deserialized
        stored = result.payload if isinstance(result.payload, dict) else json.loads(result.payload)
        assert stored["known_field"] == "value"
        assert stored["future_era_field"]["nested"] is True
        assert stored["another_unknown"] == [1, 2, 3]

    def test_all_event_types_accepted(self, db):
        """All four event_type values store correctly."""
        for etype in ("job_listing", "salary_signal", "business_review", "event_listing"):
            ev = SpEvent(
                event_id=str(uuid.uuid4()),
                session_token="test-token",
                epoch_id=1,
                event_type=etype,
                payload={"type": etype},
                source_type="extension",
                pipeline_version=1,
            )
            db.add(ev)
        db.flush()

        count = db.query(SpEvent).count()
        assert count == 4


# ── §2.2 Session Epochs table ────────────────────────────────────────────────


class TestSessionEpochsSchema:
    """Dev Req §2.2 — session_epochs acceptance criteria."""

    def test_unique_session_token(self, db):
        """Session token has UNIQUE constraint."""
        from sqlalchemy.exc import IntegrityError
        import pytest

        se1 = SessionEpoch(session_token="unique-token", epoch_id=1)
        db.add(se1)
        db.flush()

        se2 = SessionEpoch(session_token="unique-token", epoch_id=2)
        db.add(se2)
        with pytest.raises(IntegrityError):
            db.flush()

    def test_contributor_id_nullable(self, db):
        """contributor_id can be NULL (burn operation)."""
        se = SessionEpoch(
            session_token="burn-test-token",
            epoch_id=1,
            contributor_id=None,
        )
        db.add(se)
        db.flush()

        result = db.query(SessionEpoch).filter_by(session_token="burn-test-token").one()
        assert result.contributor_id is None

    def test_contributor_id_set_to_null(self, db):
        """contributor_id can be set from a value to NULL."""
        c = Contributor(uuid="test-uuid", total_signals=0)
        db.add(c)
        db.flush()

        se = SessionEpoch(
            session_token="linked-token",
            epoch_id=1,
            contributor_id=c.id,
        )
        db.add(se)
        db.flush()
        assert se.contributor_id == c.id

        # Burn — set to NULL
        se.contributor_id = None
        db.flush()

        result = db.query(SessionEpoch).filter_by(session_token="linked-token").one()
        assert result.contributor_id is None

    def test_multiple_tokens_per_contributor(self, db):
        """Multiple session tokens can exist for the same contributor."""
        c = Contributor(uuid="multi-token-user", total_signals=0)
        db.add(c)
        db.flush()

        for i in range(3):
            se = SessionEpoch(
                session_token=f"token-{i}",
                epoch_id=1,
                contributor_id=c.id,
            )
            db.add(se)
        db.flush()

        results = db.query(SessionEpoch).filter_by(contributor_id=c.id).all()
        assert len(results) == 3


# ── §2.3 Quarantine table ────────────────────────────────────────────────────


class TestQuarantineSchema:
    """Dev Req §2.3 — quarantine acceptance criteria."""

    def test_stores_complete_original_payload(self, db):
        """original_payload stores complete original event body."""
        original = {
            "session_token": "tok",
            "payload": {"contact": "user@example.com", "job": "Engineer"},
        }
        q = Quarantine(
            quarantine_id=str(uuid.uuid4()),
            original_payload=original,
            redaction_types=json.dumps(["email"]),
            rule_version=1,
        )
        db.add(q)
        db.flush()

        result = db.query(Quarantine).filter_by(quarantine_id=q.quarantine_id).one()
        stored = result.original_payload if isinstance(result.original_payload, dict) else json.loads(result.original_payload)
        assert stored["payload"]["contact"] == "user@example.com"

    def test_redaction_types_multiple(self, db):
        """redaction_types stores multiple PII types."""
        types = ["email", "phone", "ssn"]
        q = Quarantine(
            quarantine_id=str(uuid.uuid4()),
            original_payload={"test": True},
            redaction_types=json.dumps(types),
            rule_version=1,
        )
        db.add(q)
        db.flush()

        result = db.query(Quarantine).filter_by(quarantine_id=q.quarantine_id).one()
        assert json.loads(result.redaction_types) == ["email", "phone", "ssn"]

    def test_rule_version_tracked(self, db):
        """rule_version is stored for re-processing capability."""
        q = Quarantine(
            quarantine_id=str(uuid.uuid4()),
            original_payload={},
            redaction_types=json.dumps(["email"]),
            rule_version=2,
        )
        db.add(q)
        db.flush()

        result = db.query(Quarantine).filter_by(quarantine_id=q.quarantine_id).one()
        assert result.rule_version == 2


# ── §2.4 Burn Pool table ─────────────────────────────────────────────────────


class TestBurnPoolSchema:
    """Dev Req §2.4 — burn_pool acceptance criteria."""

    def test_monthly_aggregate(self, db):
        """Burn pool stores monthly aggregates with signal_count."""
        from datetime import datetime, timedelta

        now = datetime.utcnow()
        bp = BurnPool(
            month_key="2026-04",
            signal_count=5,
            burned_at=now,
            expires_at=now + timedelta(days=365),
        )
        db.add(bp)
        db.flush()

        result = db.query(BurnPool).filter_by(month_key="2026-04").first()
        assert result.signal_count == 5

    def test_expires_at_set(self, db):
        """expires_at is stored (burned_at + 1 year)."""
        from datetime import datetime, timedelta

        now = datetime.utcnow()
        expires = now + timedelta(days=365)
        bp = BurnPool(
            month_key="2026-03",
            signal_count=1,
            burned_at=now,
            expires_at=expires,
        )
        db.add(bp)
        db.flush()

        result = db.query(BurnPool).filter_by(month_key="2026-03").first()
        assert result.expires_at is not None
        # Verify it's approximately 1 year from burned_at
        delta = result.expires_at - result.burned_at
        assert 364 <= delta.days <= 366


# ── §2.5 Contributors table ──────────────────────────────────────────────────


class TestContributorsSchema:
    """Dev Req §2.5 — contributors acceptance criteria."""

    def test_no_pii_columns(self, db):
        """Contributors table has no PII — only uuid, total_signals, created_at."""
        columns = {c.name for c in Contributor.__table__.columns}
        pii_columns = {"email", "name", "ip_address", "phone", "address"}
        assert columns.isdisjoint(pii_columns), f"PII column found: {columns & pii_columns}"

    def test_uuid_unique(self, db):
        """Contributor uuid is UNIQUE."""
        from sqlalchemy.exc import IntegrityError
        import pytest

        c1 = Contributor(uuid="dup-uuid", total_signals=0)
        db.add(c1)
        db.flush()

        c2 = Contributor(uuid="dup-uuid", total_signals=0)
        db.add(c2)
        with pytest.raises(IntegrityError):
            db.flush()

    def test_total_signals_increments(self, db):
        """total_signals can be incremented."""
        c = Contributor(uuid="counter-test", total_signals=0)
        db.add(c)
        db.flush()

        c.total_signals += 1
        db.flush()

        result = db.query(Contributor).filter_by(uuid="counter-test").one()
        assert result.total_signals == 1
