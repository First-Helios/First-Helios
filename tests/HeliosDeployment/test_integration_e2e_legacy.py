"""
tests/HeliosDeployment/test_integration_e2e_legacy.py — E2E Legacy Dual-Write Path

Validates that signals sent in the OLD extension format
({domain, signals[], contributorId, region}) to POST /api/spiritpool/contribute
arrive in sp_events via the dual-write path with:
    - tabUrl/collectedAt/consent_state stripped
    - PII signals quarantined (not in sp_events)
    - Real session_token/epoch_id from M7 preserved when present
    - Fallback to legacy_{contributorId} when M7 fields absent
    - IP suppression active
"""

import json

from core.models.spiritpool import Quarantine, SpEvent


# ── Helper ──────────────────────────────────────────────────────────────────


def _legacy_post(client, domain, signals, contributor_id="test-uuid-abc", region="austin_tx"):
    """POST a legacy-format batch to /api/spiritpool/contribute."""
    return client.post(
        "/api/spiritpool/contribute",
        json={
            "domain": domain,
            "signals": signals,
            "contributorId": contributor_id,
            "region": region,
        },
    )


# ── Clean signal through dual-write ────────────────────────────────────────


class TestLegacyDualWriteClean:
    """Clean signals reach sp_events via dual-write."""

    def test_clean_signal_stored_in_sp_events(self, client, db):
        """A clean legacy signal is dual-written to sp_events."""
        signal = {
            "company": "Whole Foods",
            "jobTitle": "Team Member",
            "location": "Austin, TX",
            "salary": {"min": 16, "max": 20, "period": "hourly"},
        }
        resp = _legacy_post(client, "indeed.com", [signal])
        assert resp.status_code == 200

        events = db.query(SpEvent).all()
        assert len(events) == 1
        assert events[0].source_type == "extension_legacy"
        assert events[0].pipeline_version == 1

    def test_payload_contains_job_data(self, client, db):
        """Dual-written sp_event payload contains the signal fields."""
        signal = {
            "company": "H-E-B",
            "jobTitle": "Cashier",
            "location": "Austin, TX 78701",
        }
        _legacy_post(client, "indeed.com", [signal])

        ev = db.query(SpEvent).first()
        payload = ev.payload if isinstance(ev.payload, dict) else json.loads(ev.payload)
        assert payload["company"] == "H-E-B"
        assert payload["jobTitle"] == "Cashier"

    def test_multiple_signals_dual_written(self, client, db):
        """Multiple signals in one batch each get dual-written."""
        signals = [
            {"company": "Acme", "jobTitle": "Engineer"},
            {"company": "Globex", "jobTitle": "Designer"},
        ]
        resp = _legacy_post(client, "indeed.com", signals)
        data = resp.get_json()
        assert data["accepted"] == 2

        events = db.query(SpEvent).all()
        assert len(events) == 2


# ── Session token preservation (M7) ────────────────────────────────────────


class TestLegacySessionTokenPreservation:
    """Real session_token/epoch_id from M7 sanitize.js are preserved."""

    def test_real_session_token_preserved(self, client, db):
        """When signal has session_token from M7, it is used instead of legacy_ prefix."""
        signal = {
            "company": "Tesla",
            "jobTitle": "Technician",
            "session_token": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            "epoch_id": 3,
        }
        _legacy_post(client, "indeed.com", [signal])

        ev = db.query(SpEvent).first()
        assert ev.session_token == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert ev.epoch_id == 3

    def test_fallback_to_legacy_token(self, client, db):
        """When signal lacks session_token, falls back to legacy_{contributorId}."""
        signal = {"company": "Starbucks", "jobTitle": "Barista"}
        _legacy_post(client, "indeed.com", [signal], contributor_id="old-ext-uuid")

        ev = db.query(SpEvent).first()
        assert ev.session_token == "legacy_old-ext-uuid"
        assert ev.epoch_id == 1

    def test_64_char_hex_token_preserved(self, client, db):
        """Second Helios 64-char hex tokens pass through the legacy path."""
        hex_token = "a3f2b8c1d4e5f6789012345678abcdef0123456789abcdef0123456789abcdef"
        signal = {
            "company": "SpaceX",
            "jobTitle": "Propulsion Engineer",
            "session_token": hex_token,
            "epoch_id": 42,
        }
        _legacy_post(client, "indeed.com", [signal])

        ev = db.query(SpEvent).first()
        assert ev.session_token == hex_token
        assert ev.epoch_id == 42


# ── Field stripping ────────────────────────────────────────────────────────


