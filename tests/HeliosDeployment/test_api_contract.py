"""
tests/HeliosDeployment/test_api_contract.py — Dev Req §4: API Contract Requirements

Validates:
    §4.1 — POST /api/contribute (validation, processing order, response codes)
    §4.2 — POST /api/burn (session burn, burn_pool increment)
    §5.3 — Validation rules (all field validations, PII routing)
"""

import json
import uuid

from core.models.spiritpool import BurnPool, Quarantine, SessionEpoch, SpEvent


# ── §4.1 POST /api/contribute ─────────────────────────────────────────────────


class TestContributeEndpoint:
    """Dev Req §4.1 — POST /api/contribute acceptance criteria."""

    # ── Clean signal flow ─────────────────────────────────────────────

    def test_clean_signal_returns_200(self, client, clean_signal):
        """Clean signal stores and returns 200."""
        resp = client.post("/api/contribute", json=clean_signal)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"

    def test_clean_signal_stored_in_sp_events(self, client, clean_signal, engine):
        """Clean signal ends up in sp_events, not quarantine."""
        from sqlalchemy.orm import Session

        client.post("/api/contribute", json=clean_signal)

        with Session(engine) as s:
            events = s.query(SpEvent).all()
            quarantines = s.query(Quarantine).all()
            assert len(events) >= 1
            assert len(quarantines) == 0

    def test_server_sets_event_id(self, client, clean_signal, engine):
        """event_id is server-generated UUID, not from client."""
        client.post("/api/contribute", json=clean_signal)

        from sqlalchemy.orm import Session
        with Session(engine) as s:
            ev = s.query(SpEvent).first()
            assert ev is not None
            # Verify it's a valid UUID format
            uuid.UUID(ev.event_id)  # raises if invalid

    def test_server_sets_collected_at(self, client, clean_signal, engine):
        """collected_at is server-set, not from client."""
        clean_signal["collected_at"] = "2020-01-01T00:00:00Z"  # try to inject
        client.post("/api/contribute", json=clean_signal)

        from sqlalchemy.orm import Session
        with Session(engine) as s:
            ev = s.query(SpEvent).first()
            assert ev is not None
            # Should be close to now, not the injected 2020 date
            assert ev.collected_at.year >= 2026

    def test_server_sets_pipeline_version(self, client, clean_signal, engine):
        """pipeline_version is server-set, always 1."""
        clean_signal["pipeline_version"] = 99  # try to inject
        client.post("/api/contribute", json=clean_signal)

        from sqlalchemy.orm import Session
        with Session(engine) as s:
            ev = s.query(SpEvent).first()
            assert ev is not None
            assert ev.pipeline_version == 1

    def test_session_epoch_auto_created(self, client, clean_signal, engine):
        """First POST for a session_token creates a session_epochs row."""
        client.post("/api/contribute", json=clean_signal)

        from sqlalchemy.orm import Session
        with Session(engine) as s:
            se = s.query(SessionEpoch).filter_by(
                session_token=clean_signal["session_token"]
            ).first()
            assert se is not None
            assert se.epoch_id == clean_signal["epoch_id"]

    def test_session_epoch_not_duplicated(self, client, clean_signal, engine):
        """Second POST with same token does not create duplicate session_epochs."""
        client.post("/api/contribute", json=clean_signal)
        # Second POST, same token
        clean_signal["event_type"] = "salary_signal"
        client.post("/api/contribute", json=clean_signal)

        from sqlalchemy.orm import Session
        with Session(engine) as s:
            epochs = s.query(SessionEpoch).filter_by(
                session_token=clean_signal["session_token"]
            ).all()
            assert len(epochs) == 1

    # ── Field stripping in endpoint ───────────────────────────────────

    def test_taburl_stripped_before_storage(self, client, engine):
        """tabUrl is removed before event is stored."""
        signal = {
            "session_token": "strip-test-tok",
            "epoch_id": 1,
            "event_type": "job_listing",
            "source": "indeed",
            "domain": "jobs",
            "tabUrl": "https://indeed.com/viewjob?jk=abc",
            "payload": {
                "company": "Acme",
                "tabUrl": "https://indeed.com/nested",
            },
        }
        client.post("/api/contribute", json=signal)

        from sqlalchemy.orm import Session
        with Session(engine) as s:
            ev = s.query(SpEvent).filter_by(session_token="strip-test-tok").first()
            assert ev is not None
            payload = ev.payload if isinstance(ev.payload, dict) else json.loads(ev.payload)
            assert "tabUrl" not in payload

    def test_collectedat_stripped_before_storage(self, client, engine):
        """collectedAt is removed before event is stored."""
        signal = {
            "session_token": "strip-test-tok2",
            "epoch_id": 1,
            "event_type": "job_listing",
            "source": "indeed",
            "domain": "jobs",
            "collectedAt": "2026-01-01T00:00:00Z",
            "payload": {
                "company": "Acme",
                "collectedAt": "2026-01-01T00:00:00Z",
            },
        }
        client.post("/api/contribute", json=signal)

        from sqlalchemy.orm import Session
        with Session(engine) as s:
            ev = s.query(SpEvent).filter_by(session_token="strip-test-tok2").first()
            assert ev is not None
            payload = ev.payload if isinstance(ev.payload, dict) else json.loads(ev.payload)
            assert "collectedAt" not in payload

    # ── PII routing ───────────────────────────────────────────────────

    def test_pii_email_routes_to_quarantine(self, client, pii_signal_email, engine):
        """Signal with email PII goes to quarantine, client gets 200."""
        resp = client.post("/api/contribute", json=pii_signal_email)
        assert resp.status_code == 200

        from sqlalchemy.orm import Session
        with Session(engine) as s:
            events = s.query(SpEvent).all()
            quarantines = s.query(Quarantine).all()
            assert len(events) == 0, "PII signal should NOT be in sp_events"
            assert len(quarantines) >= 1

    def test_quarantine_has_redaction_types(self, client, pii_signal_email, engine):
        """Quarantine entry has correct redaction_types."""
        client.post("/api/contribute", json=pii_signal_email)

        from sqlalchemy.orm import Session
        with Session(engine) as s:
            q = s.query(Quarantine).first()
            assert q is not None
            types = json.loads(q.redaction_types)
            assert "email" in types

    def test_pii_phone_routes_to_quarantine(self, client, engine):
        """Signal with phone PII goes to quarantine."""
        signal = {
            "session_token": "phone-test-tok",
            "epoch_id": 1,
            "event_type": "job_listing",
            "source": "indeed",
            "domain": "jobs",
            "payload": {"company": "Acme", "contact": "512-555-1234"},
        }
        client.post("/api/contribute", json=signal)

        from sqlalchemy.orm import Session
        with Session(engine) as s:
            q = s.query(Quarantine).first()
            assert q is not None
            types = json.loads(q.redaction_types)
            assert "phone" in types

    def test_pii_ssn_routes_to_quarantine(self, client, engine):
        """Signal with SSN pattern goes to quarantine."""
        signal = {
            "session_token": "ssn-test-tok",
            "epoch_id": 1,
            "event_type": "job_listing",
            "source": "indeed",
            "domain": "jobs",
            "payload": {"company": "Acme", "notes": "SSN: 123-45-6789"},
        }
        client.post("/api/contribute", json=signal)

        from sqlalchemy.orm import Session
        with Session(engine) as s:
            q = s.query(Quarantine).first()
            assert q is not None
            types = json.loads(q.redaction_types)
            assert "ssn" in types

    def test_multi_pii_all_types_recorded(self, client, engine):
        """Signal with multiple PII types records all in redaction_types."""
        signal = {
            "session_token": "multi-pii-tok",
            "epoch_id": 1,
            "event_type": "job_listing",
            "source": "indeed",
            "domain": "jobs",
            "payload": {
                "contact": "hiring@acme.com",
                "phone": "512-555-1234",
            },
        }
        client.post("/api/contribute", json=signal)

        from sqlalchemy.orm import Session
        with Session(engine) as s:
            q = s.query(Quarantine).first()
            assert q is not None
            types = json.loads(q.redaction_types)
            assert "email" in types
            assert "phone" in types


