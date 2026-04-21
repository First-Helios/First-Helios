# 4. Privacy & Governance

> **Audience:** Anyone working on this codebase. These rules are absolute.
>
> **Source of truth:** `agentMailbox/SPIRITPOOL_CONTEXT.md` (privacy contract), `agentMailbox/FH-1_backend_hardening.md` (implementation spec)

---

## Foundational Commitments

First Helios earns contributor trust through three commitments. These are not aspirational — they are structural and enforced in code.

1. **Secure data & profiles** — PII is quarantined, not stored. IPs are never logged. Session tokens are opaque.
2. **Transparent systems** — Every table documented. Every flow traceable. Health metrics visible.
3. **Broad collection under trust** — Collect widely, govern responsibly, show your work.

---

## The 18 Non-Negotiable Rules

Violations are treated as **production incidents**. Not warnings — incidents.

### Privacy Rules (1–6)

| # | Rule | Implementation |
|---|------|---------------|
| 1 | **Never store `tabUrl`** | `strip_forbidden_fields()` in `core/privacy.py` removes it before any processing |
| 2 | **Never store `collectedAt` from clients** | Same function strips it; server sets its own `collected_at` via `datetime.utcnow()` |
| 3 | **Never log or store IP addresses** | `_IPSuppressedRequest` in `server.py` overrides `remote_addr` → `"0.0.0.0"`; `_IPFreeFormatter` strips IPs from log output |
| 4 | **Never create a mechanism to recover identity from `session_token`** | Token is treated as opaque TEXT. No parsing, no lookup tables, no reverse mapping. |
| 5 | **`consent_state` is never transmitted or stored** | No consent column exists anywhere. Consent is managed exclusively client-side. |
| 6 | **PII goes to quarantine, never to production tables** | `scan_pii()` in `core/privacy.py` runs before storage; matched events route to `quarantine` table |

### Schema Rules (7–10)

| # | Rule | Implementation |
|---|------|---------------|
| 7 | **`session_token` is TEXT with no length/format constraints** | Column type is `Text` in ORM. Accepts 36-char UUID and 64-char hex. |
| 8 | **`payload` JSONB must accept unknown fields** | PostgreSQL JSONB stores arbitrary keys. No server-side schema validation on payload contents. |
| 9 | **`pipeline_version` is set server-side only** | Hardcoded in endpoint as `_CURRENT_PIPELINE_VERSION = 1`. Never accepted from client body. |
| 10 | **`epoch_id` has no upper bound** | Column type is `Integer`. No CHECK constraint. |

### Data Quality Rules (11–15)

