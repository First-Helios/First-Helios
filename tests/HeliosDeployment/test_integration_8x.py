"""
tests/HeliosDeployment/test_integration_8x.py — Integration Test Suite §8.1–8.5

End-to-end pipeline validation from the SpiritPool × Helios Handoff document (§8).
These tests verify that all Tier 1–3 components work together correctly:
    field stripping + PII detection + IP suppression + storage + session management

    §8.1 — End-to-End Signal Flow
    §8.2 — PII Defence-in-Depth
    §8.3 — Config Signing Validation (backend resilience)
    §8.4 — Token Rotation
    §8.5 — Forward-Compatibility (Second/Third Helios readiness)

Each test exercises the full POST /api/contribute → database path, not isolated units.
"""

import json
import logging
import uuid

from sqlalchemy.orm import Session

from core.models.spiritpool import Quarantine, SessionEpoch, SpEvent


# ── §8.1 End-to-End Signal Flow ─────────────────────────────────────────────


class TestEndToEndSignalFlow:
    """§8.1 — A realistic signal enters the pipeline and arrives in sp_events
    with all privacy controls applied and server-side fields set correctly.

    Input:  Signal with salary, observedAt, tabUrl, collectedAt
    Assert: Event in sp_events table, no tabUrl, no collectedAt,
            server timestamp, no IP in logs, pipeline_version = 1
    """

    def _realistic_signal(self):
        """A signal mimicking a real extension payload — includes fields
        that MUST be stripped (tabUrl, collectedAt) and fields that should
        pass through (salary, observedAt, company, jobTitle)."""
        return {
            "session_token": "e2e-flow-" + str(uuid.uuid4())[:8],
            "epoch_id": 1,
            "event_type": "job_listing",
            "source": "indeed",
            "domain": "jobs",
            "tabUrl": "https://www.indeed.com/viewjob?jk=abc123",
            "collectedAt": "2026-04-05T12:00:00Z",
            "payload": {
                "company": "Whole Foods Market",
                "jobTitle": "Grocery Team Member",
                "location": "Austin, TX 78701",
                "salary": 75000,
                "observedAt": "2026-04-05T12:05:00Z",
                "badges": ["urgently hiring", "health insurance"],
                "tabUrl": "https://www.indeed.com/viewjob?jk=abc123",
                "collectedAt": "2026-04-05T12:00:00Z",
            },
        }

    def test_signal_stored_in_sp_events(self, client, engine):
        """Clean signal with stripped fields ends up in sp_events."""
        signal = self._realistic_signal()
        resp = client.post("/api/contribute", json=signal)
        assert resp.status_code == 200

        with Session(engine) as s:
            ev = s.query(SpEvent).filter_by(
                session_token=signal["session_token"]
            ).first()
            assert ev is not None, "Event not found in sp_events"

    def test_no_taburl_in_stored_event(self, client, engine):
        """tabUrl stripped from both top-level body and nested payload."""
        signal = self._realistic_signal()
        client.post("/api/contribute", json=signal)

        with Session(engine) as s:
            ev = s.query(SpEvent).filter_by(
                session_token=signal["session_token"]
            ).first()
            payload = ev.payload if isinstance(ev.payload, dict) else json.loads(ev.payload)
            assert "tabUrl" not in payload, "tabUrl leaked into stored payload"

    def test_no_collectedat_in_stored_event(self, client, engine):
        """collectedAt stripped from both top-level body and nested payload."""
        signal = self._realistic_signal()
        client.post("/api/contribute", json=signal)

        with Session(engine) as s:
            ev = s.query(SpEvent).filter_by(
                session_token=signal["session_token"]
            ).first()
            payload = ev.payload if isinstance(ev.payload, dict) else json.loads(ev.payload)
            assert "collectedAt" not in payload, "collectedAt leaked into stored payload"

    def test_server_sets_collected_at(self, client, engine):
        """collected_at reflects server time, not the client-sent collectedAt."""
        signal = self._realistic_signal()
        client.post("/api/contribute", json=signal)

        with Session(engine) as s:
            ev = s.query(SpEvent).filter_by(
                session_token=signal["session_token"]
            ).first()
            assert ev.collected_at is not None
            # Server timestamp should be recent (2026+), not the injected 2020 date
            assert ev.collected_at.year >= 2026

    def test_pipeline_version_is_1(self, client, engine):
        """pipeline_version always set to 1 (First Helios PII rule version)."""
        signal = self._realistic_signal()
        client.post("/api/contribute", json=signal)

        with Session(engine) as s:
            ev = s.query(SpEvent).filter_by(
                session_token=signal["session_token"]
            ).first()
            assert ev.pipeline_version == 1

    def test_session_token_preserved(self, client, engine):
        """session_token stored exactly as sent — opaque, no transformation."""
        signal = self._realistic_signal()
        client.post("/api/contribute", json=signal)

        with Session(engine) as s:
            ev = s.query(SpEvent).filter_by(
                session_token=signal["session_token"]
            ).first()
            assert ev.session_token == signal["session_token"]

    def test_epoch_id_preserved(self, client, engine):
        """epoch_id stored exactly as sent."""
        signal = self._realistic_signal()
        client.post("/api/contribute", json=signal)

        with Session(engine) as s:
            ev = s.query(SpEvent).filter_by(
                session_token=signal["session_token"]
            ).first()
            assert ev.epoch_id == signal["epoch_id"]

    def test_session_epoch_auto_created(self, client, engine):
        """First POST auto-creates a session_epochs row for the token."""
        signal = self._realistic_signal()
        client.post("/api/contribute", json=signal)

        with Session(engine) as s:
            se = s.query(SessionEpoch).filter_by(
                session_token=signal["session_token"]
            ).first()
            assert se is not None, "session_epochs row not auto-created"
            assert se.epoch_id == signal["epoch_id"]

    def test_clean_payload_fields_preserved(self, client, engine):
        """Legitimate payload fields (salary, observedAt, badges) survive intact."""
        signal = self._realistic_signal()
        client.post("/api/contribute", json=signal)

        with Session(engine) as s:
            ev = s.query(SpEvent).filter_by(
                session_token=signal["session_token"]
            ).first()
            payload = ev.payload if isinstance(ev.payload, dict) else json.loads(ev.payload)
            assert payload["salary"] == 75000
            assert payload["observedAt"] == "2026-04-05T12:05:00Z"
            assert payload["company"] == "Whole Foods Market"
            assert payload["badges"] == ["urgently hiring", "health insurance"]

    def test_not_in_quarantine(self, client, engine):
        """A clean signal does NOT end up in quarantine."""
        signal = self._realistic_signal()
        client.post("/api/contribute", json=signal)

        with Session(engine) as s:
            quarantines = s.query(Quarantine).all()
            assert len(quarantines) == 0, "Clean signal should not be quarantined"

    def test_no_ip_in_request_context(self, app):
        """request.remote_addr is always 0.0.0.0 — IP suppression active."""
        with app.test_request_context(environ_base={"REMOTE_ADDR": "192.168.1.100"}):
            from flask import request
            assert request.remote_addr == "0.0.0.0"

    def test_no_ip_in_log_output(self, client, caplog):
        """No IP address patterns appear in log output during signal processing."""
        import re

        signal = self._realistic_signal()
        with caplog.at_level(logging.DEBUG):
            client.post("/api/contribute", json=signal)

        full_log = caplog.text
        # IPv4 pattern
        ipv4_matches = re.findall(
            r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b",
            full_log,
        )
        # Filter out 0.0.0.0 (our redacted placeholder)
        real_ips = [ip for ip in ipv4_matches if ip != "0.0.0.0"]
        assert real_ips == [], f"Real IP found in logs: {real_ips}"

    def test_event_id_is_server_generated_uuid(self, client, engine):
        """event_id is a valid UUID set by the server, not the client."""
        signal = self._realistic_signal()
        client.post("/api/contribute", json=signal)

        with Session(engine) as s:
            ev = s.query(SpEvent).filter_by(
                session_token=signal["session_token"]
            ).first()
            # Must be a valid UUID
            parsed = uuid.UUID(ev.event_id)
            assert str(parsed) == ev.event_id

    def test_source_type_is_extension(self, client, engine):
        """source_type defaults to 'extension'."""
        signal = self._realistic_signal()
        client.post("/api/contribute", json=signal)

        with Session(engine) as s:
            ev = s.query(SpEvent).filter_by(
                session_token=signal["session_token"]
            ).first()
            assert ev.source_type == "extension"