# ── §4.1 / §5.3 Validation Rules ─────────────────────────────────────────────


class TestContributeValidation:
    """Dev Req §4.1 response codes + §5.3 validation rules."""

    def test_missing_session_token_400(self, client):
        """Missing session_token returns 400."""
        resp = client.post("/api/contribute", json={
            "epoch_id": 1, "event_type": "job_listing",
            "source": "indeed", "domain": "jobs",
            "payload": {"test": True},
        })
        assert resp.status_code == 400

    def test_missing_epoch_id_400(self, client):
        """Missing epoch_id returns 400."""
        resp = client.post("/api/contribute", json={
            "session_token": "tok", "event_type": "job_listing",
            "source": "indeed", "domain": "jobs",
            "payload": {"test": True},
        })
        assert resp.status_code == 400

    def test_epoch_id_zero_400(self, client):
        """epoch_id = 0 returns 400 (must be >= 1)."""
        resp = client.post("/api/contribute", json={
            "session_token": "tok", "epoch_id": 0,
            "event_type": "job_listing",
            "source": "indeed", "domain": "jobs",
            "payload": {"test": True},
        })
        assert resp.status_code == 400

    def test_epoch_id_negative_400(self, client):
        """Negative epoch_id returns 400."""
        resp = client.post("/api/contribute", json={
            "session_token": "tok", "epoch_id": -1,
            "event_type": "job_listing",
            "source": "indeed", "domain": "jobs",
            "payload": {"test": True},
        })
        assert resp.status_code == 400

    def test_invalid_event_type_400(self, client):
        """Invalid event_type returns 400."""
        resp = client.post("/api/contribute", json={
            "session_token": "tok", "epoch_id": 1,
            "event_type": "invalid_type",
            "source": "indeed", "domain": "jobs",
            "payload": {"test": True},
        })
        assert resp.status_code == 400

    def test_missing_source_400(self, client):
        """Missing source returns 400."""
        resp = client.post("/api/contribute", json={
            "session_token": "tok", "epoch_id": 1,
            "event_type": "job_listing",
            "domain": "jobs",
            "payload": {"test": True},
        })
        assert resp.status_code == 400

    def test_invalid_domain_400(self, client):
        """Invalid domain returns 400."""
        resp = client.post("/api/contribute", json={
            "session_token": "tok", "epoch_id": 1,
            "event_type": "job_listing",
            "source": "indeed", "domain": "invalid",
            "payload": {"test": True},
        })
        assert resp.status_code == 400

    def test_missing_payload_400(self, client):
        """Missing payload returns 400."""
        resp = client.post("/api/contribute", json={
            "session_token": "tok", "epoch_id": 1,
            "event_type": "job_listing",
            "source": "indeed", "domain": "jobs",
        })
        assert resp.status_code == 400

    def test_empty_payload_400(self, client):
        """Empty payload dict returns 400."""
        resp = client.post("/api/contribute", json={
            "session_token": "tok", "epoch_id": 1,
            "event_type": "job_listing",
            "source": "indeed", "domain": "jobs",
            "payload": {},
        })
        assert resp.status_code == 400

    def test_invalid_json_body_400(self, client):
        """Non-JSON body returns 400."""
        resp = client.post(
            "/api/contribute",
            data="not json",
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_all_valid_domains_accepted(self, client):
        """All three valid domains (jobs, events, business) return 200."""
        for domain in ("jobs", "events", "business"):
            resp = client.post("/api/contribute", json={
                "session_token": f"domain-test-{domain}",
                "epoch_id": 1,
                "event_type": "job_listing",
                "source": "test",
                "domain": domain,
                "payload": {"test": True},
            })
            assert resp.status_code == 200, f"Domain {domain} rejected"

    def test_all_valid_event_types_accepted(self, client):
        """All four valid event types return 200."""
        for etype in ("job_listing", "salary_signal", "business_review", "event_listing"):
            resp = client.post("/api/contribute", json={
                "session_token": f"etype-test-{etype}",
                "epoch_id": 1,
                "event_type": etype,
                "source": "test",
                "domain": "jobs",
                "payload": {"test": True},
            })
            assert resp.status_code == 200, f"Event type {etype} rejected"


# ── §4.2 POST /api/burn ──────────────────────────────────────────────────────


class TestBurnEndpoint:
    """Dev Req §4.2 — POST /api/burn acceptance criteria."""

    def _setup_session(self, client, token="burn-tok"):
        """Helper: create a session_epochs row via a contribute POST."""
        client.post("/api/contribute", json={
            "session_token": token,
            "epoch_id": 1,
            "event_type": "job_listing",
            "source": "test",
            "domain": "jobs",
            "payload": {"test": True},
        })

    def test_burn_returns_200(self, client):
        """Burn endpoint returns 200."""
        self._setup_session(client)
        resp = client.post("/api/burn", json={"session_token": "burn-tok"})
        assert resp.status_code == 200

    def test_burn_sets_contributor_id_null(self, client, engine):
        """Burn sets session_epochs.contributor_id = NULL."""
        self._setup_session(client, "burn-null-tok")
        client.post("/api/burn", json={"session_token": "burn-null-tok"})

        from sqlalchemy.orm import Session
        with Session(engine) as s:
            se = s.query(SessionEpoch).filter_by(session_token="burn-null-tok").first()
            if se:
                assert se.contributor_id is None

    def test_burn_sets_burned_at(self, client, engine):
        """Burn sets session_epochs.burned_at to a timestamp."""
        self._setup_session(client, "burn-ts-tok")
        client.post("/api/burn", json={"session_token": "burn-ts-tok"})

        from sqlalchemy.orm import Session
        with Session(engine) as s:
            se = s.query(SessionEpoch).filter_by(session_token="burn-ts-tok").first()
            if se:
                assert se.burned_at is not None

    def test_burn_increments_burn_pool(self, client, engine):
        """Burn creates/increments burn_pool entry for current month."""
        self._setup_session(client, "burn-pool-tok")
        client.post("/api/burn", json={"session_token": "burn-pool-tok"})

        from sqlalchemy.orm import Session
        with Session(engine) as s:
            pools = s.query(BurnPool).all()
            assert len(pools) >= 1
            assert pools[0].signal_count >= 1

    def test_burn_pool_has_expiry(self, client, engine):
        """Burn pool entry has expires_at set (~1 year from burned_at)."""
        self._setup_session(client, "burn-exp-tok")
        client.post("/api/burn", json={"session_token": "burn-exp-tok"})

        from sqlalchemy.orm import Session
        with Session(engine) as s:
            bp = s.query(BurnPool).first()
            assert bp is not None
            assert bp.expires_at is not None
            delta = bp.expires_at - bp.burned_at
            assert 364 <= delta.days <= 366

    def test_burn_missing_token_400(self, client):
        """Missing session_token returns 400."""
        resp = client.post("/api/burn", json={})
        assert resp.status_code == 400

    def test_burn_nonexistent_token_200(self, client):
        """Burning a non-existent token still returns 200 (idempotent)."""
        resp = client.post("/api/burn", json={"session_token": "does-not-exist"})
        assert resp.status_code == 200
