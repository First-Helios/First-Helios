"""
core/privacy.py — Defence-in-depth privacy controls for contributor data.

Contains:
    strip_forbidden_fields() — Remove tabUrl, collectedAt from payloads
    scan_pii()               — Recursive PII regex scan on JSONB payloads

Both are stateless pure functions, testable in isolation.

FH-1 §2 (Field Stripping) and §3 (PII Quarantine Pipeline).

Depends on: re (stdlib)
Called by: POST /api/contribute intake endpoint
"""

import re
from typing import Any


# ── Field Stripping (FH-1 §2) ───────────────────────────────────────────────

# Fields that must NEVER be stored, logged, or passed downstream.
# tabUrl / collectedAt — FH-1 §2 (field stripping)
# consent_state        — Non-negotiable rule #5: never transmitted or stored
_FORBIDDEN_FIELDS = {"tabUrl", "collectedAt", "consent_state"}


def strip_forbidden_fields(body: dict) -> dict:
    """Remove tabUrl and collectedAt from top-level body and nested payload.

    Mutates and returns the same dict. Safe to call even if the extension
    already stripped these — a no-op in that case.

    Must be called IMMEDIATELY after JSON parsing, before validation or storage.
    """
    for field in _FORBIDDEN_FIELDS:
        body.pop(field, None)

    payload = body.get("payload")
    if isinstance(payload, dict):
        for field in _FORBIDDEN_FIELDS:
            payload.pop(field, None)

    return body


# ── PII Detection Engine (FH-1 §3) ──────────────────────────────────────────

# Patterns from FH-1 §3 — all are compiled once at import time.
# These are intentionally broad (sensitive) to catch any real PII.
# False positives from numeric IDs, URLs, and categorical fields are
# suppressed via _PII_EXEMPT_FIELDS rather than weakening the patterns.
_PII_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("email", re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")),
    ("phone", re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b")),
    ("phone", re.compile(r"\(\d{3}\)\s?\d{3}[-.]?\d{4}")),
    ("phone", re.compile(r"\+\d{7,15}")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("credit_card", re.compile(r"\b\d{13,19}\b")),
]

# Fields whose values structurally cannot contain PII.  Exempting them from
# the recursive scan prevents false positives from numeric job IDs in URLs,
# opaque session tokens, and categorical/enum values.  Add new fields here
# as the extension schema grows — only fields that carry free-text user
# content (company, description, location) should remain scanned.
_PII_EXEMPT_FIELDS: set[str] = {
    # ── URLs & IDs — numeric job IDs trigger phone/credit-card regex ──
    "url",
    "job_url",
    "source_url",
    # ── Session / contributor plumbing ────────────────────────────────
    "session_token",
    "epoch_id",
    "legacy_contributor_id",
    "legacy_domain",
    # ── Categorical / enum-like (no free text) ───────────────────────
    "postingDate",
    "jobType",
    "isRemote",
    "salarySource",
    "jobLevel",
    "companyIndustry",
    "badges",
    "applicantCount",
    "rating",
    # ── Structured numeric (salary dict) ─────────────────────────────
    "salary",
}


def scan_pii(payload: Any) -> list[str]:
    """Recursively scan all string values in a JSONB payload for PII patterns.

    Returns a deduplicated sorted list of matched pattern types
    (e.g. ["email", "phone"]) or an empty list if clean.

    Walks dicts and lists recursively.  Dict keys in _PII_EXEMPT_FIELDS
    have their entire subtree skipped.  Only tests string values.
    """
    matched: set[str] = set()
    _scan_value(payload, matched)
    return sorted(matched)


def _scan_value(value: Any, matched: set[str], field_name: str | None = None) -> None:
    """Recursive worker — scan a single value node.

    When *field_name* is set and appears in _PII_EXEMPT_FIELDS the entire
    subtree is skipped (the value cannot structurally contain PII).
    """
    if field_name and field_name in _PII_EXEMPT_FIELDS:
        return
    if isinstance(value, str):
        for pii_type, pattern in _PII_PATTERNS:
            if pattern.search(value):
                matched.add(pii_type)
    elif isinstance(value, dict):
        for k, v in value.items():
            _scan_value(v, matched, field_name=k)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _scan_value(item, matched, field_name=field_name)
    # int, float, bool, None — skip silently
