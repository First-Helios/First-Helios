"""
tests/HeliosDeployment/test_dashboard_spiritpool.py — Tests for T3.2 dashboard
SpiritPool monitoring sections.

Dev Req §6.1: System health dashboard integration for SpiritPool tables.
"""

import json
from datetime import datetime, timedelta
from io import StringIO

import pytest

from core.models.spiritpool import BurnPool, Contributor, Quarantine, SessionEpoch, SpEvent
from scripts.system_health_dashboard import (
    check_burn_pool,
    check_contributor_volume,
    check_quarantine_health,
    check_session_epochs,
    check_spiritpool_events_freshness,
)


class TestSpEventsFresnhness:
    """§6.1 — sp_events freshness monitoring."""

    def test_no_events_shows_empty_message(self, db, capsys):
        check_spiritpool_events_freshness(db)
        out = capsys.readouterr().out
        assert "No events received yet" in out

    def test_fresh_event_shows_fresh(self, db, capsys):
        ev = SpEvent(
            event_id="evt-1",
            session_token="tok-1",
            epoch_id=1,
            event_type="job_listing",
            payload=json.dumps({"title": "test"}),
            source_type="extension",
            collected_at=datetime.utcnow(),
            pipeline_version=1,
        )
        db.add(ev)
        db.commit()

        check_spiritpool_events_freshness(db)
        out = capsys.readouterr().out
        assert "FRESH" in out
        assert "sp_events" in out

    def test_domain_coverage_breakdown(self, db, capsys):
        for i, etype in enumerate(["job_listing", "job_listing", "event_listing"]):
            db.add(SpEvent(
                event_id=f"evt-{i}",
                session_token=f"tok-{i}",
                epoch_id=1,
                event_type=etype,
                payload=json.dumps({"x": i}),
                source_type="extension",
                collected_at=datetime.utcnow(),
                pipeline_version=1,
            ))
        db.commit()

        check_spiritpool_events_freshness(db)
        out = capsys.readouterr().out
        assert "Domain coverage" in out
        assert "job_listing" in out
        assert "event_listing" in out


class TestQuarantineHealth:
    """§6.1 — quarantine table health and PII detection hit rate."""

    def test_no_data_shows_empty(self, db, capsys):
        check_quarantine_health(db)
        out = capsys.readouterr().out
        assert "No events processed yet" in out

    def test_healthy_rate(self, db, capsys):
        # 10 clean events, 0 quarantined → 0% → HEALTHY
        for i in range(10):
            db.add(SpEvent(
                event_id=f"evt-{i}",
                session_token=f"tok-{i}",
                epoch_id=1,
                event_type="job_listing",
                payload=json.dumps({"x": i}),
                source_type="extension",
                collected_at=datetime.utcnow(),
                pipeline_version=1,
            ))
        db.commit()

        check_quarantine_health(db)
        out = capsys.readouterr().out
        assert "HEALTHY" in out
        assert "0.0%" in out

    def test_warning_rate(self, db, capsys):
        # 9 clean, 1 quarantined → 10% → WARNING
        for i in range(9):
            db.add(SpEvent(
                event_id=f"evt-{i}",
                session_token=f"tok-{i}",
                epoch_id=1,
                event_type="job_listing",
                payload=json.dumps({"x": i}),
                source_type="extension",
                collected_at=datetime.utcnow(),
                pipeline_version=1,
            ))
        db.add(Quarantine(
            quarantine_id="q-1",
            original_payload=json.dumps({"email": "test@x.com"}),
            redaction_types=json.dumps(["email"]),
            rule_version=1,
            quarantined_at=datetime.utcnow(),
        ))
        db.commit()

        check_quarantine_health(db)
        out = capsys.readouterr().out
        assert "WARNING" in out

    def test_critical_rate(self, db, capsys):
        # 4 clean, 1 quarantined → 20% → CRITICAL
        for i in range(4):
            db.add(SpEvent(
                event_id=f"evt-{i}",
                session_token=f"tok-{i}",
                epoch_id=1,
                event_type="job_listing",
                payload=json.dumps({"x": i}),
                source_type="extension",
                collected_at=datetime.utcnow(),
                pipeline_version=1,
            ))
        db.add(Quarantine(
            quarantine_id="q-1",
            original_payload=json.dumps({"email": "test@x.com"}),
            redaction_types=json.dumps(["email"]),
            rule_version=1,
            quarantined_at=datetime.utcnow(),
        ))
        db.commit()

        check_quarantine_health(db)
        out = capsys.readouterr().out
        assert "CRITICAL" in out


class TestSessionEpochs:
    """§6.1 — session epoch and burn rate monitoring."""

    def test_no_sessions_shows_empty(self, db, capsys):
        check_session_epochs(db)
        out = capsys.readouterr().out
        assert "No sessions recorded yet" in out

    def test_active_and_burned_counts(self, db, capsys):
        db.add(SessionEpoch(session_token="tok-1", epoch_id=1, created_at=datetime.utcnow()))
        db.add(SessionEpoch(session_token="tok-2", epoch_id=1, created_at=datetime.utcnow(),
                            burned_at=datetime.utcnow()))
        db.commit()

        check_session_epochs(db)
        out = capsys.readouterr().out
        assert "Total sessions:   2" in out
        assert "Active:           1" in out
        assert "Burned:           1" in out


class TestBurnPool:
    """§6.1 — burn pool monthly trends and expiry."""

    def test_no_data_shows_empty(self, db, capsys):
        check_burn_pool(db)
        out = capsys.readouterr().out
        assert "No burn pool data yet" in out

    def test_active_month_shown(self, db, capsys):
        now = datetime.utcnow()
        db.add(BurnPool(
            month_key=now.strftime("%Y-%m"),
            signal_count=5,
            burned_at=now,
            expires_at=now + timedelta(days=365),
        ))
        db.commit()

        check_burn_pool(db)
        out = capsys.readouterr().out
        assert "ACTIVE" in out
        assert "signals:      5" in out

    def test_expired_month_flagged(self, db, capsys):
        past = datetime.utcnow() - timedelta(days=400)
        db.add(BurnPool(
            month_key="2024-01",
            signal_count=3,
            burned_at=past,
            expires_at=past + timedelta(days=365),
        ))
        db.commit()

        check_burn_pool(db)
        out = capsys.readouterr().out
        assert "EXPIRED" in out


class TestContributorVolume:
    """§6.1 — contributor volume tracking."""

    def test_no_contributors_shows_empty(self, db, capsys):
        check_contributor_volume(db)
        out = capsys.readouterr().out
        assert "No contributors registered yet" in out

    def test_contributor_stats(self, db, capsys):
        db.add(Contributor(uuid="c-1", total_signals=10, created_at=datetime.utcnow()))
        db.add(Contributor(uuid="c-2", total_signals=20, created_at=datetime.utcnow()))
        db.commit()

        check_contributor_volume(db)
        out = capsys.readouterr().out
        assert "Total contributors:      2" in out
        assert "Total signals ingested:  30" in out
        assert "Avg signals/contributor: 15.0" in out