# ── §8.2 PII Defence-in-Depth ───────────────────────────────────────────────


class TestPIIDefenceInDepth:
    """§8.2 — PII in payload triggers quarantine, not events table.

    The extension's sanitize does not catch payload PII (not its job — it strips
    metadata, not payload PII). The backend PII rule engine catches it.
    Client always receives 200 regardless of quarantine/clean routing.
    """

    def _base_signal(self, token_suffix, payload):
        return {
            "session_token": f"pii-test-{token_suffix}",
            "epoch_id": 1,
            "event_type": "job_listing",
            "source": "indeed",
            "domain": "jobs",
            "payload": payload,
        }

    # ── Email PII ────────────────────────────────────────────────────

    def test_email_quarantined(self, client, engine):
        """Email in payload → quarantine, NOT sp_events."""
        signal = self._base_signal("email", {
            "company": "Acme Corp",
            "jobTitle": "Sales Rep",
            "contact": "test@example.com",
        })
        resp = client.post("/api/contribute", json=signal)
        assert resp.status_code == 200, "Client must get 200 even on quarantine"

        with Session(engine) as s:
            events = s.query(SpEvent).filter_by(
                session_token=signal["session_token"]
            ).all()
            quarantines = s.query(Quarantine).all()

            assert len(events) == 0, "PII signal must NOT be in sp_events"
            assert len(quarantines) >= 1, "PII signal must be in quarantine"

    def test_email_redaction_type_recorded(self, client, engine):
        """Quarantine record has redaction_types: ['email']."""
        signal = self._base_signal("email-type", {
            "company": "Acme",
            "recruiter": "hiring@acme.com",
        })
        client.post("/api/contribute", json=signal)

        with Session(engine) as s:
            q = s.query(Quarantine).first()
            types = json.loads(q.redaction_types)
            assert "email" in types

    # ── Phone PII ────────────────────────────────────────────────────

    def test_phone_quarantined(self, client, engine):
        """Phone number in payload → quarantine."""
        signal = self._base_signal("phone", {
            "company": "Acme",
            "contact_phone": "512-555-1234",
        })
        resp = client.post("/api/contribute", json=signal)
        assert resp.status_code == 200

        with Session(engine) as s:
            events = s.query(SpEvent).filter_by(
                session_token=signal["session_token"]
            ).all()
            quarantines = s.query(Quarantine).all()
            assert len(events) == 0
            assert len(quarantines) >= 1

    def test_phone_redaction_type_recorded(self, client, engine):
        """Quarantine record has 'phone' in redaction_types."""
        signal = self._base_signal("phone-type", {
            "company": "Acme",
            "call": "(512) 555-1234",
        })
        client.post("/api/contribute", json=signal)

        with Session(engine) as s:
            q = s.query(Quarantine).first()
            types = json.loads(q.redaction_types)
            assert "phone" in types

    # ── SSN PII ──────────────────────────────────────────────────────

    def test_ssn_quarantined(self, client, engine):
        """SSN pattern in payload → quarantine."""
        signal = self._base_signal("ssn", {
            "company": "Acme",
            "notes": "Background check: SSN 123-45-6789",
        })
        resp = client.post("/api/contribute", json=signal)
        assert resp.status_code == 200

        with Session(engine) as s:
            events = s.query(SpEvent).filter_by(
                session_token=signal["session_token"]
            ).all()
            quarantines = s.query(Quarantine).all()
            assert len(events) == 0
            assert len(quarantines) >= 1

    def test_ssn_redaction_type_recorded(self, client, engine):
        """Quarantine record has 'ssn' in redaction_types."""
        signal = self._base_signal("ssn-type", {
            "id_info": "SSN: 123-45-6789",
        })
        client.post("/api/contribute", json=signal)

        with Session(engine) as s:
            q = s.query(Quarantine).first()
            types = json.loads(q.redaction_types)
            assert "ssn" in types

    # ── Multi-PII ────────────────────────────────────────────────────

    def test_multi_pii_all_types_in_redaction(self, client, engine):
        """Multiple PII types → quarantine with ALL matching types listed."""
        signal = self._base_signal("multi-pii", {
            "company": "Acme",
            "recruiter_email": "hr@acme.com",
            "recruiter_phone": "512-555-9999",
            "background": "SSN: 987-65-4321",
        })
        resp = client.post("/api/contribute", json=signal)
        assert resp.status_code == 200

        with Session(engine) as s:
            events = s.query(SpEvent).filter_by(
                session_token=signal["session_token"]
            ).all()
            q = s.query(Quarantine).first()

            assert len(events) == 0, "Multi-PII signal must NOT be in sp_events"
            assert q is not None
            types = json.loads(q.redaction_types)
            assert "email" in types
            assert "phone" in types
            assert "ssn" in types

    # ── Deeply nested PII ────────────────────────────────────────────

    def test_nested_pii_detected(self, client, engine):
        """PII buried in nested payload structure still triggers quarantine."""
        signal = self._base_signal("nested-pii", {
            "company": "Acme",
            "details": {
                "hiring_manager": {
                    "contact": "hidden@acme.com",
                },
            },
        })
        resp = client.post("/api/contribute", json=signal)
        assert resp.status_code == 200

        with Session(engine) as s:
            events = s.query(SpEvent).filter_by(
                session_token=signal["session_token"]
            ).all()
            quarantines = s.query(Quarantine).all()
            assert len(events) == 0
            assert len(quarantines) >= 1

    # ── Clean payload passes through ─────────────────────────────────

    def test_clean_payload_not_quarantined(self, client, engine):
        """Payload without PII flows to sp_events unaffected."""
        signal = self._base_signal("clean", {
            "company": "Whole Foods",
            "jobTitle": "Team Member",
            "salary": {"min": 16, "max": 20, "period": "hourly"},
            "location": "Austin, TX 78701",
        })
        resp = client.post("/api/contribute", json=signal)
        assert resp.status_code == 200

        with Session(engine) as s:
            events = s.query(SpEvent).filter_by(
                session_token=signal["session_token"]
            ).all()
            quarantines = s.query(Quarantine).all()
            assert len(events) == 1
            assert len(quarantines) == 0

    # ── Quarantine preserves original payload ─────────────────────────

    def test_quarantine_stores_original_payload(self, client, engine):
        """Quarantine entry preserves the complete original event body."""
        signal = self._base_signal("preserve", {
            "company": "Acme",
            "jobTitle": "Engineer",
            "contact": "user@example.com",
        })
        client.post("/api/contribute", json=signal)

        with Session(engine) as s:
            q = s.query(Quarantine).first()
            assert q is not None
            stored = q.original_payload if isinstance(q.original_payload, dict) else json.loads(q.original_payload)
            # The full body (post-strip) should be stored
            assert stored.get("session_token") == signal["session_token"]

    # ── Session epoch still created for quarantined signals ───────────

    def test_session_epoch_created_for_quarantined(self, client, engine):
        """Session epoch auto-created even when signal is quarantined."""
        signal = self._base_signal("epoch-quarantine", {
            "company": "Acme",
            "contact": "pii@acme.com",
        })
        client.post("/api/contribute", json=signal)

        with Session(engine) as s:
            se = s.query(SessionEpoch).filter_by(
                session_token=signal["session_token"]
            ).first()
            assert se is not None, "session_epoch must be created even for quarantined signals"

    # ── Rule version tracking ────────────────────────────────────────

    def test_quarantine_rule_version_matches_pipeline(self, client, engine):
        """Quarantine rule_version matches current pipeline_version (1)."""
        signal = self._base_signal("rule-ver", {
            "contact": "test@test.com",
        })
        client.post("/api/contribute", json=signal)

        with Session(engine) as s:
            q = s.query(Quarantine).first()
            assert q.rule_version == 1