| # | Rule | Implementation |
|---|------|---------------|
| 11 | **Every new table registered in `meta_table_catalog` before data is written** | `scripts/one_shot/populate_metadata.py` registers all tables. Run before any ingest. |
| 12 | **Every external API source registered in `api_sources`** | `core/rate_manager.py` manages registration. |
| 13 | **Every ingest job logs a `MetaJobRun`** | All collector runners create MetaJobRun entries on start/completion. |
| 14 | **Dedup keys documented** | See [Data Architecture § Deduplication Keys](02_DATA_ARCHITECTURE.md#deduplication-keys). |
| 15 | **Data contracts for dashboard-facing tables** | Four contracts exist in `docs/contracts/`. |

### Naming Rules (16–18)

| # | Rule | Example |
|---|------|---------|
| 16 | **Table names: `[layer]_[source]_[entity]`** for new tables | `sp_events`, `burn_pool`. Legacy tables keep existing names. |
| 17 | **Column names: snake_case** | `session_token`, `epoch_id`. Allowed abbreviations: lat, lng, h3, soc, naics. |
| 18 | **Index names: `idx_[table]_[columns]`** | `idx_sp_events_session_epoch`, `idx_sp_events_type_collected` |

---

## IP Suppression (Rule #3) — How It Works

Implemented in `server.py`, active for every request on the Flask app.

### Layer 1: Request Override
```python
class _IPSuppressedRequest(Flask.request_class):
    @property
    def remote_addr(self):
        return "0.0.0.0"
```
Every handler that reads `request.remote_addr` gets `"0.0.0.0"`. This is structural — there is no code path where the real IP is available inside the application.

### Layer 2: Log Sanitization
```python
class _IPFreeFormatter(logging.Formatter):
    _IP_RE = re.compile(
        r'\b(?:\d{1,3}\.){3}\d{1,3}\b'     # IPv4
        r'|'
        r'\b(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{1,4}\b'  # IPv6
    )
    def format(self, record):
        msg = super().format(record)
        return self._IP_RE.sub("0.0.0.0", msg)
```
Applied to both the werkzeug logger and any additional handler. Even if an IP leaked into a log message through an exception traceback, it would be stripped.

---

## Field Stripping (Rules #1, #2) — How It Works

Implemented in `core/privacy.py:strip_forbidden_fields()`.

Called **immediately** after JSON parsing in the `/api/contribute` endpoint, before validation or any other processing.

```python
_FORBIDDEN_FIELDS = {"tabUrl", "collectedAt"}

def strip_forbidden_fields(body: dict) -> dict:
    for field in _FORBIDDEN_FIELDS:
        body.pop(field, None)
    payload = body.get("payload")
    if isinstance(payload, dict):
        for field in _FORBIDDEN_FIELDS:
            payload.pop(field, None)
    return body
```

Strips from both top-level body and nested `payload` dict. No-op if fields are already absent.

---

## PII Detection (Rule #6) — How It Works

Implemented in `core/privacy.py:scan_pii()`.

### Patterns (6 compiled regexes at import time)

| Type | Pattern | Example Match |
|------|---------|--------------|
| `email` | `[^@\s]+@[^@\s]+\.[^@\s]+` | `user@example.com` |
| `phone` | `\b\d{3}[-.]?\d{3}[-.]?\d{4}\b` | `512-555-1234` |
| `phone` | `\(\d{3}\)\s?\d{3}[-.]?\d{4}` | `(512) 555-1234` |
| `phone` | `\+\d{7,15}` | `+15125551234` |
| `ssn` | `\b\d{3}-\d{2}-\d{4}\b` | `123-45-6789` |
| `credit_card` | `\b\d{13,19}\b` | `4111111111111111` |

### Behavior
- Recursively walks all dict values and list items in the JSONB `payload`
- Only tests string values
- Returns sorted deduplicated list: `["email", "phone"]` or `[]`
- Salary values (5 digits) are below the 13-digit credit card threshold — no false positives

### Routing Decision
```
if scan_pii(payload):
    → quarantine table (original_payload + redaction_types + rule_version)
else:
    → sp_events table
```

Events in quarantine are **never** queryable by external APIs or dashboards.

---

## Burn Mechanism (Session Anonymization)

Contributors can sever the link between their session token and their contributor identity at any time via `POST /api/burn`.

**What happens:**
1. `session_epochs.contributor_id` → `NULL`
2. `session_epochs.burned_at` → `NOW()`
3. `burn_pool` entry created/incremented for the current month
4. `burn_pool.expires_at` set to `burned_at + 1 year`
5. Daily cleanup job deletes expired `burn_pool` records

**What you cannot do after a burn:**
- Recover which contributor was associated with the token
- Undo the burn
- Trace the token back to a person

The signals in `sp_events` remain (they're useful data), but the identity link is permanently severed.

---

## Data Governance Checklist

Before any code change that touches data, verify:

- [ ] No IP address stored, logged, or accessible via any code path
- [ ] No `tabUrl` or `collectedAt` in any stored payload
- [ ] No `consent_state` column or field anywhere
- [ ] All new tables registered in `meta_table_catalog`
- [ ] All columns documented in `meta_column_catalog`
- [ ] Data lineage registered in `meta_data_lineage`
- [ ] PII scan runs before any data reaches production tables
- [ ] Ingest jobs log `MetaJobRun` entries
- [ ] Data contracts exist for dashboard-facing tables
- [ ] Dedup keys documented and enforced

---

## Security Findings Log

Known issues and resolutions are tracked in [SECURITY_FINDINGS.md](../../SECURITY_FINDINGS.md) at the project root.

---

## Related Files

| File | What It Does |
|------|-------------|
| `server.py` | `_IPSuppressedRequest`, `_IPFreeFormatter` — IP suppression |
| `core/privacy.py` | `strip_forbidden_fields()`, `scan_pii()` — field stripping + PII detection |
| `core/contribute_routes.py` | Endpoint that enforces the full processing pipeline |
| `core/models/spiritpool.py` | `Quarantine` model — PII-flagged payload storage |
| `agentMailbox/SPIRITPOOL_CONTEXT.md` | Original privacy contract |
| `agentMailbox/FH-1_backend_hardening.md` | Implementation spec for all privacy controls |
