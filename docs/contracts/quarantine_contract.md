# Data Contract: quarantine

> **Table:** `quarantine`
> **Layer:** Metadata
> **Owner:** Data Engineering
> **Created:** 2026-04-05
> **Status:** Active (FH-1)

---

## Purpose

PII-flagged payloads held for internal audit only. Events matching any PII regex pattern (email, phone, SSN, credit card) are stored here instead of `sp_events`. Never exposed to external APIs, dashboards, or scoring.

## Consumers

| Consumer | Usage | Dependency Level |
|----------|-------|-----------------|
| Internal audit | Re-evaluate quarantined payloads when PII rules improve | Hard |
| System health dashboard | Quarantine rate metric (quarantined / total events) | Soft |
| Transparency metrics | PII detection hit rate visible to contributors | Soft |

## Schema Contract

| Column | Type | Nullable | Constraint |
|--------|------|----------|------------|
| quarantine_id | VARCHAR (UUID) | No | PK, server-generated |
| original_payload | JSONB | No | Complete original event body |
| redaction_types | TEXT | No | JSON array of pattern types |
| rule_version | INTEGER | No | Matches pipeline_version logic |
| quarantined_at | DATETIME | No | Server-set |

## Access Restrictions

- **NEVER queryable** by external APIs, public endpoints, or dashboards
- Internal audit access only
- No export mechanism without explicit authorization
- Records are immutable — no updates, only appends

## Accuracy Source

- PII detection engine using regex patterns (FH-1 §3)
- `redaction_types` accurately lists ALL patterns that triggered quarantine
- `rule_version` enables re-processing: if regex improves, old quarantined events can be re-evaluated

## Freshness SLA

- No freshness requirement — this table grows only when PII is detected
- Growth rate monitored as a health metric

## Alerting Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| Quarantine rate (% of total events) | > 5% | > 15% |
| Table growth rate (week-over-week) | > 50% increase | > 200% increase |

## Re-Processing Rules

1. When PII regex patterns are updated (new `rule_version`), old quarantined events MAY be re-evaluated
2. Events that no longer match updated patterns can be moved to `sp_events` with the new `pipeline_version`
3. Re-processing must be logged as a `MetaJobRun` entry
4. Re-processing is a manual operation — never automated

## What Can Break

| Scenario | Impact | Mitigation |
|----------|--------|------------|
| False positive PII detection | Legitimate events quarantined | Monitor quarantine rate; tune regex |
| False negative PII detection | PII stored in sp_events | Periodic audit; upgrade to NER in Second Helios |
| Quarantine table grows too large | Storage pressure | Review and prune after re-evaluation |

## Privacy Constraints

- Quarantined payloads contain PII by definition — handle with highest security
- No export to external systems
- Subject to same IP suppression, field stripping rules as all other data
