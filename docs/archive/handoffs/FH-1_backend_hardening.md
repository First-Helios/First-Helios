> **ARCHIVED 2026-04-21.** Phase complete and audited in [../../SECURITY_FINDINGS.md](../../SECURITY_FINDINGS.md). Canonical replacement: [../../architecture/HeliosDeployment/04_PRIVACY_AND_GOVERNANCE.md](../../architecture/HeliosDeployment/04_PRIVACY_AND_GOVERNANCE.md).

# FH-1: Backend Hardening / M6

> **Trigger:** SpiritPool Phase 2 complete (security controls active on extension side)
> **Prerequisite:** FH-0 complete (intake endpoint + schema live). Read `SPIRITPOOL_CONTEXT.md` for full context.
> **Target repo:** `/home/fortune/CodeProjects/First-Helios/`
> **This is a security gate — nothing ships to users until FH-1 passes.**

---

## Objective

Enforce all privacy controls at the server boundary before any external access or production deployment. This document specifies the three hardening layers and the integration test suite that must pass before launch.

---

## 1. IP Suppression (Critical — Priority 1)

### Requirements
- Middleware must strip client IP from the request context **before** any handler runs
- Override framework logging to exclude IP addresses completely
- Access logs, request logs, error logs — all must be IP-free
- If the framework logs IP by default, override it

### Verification
```bash
# Must return zero matches — any match is a security incident
grep -rP '\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}' logs/ database/
# Also check IPv6 patterns
grep -rP '[0-9a-fA-F]{1,4}(:[0-9a-fA-F]{1,4}){7}' logs/ database/
```

### Rule
Any IP-like pattern found in logs or database = **critical bug and security incident**. Fix immediately, audit all historical data.

---

## 2. Field Stripping (Defence-in-Depth)

### Requirements
- Delete `tabUrl` and `collectedAt` from all payloads **before any processing**, regardless of whether the extension already stripped them
- These fields are never logged, never stored, never passed to any downstream function
- If an `Observation.page_url` column exists from legacy schema, **stop populating it** (do not drop column yet — drop in a future migration after confirming no dependency)

### Implementation
Strip in the intake handler immediately after JSON parsing, before validation or storage:

```
# Pseudocode — adapt to your framework
payload.pop('tabUrl', None)
payload.pop('collectedAt', None)
if 'payload' in body and isinstance(body['payload'], dict):
    body['payload'].pop('tabUrl', None)
    body['payload'].pop('collectedAt', None)
```

---

## 3. PII Quarantine Pipeline

### Requirements
Pre-write regex gate scanning **all text fields** in `payload` JSONB for PII patterns. Events matching any pattern go to `quarantine` table — not silently dropped, not error-rejected.

### PII Patterns to Detect

| Pattern | Regex | Example Matches |
|---|---|---|
| Email | `[^@\s]+@[^@\s]+\.[^@\s]+` | `test@example.com` |
| US phone | `\b\d{3}[-.]?\d{3}[-.]?\d{4}\b` | `512-555-1234`, `5125551234` |
| US phone (parens) | `\(\d{3}\)\s?\d{3}[-.]?\d{4}` | `(512) 555-1234` |
| International phone | `\+\d{7,15}` | `+15125551234` |
| US SSN | `\b\d{3}-\d{2}-\d{4}\b` | `123-45-6789` |
| Credit card | `\b\d{13,19}\b` | 13–19 consecutive digits |

### Processing Logic
1. Parse `payload` JSONB recursively — check all string values at every nesting level
2. Test each string against all PII patterns
3. If **any** match:
   - Insert into `quarantine` table (see §3.1)
   - Do NOT insert into `events` table
   - Return 200 to the extension (contributor's session continues unaffected)
4. If no match:
   - Insert into `events` table normally

### 3.1 Quarantine Table Schema

```sql
CREATE TABLE quarantine (
  quarantine_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  original_payload JSONB NOT NULL,
  redaction_types  TEXT[] NOT NULL,          -- e.g. ['email'], ['phone', 'ssn']
  rule_version     INTEGER NOT NULL,         -- matches pipeline_version logic
  quarantined_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### Rules
- Quarantined events are **never queryable** by external APIs or dashboards
- Quarantine is for internal audit only
- `redaction_types` array records which patterns triggered the quarantine
- `rule_version` enables re-processing: if regex improves, old quarantined events can be re-evaluated

---

## 4. Integration Test Suite (§8.1–8.5)

All five tests must pass before production deployment.

### §8.1 End-to-End Signal Flow Test

**Input:** Raw signal with:
- `salary: 75000`
- `observedAt: <exact timestamp>`
- `tabUrl: "https://example.com/browsing?session=abc123"`
- `collectedAt: "2026-04-01T12:00:00Z"`

**Expected at backend after intake:**
- [ ] Event stored in `events` table
- [ ] No `tabUrl` anywhere in the record
- [ ] No `collectedAt` — server sets its own `collected_at` timestamp
- [ ] No IP address in any log file
- [ ] `session_token` and `epoch_id` match what the extension sent
- [ ] `pipeline_version = 1`

### §8.2 PII Defence-in-Depth Test

**Input:** Signal with payload containing `test@example.com`

**Expected:**
- [ ] Backend PII engine catches the email pattern
- [ ] Event goes to `quarantine` table, NOT `events` table
- [ ] Quarantine record includes `redaction_types: ['email']`
- [ ] Extension receives 200 (session not disrupted)

**Variant tests:**
- Phone number in payload → quarantine with `['phone']`
- SSN pattern → quarantine with `['ssn']`
- Multiple PII types → quarantine with all matching types

### §8.3 Config Signing Validation
- Extension-only test. Backend validates it doesn't crash on signals from extension using fallback selectors.
- No backend action required beyond accepting valid signals normally.

### §8.4 Token Rotation Test

**Input:** Simulate a token rotation — first POST with token A, then POST with token B and incremented epoch_id.

**Expected:**
- [ ] Both events stored with their respective tokens
- [ ] `session_epochs` has rows for both tokens
- [ ] Old token (A) is not referenced in any log after token B begins

### §8.5 Forward-Compatibility Test

**Input:**
1. `session_token` = 64-character hex string (simulating Second Helios)
2. `epoch_id` = large integer (e.g. 999999)
3. Unknown fields in `payload` JSONB (simulating Third Helios EDN fields)

**Expected:**
- [ ] All stored successfully — no validation error
- [ ] 64-char hex token stored in TEXT column without truncation
- [ ] Large epoch_id stored without overflow
- [ ] Unknown JSONB fields preserved exactly

**Rule:** If any of these fail → forward-compatibility bug. Must be fixed before ship.

---

## 5. Success Criteria Summary

- [ ] Zero IP patterns in any log or DB row (`grep` test passes)
- [ ] `tabUrl` and `collectedAt` stripped even if present in POST body
- [ ] PII regex catches email/phone/SSN/CC → quarantine with `redaction_types`
- [ ] Clean events flow to `events` unaffected
- [ ] Forward-compat tests pass (§8.5)
- [ ] Full integration test suite §8.1–8.5 green
- [ ] Extension receives 200 for both clean and quarantined events

---

## 6. What Comes After FH-1

Once FH-1 passes:
- Production deployment of the intake pipeline is cleared
- SpiritPool can be submitted to Chrome Web Store / Firefox Add-ons
- **FH-2** handoff documents arrive per new content script with dedup keys and payload shapes
- Second Helios upgrades (NER pipeline, cert-gated writes) build on top of this foundation