# ── §8.3 Config Signing Validation ──────────────────────────────────────────


class TestConfigSigningValidation:
    """§8.3 — Backend does not crash on signals from extension using fallback selectors.

    The config signing system is extension-side. The backend's contract is simpler:
    accept well-formed signals regardless of how the extension determined what to scrape.
    Signals from bundled selectors, signed remote config, or fallback selectors all look
    the same to the backend — the only difference is payload shape, which is JSONB and
    accepts unknown fields by design.

    These tests verify the backend handles varied payload shapes gracefully.
    """

    def _signal_with_payload(self, token_suffix, payload):
        return {
            "session_token": f"config-sign-{token_suffix}",
            "epoch_id": 1,
            "event_type": "job_listing",
            "source": "indeed",
            "domain": "jobs",
            "payload": payload,
        }

    def test_bundled_selector_payload(self, client, engine):
        """Signal from bundled selectors (standard fields) accepted."""
        signal = self._signal_with_payload("bundled", {
            "company": "Google",
            "jobTitle": "Software Engineer",
            "location": "Austin, TX",
            "salary": {"min": 120000, "max": 180000, "period": "yearly"},
            "postingDate": "2026-04-01",
        })
        resp = client.post("/api/contribute", json=signal)
        assert resp.status_code == 200

        with Session(engine) as s:
            ev = s.query(SpEvent).filter_by(
                session_token=signal["session_token"]
            ).first()
            assert ev is not None

    def test_fallback_selector_minimal_payload(self, client, engine):
        """Signal from fallback selectors (minimal fields) accepted.

        When signed remote config fails verification, the extension falls back
        to bundled selectors. If those don't match either, minimal extraction
        occurs. The backend must still accept the signal.
        """
        signal = self._signal_with_payload("fallback", {
            "raw_text": "Software Engineer - Austin, TX - $120k-$180k",
        })
        resp = client.post("/api/contribute", json=signal)
        assert resp.status_code == 200

        with Session(engine) as s:
            ev = s.query(SpEvent).filter_by(
                session_token=signal["session_token"]
            ).first()
            assert ev is not None

    def test_remote_config_extra_fields_accepted(self, client, engine):
        """Signal with extra fields from signed remote config accepted.

        Remote config may define selectors that extract fields not in the
        bundled schema. JSONB payload must preserve them.
        """
        signal = self._signal_with_payload("remote-extra", {
            "company": "Apple",
            "jobTitle": "ML Engineer",
            "remote_config_field": "extracted_by_remote_selector",
            "custom_badge_v2": ["top employer", "visa sponsor"],
            "extraction_confidence": 0.95,
        })
        resp = client.post("/api/contribute", json=signal)
        assert resp.status_code == 200

        with Session(engine) as s:
            ev = s.query(SpEvent).filter_by(
                session_token=signal["session_token"]
            ).first()
            payload = ev.payload if isinstance(ev.payload, dict) else json.loads(ev.payload)
            assert payload["remote_config_field"] == "extracted_by_remote_selector"
            assert payload["extraction_confidence"] == 0.95

    def test_deeply_nested_payload_accepted(self, client, engine):
        """Complex nested payload from advanced selectors doesn't crash backend."""
        signal = self._signal_with_payload("deep-nest", {
            "company": "Meta",
            "structured": {
                "compensation": {
                    "base": {"min": 150000, "max": 200000, "currency": "USD"},
                    "equity": {"vesting_years": 4, "refresh": True},
                    "benefits": ["health", "401k", "remote"],
                },
                "requirements": {
                    "years_experience": 5,
                    "skills": ["python", "pytorch", "distributed systems"],
                },
            },
        })
        resp = client.post("/api/contribute", json=signal)
        assert resp.status_code == 200

        with Session(engine) as s:
            ev = s.query(SpEvent).filter_by(
                session_token=signal["session_token"]
            ).first()
            payload = ev.payload if isinstance(ev.payload, dict) else json.loads(ev.payload)
            assert payload["structured"]["compensation"]["base"]["min"] == 150000

    def test_all_event_types_accepted_with_varied_payloads(self, client, engine):
        """All four event types work with domain-appropriate payloads."""
        type_payloads = {
            "job_listing": {"company": "Acme", "jobTitle": "Clerk"},
            "salary_signal": {"role": "Engineer", "wage": 45.00},
            "business_review": {"business": "Joe's Coffee", "rating": 4.5},
            "event_listing": {"event_name": "PyCon", "venue": "ACC"},
        }
        for etype, payload in type_payloads.items():
            signal = self._signal_with_payload(f"etype-{etype}", payload)
            signal["event_type"] = etype
            resp = client.post("/api/contribute", json=signal)
            assert resp.status_code == 200, f"event_type={etype} rejected"

    def test_server_does_not_crash_on_empty_string_values(self, client, engine):
        """Payload with empty string values doesn't crash the pipeline."""
        signal = self._signal_with_payload("empty-strings", {
            "company": "",
            "jobTitle": "Unknown",
            "location": "",
        })
        resp = client.post("/api/contribute", json=signal)
        assert resp.status_code == 200


