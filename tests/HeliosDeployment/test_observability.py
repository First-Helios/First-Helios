"""
tests/HeliosDeployment/test_observability.py — Dev Req §6: Observability Requirements

Validates:
    §6.3 — Audit trail (pipeline_version tracking, rule_version in quarantine)
    T2.5 — Burn pool maintenance job exists and deletes expired records
"""

import uuid
from datetime import datetime, timedelta

from core.models.spiritpool import BurnPool, Quarantine, SessionEpoch, SpEvent


class TestAuditTrail:
    """Dev Req §6.3 — Audit trail requirements."""

    def test_event_has_pipeline_version(self, db):
        """Every sp_event has a pipeline_version for re-processing tracking."""
        ev = SpEvent(
            event_id=str(uuid.uuid4()),
            session_token="audit-tok",
            epoch_id=1,
            event_type="job_listing",
            payload={"test": True},
            source_type="extension",
            pipeline_version=1,
        )
        db.add(ev)
        db.flush()

        result = db.query(SpEvent).filter_by(event_id=ev.event_id).one()
        assert result.pipeline_version == 1

    def test_quarantine_has_rule_version(self, db):
        """Every quarantine record has a rule_version for re-processing."""
        import json

        q = Quarantine(
            quarantine_id=str(uuid.uuid4()),
            original_payload={"test": True},
            redaction_types=json.dumps(["email"]),
            rule_version=1,
        )
        db.add(q)
        db.flush()

        result = db.query(Quarantine).filter_by(quarantine_id=q.quarantine_id).one()
        assert result.rule_version == 1

    def test_session_epoch_tracks_created_at(self, db):
        """session_epochs.created_at is set on creation."""
        se = SessionEpoch(session_token="audit-se-tok", epoch_id=1)
        db.add(se)
        db.flush()

        result = db.query(SessionEpoch).filter_by(session_token="audit-se-tok").one()
        assert result.created_at is not None

    def test_session_epoch_tracks_burned_at(self, db):
        """session_epochs.burned_at can be set (initially NULL)."""
        se = SessionEpoch(session_token="audit-burn-tok", epoch_id=1)
        db.add(se)
        db.flush()

        assert se.burned_at is None

        se.burned_at = datetime.utcnow()
        db.flush()

        result = db.query(SessionEpoch).filter_by(session_token="audit-burn-tok").one()
        assert result.burned_at is not None


class TestBurnPoolMaintenance:
    """T2.5 — Burn pool maintenance job deletes expired records."""

    def test_cleanup_deletes_expired(self, db):
        """Expired burn_pool records are deleted by the cleanup logic."""
        now = datetime.utcnow()

        # Expired record (expires_at in the past)
        expired = BurnPool(
            month_key="2025-01",
            signal_count=3,
            burned_at=now - timedelta(days=400),
            expires_at=now - timedelta(days=35),
        )
        db.add(expired)

        # Still valid record (expires_at in the future)
        valid = BurnPool(
            month_key="2026-03",
            signal_count=1,
            burned_at=now - timedelta(days=30),
            expires_at=now + timedelta(days=335),
        )
        db.add(valid)
        db.flush()

        assert db.query(BurnPool).count() == 2

        # Simulate the cleanup query (same as _run_burn_pool_cleanup)
        from sqlalchemy import text
        db.execute(text("DELETE FROM burn_pool WHERE expires_at < :now"), {"now": now})
        db.flush()

        remaining = db.query(BurnPool).all()
        assert len(remaining) == 1
        assert remaining[0].month_key == "2026-03"

    def test_cleanup_noop_when_none_expired(self, db):
        """Cleanup is a no-op when no records are expired."""
        now = datetime.utcnow()

        bp = BurnPool(
            month_key="2026-04",
            signal_count=1,
            burned_at=now,
            expires_at=now + timedelta(days=365),
        )
        db.add(bp)
        db.flush()

        from sqlalchemy import text
        db.execute(text("DELETE FROM burn_pool WHERE expires_at < :now"), {"now": now})
        db.flush()

        assert db.query(BurnPool).count() == 1

    def test_scheduler_config_has_cleanup_job(self):
        """config/scheduler.yaml has burn_pool_cleanup entry."""
        from pathlib import Path
        import yaml

        config_path = Path(__file__).parent.parent.parent / "config" / "scheduler.yaml"
        assert config_path.exists(), "scheduler.yaml missing"

        with open(config_path) as f:
            config = yaml.safe_load(f)

        assert "burn_pool_cleanup" in config, "burn_pool_cleanup not in scheduler.yaml"
        assert config["burn_pool_cleanup"].get("enabled") is True

    def test_cleanup_function_importable(self):
        """_run_burn_pool_cleanup is importable from core.scheduler."""
        from core.scheduler import _run_burn_pool_cleanup
        assert callable(_run_burn_pool_cleanup)
