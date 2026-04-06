"""
tests/HeliosDeployment/test_legacy_compat.py — Tests for T3.3 legacy SpiritPool
route compatibility layer.

Verifies:
    - §4.3: POST /api/spiritpool/contribute still works with old payload format
    - Privacy: request.remote_addr is no longer logged
    - Dual-write: legacy signals also flow to sp_events or quarantine
    - Backward compatible response format preserved
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from core.privacy import strip_forbidden_fields


class TestLegacyFieldStripping:
    """T3.3 — field stripping applied to legacy route payloads."""

    def test_strip_tabUrl_from_signal(self):
        raw = {"company": "Acme", "tabUrl": "https://indeed.com/job/123", "jobTitle": "Dev"}
        strip_forbidden_fields(raw)
        assert "tabUrl" not in raw

    def test_strip_collectedAt_from_signal(self):
        raw = {"company": "Acme", "collectedAt": "2025-01-01T00:00:00Z", "jobTitle": "Dev"}
        strip_forbidden_fields(raw)
        assert "collectedAt" not in raw

    def test_strip_nested_payload(self):
        raw = {
            "company": "Acme",
            "payload": {"tabUrl": "http://x.com", "collectedAt": "now", "salary": 50000},
        }
        strip_forbidden_fields(raw)
        assert "tabUrl" not in raw.get("payload", {})
        assert "collectedAt" not in raw.get("payload", {})
        assert raw["payload"]["salary"] == 50000


class TestLegacyPrivacyFix:
    """T3.3 — legacy route no longer logs request.remote_addr."""

    def test_no_ip_in_log_format_string(self):
        """The legacy contribute route logger.info call should NOT contain
        'ip=%s' or 'request.remote_addr'."""
        import inspect
        from postings.spiritpool_routes import contribute
        source = inspect.getsource(contribute)
        assert "ip=%s" not in source, "Legacy log still references ip=%s"
        assert "remote_addr" not in source, "Legacy log still references remote_addr"


class TestLegacyDualWrite:
    """T3.3 — dual-write helper routes legacy signals to sp_events or quarantine."""

    def test_clean_signal_goes_to_sp_events(self, db):
        from postings.spiritpool_routes import _dual_write_to_sp_events
        from core.models.spiritpool import SpEvent

        raw = {"company": "Whole Foods", "jobTitle": "Cashier", "location": "Austin, TX"}
        _dual_write_to_sp_events(db, raw, "contributor-abc", "indeed")
        db.commit()

        events = db.query(SpEvent).all()
        assert len(events) == 1
        assert events[0].source_type == "extension_legacy"
        assert events[0].session_token == "legacy_contributor-abc"
        assert events[0].event_type == "job_listing"

        payload = events[0].payload
        if isinstance(payload, str):
            payload = json.loads(payload)
        assert payload["legacy_contributor_id"] == "contributor-abc"
        assert payload["legacy_domain"] == "indeed"

    def test_pii_signal_goes_to_quarantine(self, db):
        from postings.spiritpool_routes import _dual_write_to_sp_events
        from core.models.spiritpool import Quarantine, SpEvent

        raw = {"company": "Acme", "contact": "hiring@acme.com"}
        _dual_write_to_sp_events(db, raw, "contributor-xyz", "indeed")
        db.commit()

        events = db.query(SpEvent).all()
        assert len(events) == 0

        quarantined = db.query(Quarantine).all()
        assert len(quarantined) == 1
        types = json.loads(quarantined[0].redaction_types)
        assert "email" in types

    def test_dual_write_failure_is_non_fatal(self, db):
        """If dual-write fails, it should not raise — just log a warning."""
        from postings.spiritpool_routes import _dual_write_to_sp_events

        # Force a failure by passing invalid session that will cause flush error
        # We patch the session.add to raise an exception
        original_add = db.add
        call_count = [0]

        def _failing_add(obj):
            call_count[0] += 1
            raise RuntimeError("simulated DB error")

        db.add = _failing_add
        # Should not raise
        _dual_write_to_sp_events(db, {"company": "Test"}, "c-1", "indeed")
        db.add = original_add  # restore

    def test_legacy_payload_fields_preserved(self, db):
        """Dual-write preserves original signal fields alongside metadata."""
        from postings.spiritpool_routes import _dual_write_to_sp_events
        from core.models.spiritpool import SpEvent

        raw = {
            "company": "HEB",
            "jobTitle": "Bagger",
            "salary": {"min": 12, "max": 15, "period": "hourly"},
            "isRemote": False,
        }
        _dual_write_to_sp_events(db, raw, "contrib-1", "indeed")
        db.commit()

        ev = db.query(SpEvent).first()
        payload = ev.payload
        if isinstance(payload, str):
            payload = json.loads(payload)
        assert payload["company"] == "HEB"
        assert payload["salary"]["min"] == 12
        assert payload["isRemote"] is False


class TestLegacyResponseFormat:
    """T3.3 — legacy endpoint response format is backward-compatible."""

    def test_response_has_accepted_new_jobs_failed(self):
        """The response must include 'accepted', 'new_jobs', 'failed' keys
        for background.js compatibility."""
        import inspect
        from postings.spiritpool_routes import contribute
        source = inspect.getsource(contribute)
        assert '"accepted"' in source
        assert '"new_jobs"' in source
        assert '"failed"' in source