# ── §8.4 Token Rotation ────────────────────────────────────────────────────


class TestTokenRotation:
    """§8.4 — Multiple tokens from the same contributor stored independently.

    Simulates token rotation: POST with token A, then POST with token B
    (incremented epoch_id). Both events stored. Session epochs has rows for both.
    No cross-contamination between sessions.
    """

    TOKEN_A = "rotation-token-A-" + str(uuid.uuid4())[:8]
    TOKEN_B = "rotation-token-B-" + str(uuid.uuid4())[:8]

    def _post_with_token(self, client, token, epoch_id, payload_tag):
        return client.post("/api/contribute", json={
            "session_token": token,
            "epoch_id": epoch_id,
            "event_type": "job_listing",
            "source": "indeed",
            "domain": "jobs",
            "payload": {"tag": payload_tag, "company": "Acme"},
        })

    def test_both_tokens_accepted(self, client):
        """POST with token A and token B both return 200."""
        resp_a = self._post_with_token(client, self.TOKEN_A, 1, "signal-A")
        resp_b = self._post_with_token(client, self.TOKEN_B, 2, "signal-B")
        assert resp_a.status_code == 200
        assert resp_b.status_code == 200

    def test_both_events_stored(self, client, engine):
        """Both signals stored in sp_events."""
        self._post_with_token(client, self.TOKEN_A, 1, "signal-A")
        self._post_with_token(client, self.TOKEN_B, 2, "signal-B")

        with Session(engine) as s:
            ev_a = s.query(SpEvent).filter_by(session_token=self.TOKEN_A).first()
            ev_b = s.query(SpEvent).filter_by(session_token=self.TOKEN_B).first()
            assert ev_a is not None, "Token A event not stored"
            assert ev_b is not None, "Token B event not stored"

    def test_separate_session_epochs(self, client, engine):
        """Each token gets its own session_epochs row."""
        self._post_with_token(client, self.TOKEN_A, 1, "signal-A")
        self._post_with_token(client, self.TOKEN_B, 2, "signal-B")

        with Session(engine) as s:
            se_a = s.query(SessionEpoch).filter_by(session_token=self.TOKEN_A).first()
            se_b = s.query(SessionEpoch).filter_by(session_token=self.TOKEN_B).first()
            assert se_a is not None, "Token A session epoch not created"
            assert se_b is not None, "Token B session epoch not created"

    def test_epoch_ids_correct(self, client, engine):
        """Token A has epoch_id=1, token B has epoch_id=2 (incremented)."""
        self._post_with_token(client, self.TOKEN_A, 1, "signal-A")
        self._post_with_token(client, self.TOKEN_B, 2, "signal-B")

        with Session(engine) as s:
            se_a = s.query(SessionEpoch).filter_by(session_token=self.TOKEN_A).first()
            se_b = s.query(SessionEpoch).filter_by(session_token=self.TOKEN_B).first()
            assert se_a.epoch_id == 1
            assert se_b.epoch_id == 2

    def test_no_cross_contamination(self, client, engine):
        """Token A events are not visible under token B and vice versa."""
        self._post_with_token(client, self.TOKEN_A, 1, "signal-A")
        self._post_with_token(client, self.TOKEN_B, 2, "signal-B")

        with Session(engine) as s:
            events_a = s.query(SpEvent).filter_by(session_token=self.TOKEN_A).all()
            events_b = s.query(SpEvent).filter_by(session_token=self.TOKEN_B).all()

            # Each token should have exactly 1 event
            assert len(events_a) == 1
            assert len(events_b) == 1

            # Payloads should be distinct
            payload_a = events_a[0].payload if isinstance(events_a[0].payload, dict) else json.loads(events_a[0].payload)
            payload_b = events_b[0].payload if isinstance(events_b[0].payload, dict) else json.loads(events_b[0].payload)
            assert payload_a["tag"] == "signal-A"
            assert payload_b["tag"] == "signal-B"

    def test_multiple_events_per_token(self, client, engine):
        """Multiple POSTs with the same token create multiple events,
        but only one session_epochs row."""
        token = "multi-event-" + str(uuid.uuid4())[:8]
        self._post_with_token(client, token, 1, "first")
        self._post_with_token(client, token, 1, "second")
        self._post_with_token(client, token, 1, "third")

        with Session(engine) as s:
            events = s.query(SpEvent).filter_by(session_token=token).all()
            epochs = s.query(SessionEpoch).filter_by(session_token=token).all()
            assert len(events) == 3, "Three events expected for same token"
            assert len(epochs) == 1, "Only one session_epoch per token"

    def test_burned_token_does_not_affect_new_token(self, client, engine):
        """Burning token A does not affect token B."""
        token_burn = "burn-isolation-A-" + str(uuid.uuid4())[:8]
        token_keep = "burn-isolation-B-" + str(uuid.uuid4())[:8]

        self._post_with_token(client, token_burn, 1, "to-burn")
        self._post_with_token(client, token_keep, 2, "to-keep")

        # Burn token A
        client.post("/api/burn", json={"session_token": token_burn})

        with Session(engine) as s:
            se_burned = s.query(SessionEpoch).filter_by(session_token=token_burn).first()
            se_kept = s.query(SessionEpoch).filter_by(session_token=token_keep).first()

            assert se_burned.burned_at is not None, "Token A should be burned"
            assert se_kept.burned_at is None, "Token B should NOT be burned"


