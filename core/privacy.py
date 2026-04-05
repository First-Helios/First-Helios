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
_FORBIDDEN_FIELDS = {"tabUrl", "collectedAt"}


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
_PII_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("email", re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")),
    ("phone", re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b")),
    ("phone", re.compile(r"\(\d{3}\)\s?\d{3}[-.]?\d{4}")),
    ("phone", re.compile(r"\+\d{7,15}")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("credit_card", re.compile(r"\b\d{13,19}\b")),
]

# Common false positive patterns for credit card regex (salary numbers, zip codes, etc.)
# Salary values like "75000" are 5 digits — below the 13-digit threshold, so safe.
# Phone-like strings that are actually IDs are handled by the word-boundary anchors.


def scan_pii(payload: Any) -> list[str]:
    """Recursively scan all string values in a JSONB payload for PII patterns.

    Returns a deduplicated sorted list of matched pattern types
    (e.g. ["email", "phone"]) or an empty list if clean.

    Walks dicts and lists recursively. Only tests string values.
    """
    matched: set[str] = set()
    _scan_value(payload, matched)
    return sorted(matched)


def _scan_value(value: Any, matched: set[str]) -> None:
    """Recursive worker — scan a single value node."""
    if isinstance(value, str):
        for pii_type, pattern in _PII_PATTERNS:
            if pattern.search(value):
                matched.add(pii_type)
    elif isinstance(value, dict):
        for v in value.values():
            _scan_value(v, matched)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _scan_value(item, matched)
    # int, float, bool, None — skip silently
