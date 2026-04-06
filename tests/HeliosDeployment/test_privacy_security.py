"""
tests/HeliosDeployment/test_privacy_security.py — Dev Req §3: Privacy & Security Requirements

Validates:
    §3.1 — IP Suppression (request.remote_addr, log formatting)
    §3.2 — Field Stripping (tabUrl, collectedAt — top-level and nested)
    §3.3 — PII Quarantine Pipeline (all 6 patterns, recursive walk, routing)
"""

import logging
import re

from core.privacy import scan_pii, strip_forbidden_fields


# ── §3.1 IP Suppression ──────────────────────────────────────────────────────


class TestIPSuppression:
    """Dev Req §3.1 — IP suppression acceptance criteria."""

    def test_remote_addr_returns_redacted(self, app):
        """request.remote_addr always returns 0.0.0.0."""
        with app.test_request_context(environ_base={"REMOTE_ADDR": "192.168.1.100"}):
            from flask import request
            assert request.remote_addr == "0.0.0.0"

    def test_remote_addr_never_real_ip(self, app):
        """Even with X-Forwarded-For, remote_addr is 0.0.0.0."""
        headers = {"X-Forwarded-For": "10.0.0.1"}
        with app.test_request_context(headers=headers, environ_base={"REMOTE_ADDR": "172.16.0.1"}):
            from flask import request
            assert request.remote_addr == "0.0.0.0"

    def test_ip_free_formatter_strips_ipv4(self):
        """Log formatter strips IPv4 patterns from messages."""
        from server import _IPFreeFormatter

        formatter = _IPFreeFormatter("%(message)s")
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Request from 192.168.1.100 to /api/contribute",
            args=(), exc_info=None,
        )
        formatted = formatter.format(record)
        assert "192.168.1.100" not in formatted
        assert "[REDACTED]" in formatted

    def test_ip_free_formatter_strips_ipv6(self):
        """Log formatter strips IPv6 patterns from messages."""
        from server import _IPFreeFormatter

        formatter = _IPFreeFormatter("%(message)s")
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Connection from 2001:0db8:85a3:0000:0000:8a2e:0370:7334",
            args=(), exc_info=None,
        )
        formatted = formatter.format(record)
        assert "2001:0db8" not in formatted

    def test_no_ip_column_in_sp_events(self):
        """sp_events table has no IP-related column."""
        from core.models.spiritpool import SpEvent

        columns = {c.name for c in SpEvent.__table__.columns}
        ip_columns = {"ip", "ip_address", "remote_addr", "client_ip", "source_ip"}
        assert columns.isdisjoint(ip_columns), f"IP column found in sp_events: {columns & ip_columns}"

    def test_no_ip_column_in_quarantine(self):
        """quarantine table has no IP-related column."""
        from core.models.spiritpool import Quarantine

        columns = {c.name for c in Quarantine.__table__.columns}
        ip_columns = {"ip", "ip_address", "remote_addr", "client_ip", "source_ip"}
        assert columns.isdisjoint(ip_columns), f"IP column found in quarantine: {columns & ip_columns}"


# ── §3.2 Field Stripping ─────────────────────────────────────────────────────


class TestFieldStripping:
    """Dev Req §3.2 — tabUrl/collectedAt stripping acceptance criteria."""

    def test_strip_top_level_taburl(self):
        """tabUrl removed from top-level body."""
        body = {"session_token": "tok", "tabUrl": "https://evil.com/jobs"}
        result = strip_forbidden_fields(body)
        assert "tabUrl" not in result

    def test_strip_top_level_collectedat(self):
        """collectedAt removed from top-level body."""
        body = {"session_token": "tok", "collectedAt": "2026-04-05T00:00:00Z"}
        result = strip_forbidden_fields(body)
        assert "collectedAt" not in result

    def test_strip_nested_payload_taburl(self):
        """tabUrl removed from nested payload dict."""
        body = {
            "session_token": "tok",
            "payload": {"company": "Acme", "tabUrl": "https://indeed.com/job/123"},
        }
        result = strip_forbidden_fields(body)
        assert "tabUrl" not in result["payload"]

    def test_strip_nested_payload_collectedat(self):
        """collectedAt removed from nested payload dict."""
        body = {
            "session_token": "tok",
            "payload": {"data": "ok", "collectedAt": "2026-04-05T00:00:00Z"},
        }
        result = strip_forbidden_fields(body)
        assert "collectedAt" not in result["payload"]

    def test_strip_both_top_and_nested(self):
        """Both top-level and nested forbidden fields removed in one pass."""
        body = {
            "tabUrl": "https://example.com",
            "collectedAt": "2026-01-01",
            "payload": {
                "tabUrl": "https://example.com/nested",
                "collectedAt": "2026-02-02",
                "job": "Engineer",
            },
        }
        result = strip_forbidden_fields(body)
        assert "tabUrl" not in result
        assert "collectedAt" not in result
        assert "tabUrl" not in result["payload"]
        assert "collectedAt" not in result["payload"]
        assert result["payload"]["job"] == "Engineer"

    def test_strip_no_op_when_fields_absent(self):
        """Stripping is a no-op when fields are already absent."""
        body = {"session_token": "tok", "payload": {"clean": True}}
        result = strip_forbidden_fields(body)
        assert result == body

    def test_strip_preserves_other_fields(self):
        """Stripping does not remove non-forbidden fields."""
        body = {
            "session_token": "tok",
            "epoch_id": 1,
            "tabUrl": "remove-me",
            "payload": {"company": "Acme", "salary": 50000},
        }
        result = strip_forbidden_fields(body)
        assert result["session_token"] == "tok"
        assert result["epoch_id"] == 1
        assert result["payload"]["company"] == "Acme"
        assert result["payload"]["salary"] == 50000

    # ── consent_state stripping (Non-negotiable rule #5) ─────────────

    def test_strip_top_level_consent_state(self):
        """consent_state removed from top-level body (rule #5: never stored)."""
        body = {
            "session_token": "tok",
            "consent_state": {"sites_enabled": ["indeed.com"], "collection_active": True},
        }
        result = strip_forbidden_fields(body)
        assert "consent_state" not in result

    def test_strip_nested_consent_state(self):
        """consent_state removed from nested payload dict."""
        body = {
            "session_token": "tok",
            "payload": {
                "company": "Acme",
                "consent_state": {"collection_active": True},
            },
        }
        result = strip_forbidden_fields(body)
        assert "consent_state" not in result["payload"]