class TestLegacyFieldStripping:
    """Forbidden fields stripped from legacy signals before storage."""

    def test_taburl_stripped_from_signal(self, client, db):
        """tabUrl in a signal is stripped before dual-write."""
        signal = {
            "company": "Amazon",
            "jobTitle": "Warehouse",
            "tabUrl": "https://indeed.com/viewjob?jk=123",
        }
        _legacy_post(client, "indeed.com", [signal])

        ev = db.query(SpEvent).first()
        payload = ev.payload if isinstance(ev.payload, dict) else json.loads(ev.payload)
        assert "tabUrl" not in payload

    def test_collectedat_stripped_from_signal(self, client, db):
        """collectedAt in a signal is stripped before dual-write."""
        signal = {
            "company": "Google",
            "jobTitle": "SWE",
            "collectedAt": "2026-04-05T12:00:00Z",
        }
        _legacy_post(client, "indeed.com", [signal])

        ev = db.query(SpEvent).first()
        payload = ev.payload if isinstance(ev.payload, dict) else json.loads(ev.payload)
        assert "collectedAt" not in payload

    def test_consent_state_stripped_from_signal(self, client, db):
        """consent_state in a signal is stripped before dual-write."""
        signal = {
            "company": "Meta",
            "jobTitle": "PM",
            "consent_state": {"collection_active": True, "sites_enabled": ["indeed.com"]},
        }
        _legacy_post(client, "indeed.com", [signal])

        ev = db.query(SpEvent).first()
        payload = ev.payload if isinstance(ev.payload, dict) else json.loads(ev.payload)
        assert "consent_state" not in payload

    def test_taburl_stripped_from_batch_body(self, client, db):
        """tabUrl at the top-level batch body is also stripped."""
        resp = client.post(
            "/api/spiritpool/contribute",
            json={
                "domain": "indeed.com",
                "signals": [{"company": "Apple", "jobTitle": "Genius"}],
                "contributorId": "cid",
                "tabUrl": "https://indeed.com/jobs",
            },
        )
        assert resp.status_code == 200
        ev = db.query(SpEvent).first()
        payload = ev.payload if isinstance(ev.payload, dict) else json.loads(ev.payload)
        assert "tabUrl" not in payload


# ── PII quarantine on legacy path ──────────────────────────────────────────


class TestLegacyPIIQuarantine:
    """PII-containing signals are quarantined, not stored in sp_events."""

    def test_email_quarantined(self, client, db):
        """Signal with email in payload goes to quarantine, not sp_events."""
        signal = {
            "company": "Acme",
            "jobTitle": "Sales",
            "contact": "hiring@acme.com",
        }
        _legacy_post(client, "indeed.com", [signal])

        assert db.query(SpEvent).count() == 0
        q = db.query(Quarantine).first()
        assert q is not None
        types = json.loads(q.redaction_types) if isinstance(q.redaction_types, str) else q.redaction_types
        assert "email" in types

    def test_phone_quarantined(self, client, db):
        """Signal with phone number goes to quarantine."""
        signal = {
            "company": "Acme",
            "jobTitle": "Rep",
            "phone": "512-555-1234",
        }
        _legacy_post(client, "indeed.com", [signal])

        assert db.query(SpEvent).count() == 0
        assert db.query(Quarantine).count() == 1

    def test_clean_and_pii_mixed_batch(self, client, db):
        """In a mixed batch, clean signals go to sp_events, PII to quarantine."""
        signals = [
            {"company": "Clean Co", "jobTitle": "Dev"},
            {"company": "PII Co", "jobTitle": "Admin", "contact": "admin@pii.com"},
        ]
        _legacy_post(client, "indeed.com", signals)

        assert db.query(SpEvent).count() == 1
        assert db.query(Quarantine).count() == 1

        ev = db.query(SpEvent).first()
        payload = ev.payload if isinstance(ev.payload, dict) else json.loads(ev.payload)
        assert payload["company"] == "Clean Co"


# ── IP suppression on legacy path ──────────────────────────────────────────


class TestLegacyIPSuppression:
    """IP suppression is active on the legacy endpoint."""

    def test_remote_addr_suppressed(self, app):
        """request.remote_addr returns 0.0.0.0 even on legacy endpoint."""
        with app.test_request_context(
            "/api/spiritpool/contribute",
            environ_base={"REMOTE_ADDR": "192.168.1.100"},
        ):
            from flask import request
            assert request.remote_addr == "0.0.0.0"


# ── Edge cases ─────────────────────────────────────────────────────────────


class TestLegacyEdgeCases:
    """Edge cases for the legacy dual-write path."""

    def test_empty_signals_list(self, client):
        """Empty signals list returns 200 with 0 accepted."""
        resp = _legacy_post(client, "indeed.com", [])
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["accepted"] == 0

    def test_unrecognised_domain_rejected(self, client):
        """Unknown domain returns 400."""
        resp = _legacy_post(client, "evil.com", [{"company": "X", "jobTitle": "Y"}])
        assert resp.status_code == 400

    def test_no_json_body_rejected(self, client):
        """Missing JSON body returns 400."""
        resp = client.post("/api/spiritpool/contribute", data="not json")
        assert resp.status_code == 400

    def test_signal_without_company_or_title_skipped(self, client, db):
        """Signal lacking both company and jobTitle is skipped (failed count)."""
        signals = [
            {"location": "Austin"},  # no company or title
            {"company": "Valid", "jobTitle": "Dev"},
        ]
        resp = _legacy_post(client, "indeed.com", signals)
        data = resp.get_json()
        assert data["accepted"] == 1
        assert data["failed"] == 1
        assert db.query(SpEvent).count() == 1