# ── §8.5 Forward-Compatibility ──────────────────────────────────────────────


class TestForwardCompatibility:
    """§8.5 — Backend accepts Second and Third Helios data without modification.

    - 64-char hex session_token (simulating Second Helios HMAC-SHA256 hash_token)
    - Large epoch_id (simulating many consent changes over time)
    - Unknown JSONB fields (simulating Third Helios EDN fields in consent_state/payload)
    - All must store successfully without error or truncation.

    If any of these fail, the schema or validation logic has a forward-compatibility
    bug that must be fixed before it ships.
    """

    # Second Helios: HMAC-SHA256 hash_token (64-char hex)
    SECOND_HELIOS_TOKEN = "a3f2b8c1d4e5f6789012345678abcdef0123456789abcdef0123456789abcdef"
    # Third Helios: VOPRF unblinded output (64-char hex)
    THIRD_HELIOS_TOKEN = "b7e2c9d1f5a6b8901234567890abcdef1234567890abcdef1234567890abcdef"

    def test_64_char_hex_token_stores(self, client, engine):
        """64-char hex session_token (Second Helios hash_token) stores without error."""
        resp = client.post("/api/contribute", json={
            "session_token": self.SECOND_HELIOS_TOKEN,
            "epoch_id": 1,
            "event_type": "job_listing",
            "source": "indeed",
            "domain": "jobs",
            "payload": {"company": "Acme", "jobTitle": "Engineer"},
        })
        assert resp.status_code == 200

        with Session(engine) as s:
            ev = s.query(SpEvent).filter_by(
                session_token=self.SECOND_HELIOS_TOKEN
            ).first()
            assert ev is not None
            assert ev.session_token == self.SECOND_HELIOS_TOKEN
            assert len(ev.session_token) == 64, "Token truncated!"

    def test_third_helios_token_stores(self, client, engine):
        """Third Helios VOPRF token (64-char hex) stores without error."""
        resp = client.post("/api/contribute", json={
            "session_token": self.THIRD_HELIOS_TOKEN,
            "epoch_id": 1,
            "event_type": "salary_signal",
            "source": "linkedin",
            "domain": "jobs",
            "payload": {"role": "Data Scientist", "wage": 55.00},
        })
        assert resp.status_code == 200

        with Session(engine) as s:
            ev = s.query(SpEvent).filter_by(
                session_token=self.THIRD_HELIOS_TOKEN
            ).first()
            assert ev is not None
            assert len(ev.session_token) == 64

    def test_large_epoch_id(self, client, engine):
        """Large epoch_id (many consent changes) stores without overflow."""
        large_epoch = 999999
        resp = client.post("/api/contribute", json={
            "session_token": "large-epoch-test",
            "epoch_id": large_epoch,
            "event_type": "job_listing",
            "source": "glassdoor",
            "domain": "jobs",
            "payload": {"company": "BigCo"},
        })
        assert resp.status_code == 200

        with Session(engine) as s:
            ev = s.query(SpEvent).filter_by(session_token="large-epoch-test").first()
            assert ev is not None
            assert ev.epoch_id == large_epoch

    def test_very_large_epoch_id(self, client, engine):
        """Very large epoch_id (edge case) stores without overflow."""
        very_large = 2147483647  # max 32-bit signed integer
        resp = client.post("/api/contribute", json={
            "session_token": "vlarge-epoch-test",
            "epoch_id": very_large,
            "event_type": "job_listing",
            "source": "indeed",
            "domain": "jobs",
            "payload": {"company": "EdgeCase Inc"},
        })
        assert resp.status_code == 200

        with Session(engine) as s:
            ev = s.query(SpEvent).filter_by(session_token="vlarge-epoch-test").first()
            assert ev.epoch_id == very_large

    def test_unknown_jsonb_fields_preserved(self, client, engine):
        """Unknown JSONB fields in payload preserved exactly (future era fields)."""
        payload = {
            "company": "Acme",
            "jobTitle": "Engineer",
            # Third Helios EDN fields — unknown to First Helios
            "edn_hosting_consent": True,
            "edn_account_consent": {"scope": "full", "expires": "2027-01-01"},
            "resource_limits": {"cpu": 4, "memory_gb": 16},
            "future_field_v4": [1, 2, 3, {"nested": "value"}],
        }
        resp = client.post("/api/contribute", json={
            "session_token": "unknown-fields-test",
            "epoch_id": 1,
            "event_type": "business_review",
            "source": "google_maps",
            "domain": "business",
            "payload": payload,
        })
        assert resp.status_code == 200

        with Session(engine) as s:
            ev = s.query(SpEvent).filter_by(session_token="unknown-fields-test").first()
            stored = ev.payload if isinstance(ev.payload, dict) else json.loads(ev.payload)
            assert stored["edn_hosting_consent"] is True
            assert stored["edn_account_consent"]["scope"] == "full"
            assert stored["resource_limits"]["cpu"] == 4
            assert stored["future_field_v4"] == [1, 2, 3, {"nested": "value"}]

    def test_64_char_token_session_epoch(self, client, engine):
        """64-char hex token creates a session_epoch without error."""
        token = "c" * 64  # another 64-char token
        client.post("/api/contribute", json={
            "session_token": token,
            "epoch_id": 42,
            "event_type": "event_listing",
            "source": "eventbrite",
            "domain": "events",
            "payload": {"event_name": "Test Event"},
        })

        with Session(engine) as s:
            se = s.query(SessionEpoch).filter_by(session_token=token).first()
            assert se is not None
            assert len(se.session_token) == 64
            assert se.epoch_id == 42

    def test_first_helios_uuid_token_still_works(self, client, engine):
        """Standard 36-char UUID token (First Helios) still accepted alongside
        64-char hex tokens — backward compatibility within forward-compat."""
        uuid_token = str(uuid.uuid4())
        resp = client.post("/api/contribute", json={
            "session_token": uuid_token,
            "epoch_id": 1,
            "event_type": "job_listing",
            "source": "indeed",
            "domain": "jobs",
            "payload": {"company": "Legacy Corp"},
        })
        assert resp.status_code == 200

        with Session(engine) as s:
            ev = s.query(SpEvent).filter_by(session_token=uuid_token).first()
            assert ev is not None
            assert len(ev.session_token) == 36

    def test_mixed_era_tokens_coexist(self, client, engine):
        """First Helios UUID and Second Helios hex tokens can coexist
        in the same database without conflict."""
        uuid_token = str(uuid.uuid4())
        hex_token = "d" * 64

        client.post("/api/contribute", json={
            "session_token": uuid_token,
            "epoch_id": 1,
            "event_type": "job_listing",
            "source": "indeed",
            "domain": "jobs",
            "payload": {"era": "first"},
        })
        client.post("/api/contribute", json={
            "session_token": hex_token,
            "epoch_id": 1,
            "event_type": "job_listing",
            "source": "indeed",
            "domain": "jobs",
            "payload": {"era": "second"},
        })

        with Session(engine) as s:
            ev_first = s.query(SpEvent).filter_by(session_token=uuid_token).first()
            ev_second = s.query(SpEvent).filter_by(session_token=hex_token).first()
            assert ev_first is not None
            assert ev_second is not None

            payload_first = ev_first.payload if isinstance(ev_first.payload, dict) else json.loads(ev_first.payload)
            payload_second = ev_second.payload if isinstance(ev_second.payload, dict) else json.loads(ev_second.payload)
            assert payload_first["era"] == "first"
            assert payload_second["era"] == "second"