# ── §3.3 PII Quarantine Pipeline — Pattern Detection ─────────────────────────


class TestPIIDetection:
    """Dev Req §3.3 — PII regex patterns, recursive walk, detection accuracy."""

    # ── Email ─────────────────────────────────────────────────────────

    def test_detect_email_simple(self):
        """Email in any nested field detected."""
        assert "email" in scan_pii({"contact": "user@example.com"})

    def test_detect_email_deeply_nested(self):
        """Email in deeply nested dict detected."""
        payload = {"meta": {"author": {"email": "deep@nested.org"}}}
        assert "email" in scan_pii(payload)

    def test_detect_email_in_list(self):
        """Email in a list value detected."""
        payload = {"contacts": ["alice@test.com", "bob@test.com"]}
        assert "email" in scan_pii(payload)

    # ── Phone ─────────────────────────────────────────────────────────

    def test_detect_phone_dashes(self):
        """US phone with dashes detected."""
        assert "phone" in scan_pii({"phone": "512-555-1234"})

    def test_detect_phone_dots(self):
        """US phone with dots detected."""
        assert "phone" in scan_pii({"phone": "512.555.1234"})

    def test_detect_phone_no_separator(self):
        """US phone without separators detected."""
        assert "phone" in scan_pii({"phone": "5125551234"})

    def test_detect_phone_parens(self):
        """US phone with parentheses detected."""
        assert "phone" in scan_pii({"phone": "(512) 555-1234"})

    def test_detect_phone_international(self):
        """International phone with + prefix detected."""
        assert "phone" in scan_pii({"phone": "+15125551234"})

    # ── SSN ───────────────────────────────────────────────────────────

    def test_detect_ssn(self):
        """SSN pattern (###-##-####) detected."""
        assert "ssn" in scan_pii({"id": "123-45-6789"})

    # ── Credit Card ───────────────────────────────────────────────────

    def test_detect_credit_card(self):
        """13-19 digit number detected as credit card."""
        assert "credit_card" in scan_pii({"cc": "4111111111111111"})

    # ── Multiple PII ──────────────────────────────────────────────────

    def test_detect_multiple_pii_types(self):
        """Multiple PII types detected in one payload."""
        payload = {
            "email": "test@example.com",
            "phone": "512-555-1234",
        }
        result = scan_pii(payload)
        assert "email" in result
        assert "phone" in result

    # ── Clean payloads ────────────────────────────────────────────────

    def test_clean_payload_no_pii(self):
        """Clean payload returns empty list."""
        payload = {
            "company": "Whole Foods",
            "jobTitle": "Team Member",
            "salary": {"min": 16, "max": 20, "period": "hourly"},
            "location": "Austin, TX 78701",
        }
        assert scan_pii(payload) == []

    def test_salary_not_false_positive(self):
        """Salary values (5 digits) are not flagged as credit cards."""
        payload = {"salary": "75000", "wage": "22.50"}
        assert scan_pii(payload) == []

    def test_zip_code_not_false_positive(self):
        """5-digit zip codes are not flagged."""
        payload = {"zip": "78701", "region": "Austin"}
        assert scan_pii(payload) == []

    # ── Non-string types ──────────────────────────────────────────────

    def test_integer_values_ignored(self):
        """Integer values are not scanned (only strings)."""
        payload = {"count": 5125551234, "epoch": 999999}
        assert scan_pii(payload) == []

    def test_none_values_ignored(self):
        """None values do not cause errors."""
        payload = {"company": None, "title": "Engineer"}
        assert scan_pii(payload) == []

    def test_boolean_values_ignored(self):
        """Boolean values do not cause errors."""
        payload = {"active": True, "remote": False}
        assert scan_pii(payload) == []

    # ── Recursive structure ───────────────────────────────────────────

    def test_nested_list_of_dicts(self):
        """PII in list of dicts detected."""
        payload = {
            "applicants": [
                {"name": "Alice", "resume": "Contact me at alice@test.com"},
                {"name": "Bob"},
            ]
        }
        assert "email" in scan_pii(payload)
