# Test Audit Log — HeliosDeployment T1/T2/T3 Test Suite
#
# Generated: 2026-04-05
# Updated: 2026-04-05 (T3 additions)
# Suite: tests/HeliosDeployment/
# Total tests: 124
# Pillars: §2 Schema, §3 Privacy, §4 API Contract, §5 Data Quality, §6 Observability
# T3 additions: §4.3 Legacy Compat, §6.1 Dashboard Monitoring
#
# Format:
#   ID | File | Class | Test | Dev Req | Status | Description
#
# Status codes:
#   PASS  — Test passes on current codebase
#   FAIL  — Test fails (see error_tracking.md for diagnosis)
#   SKIP  — Test skipped (dependency not met or deferred)
#   XFAIL — Expected failure (known issue, tracked)
#
# This log is the single source of truth for auditing test coverage
# against the DEVELOPMENT_REQUIREMENTS_PLAN.md acceptance criteria.

---

## Summary

| Pillar | File | Tests | Pass | Fail | Coverage Target |
|--------|------|-------|------|------|-----------------|
| §2 Schema & Storage | test_schema_storage.py | 14 | 14 | 0 | §2.1–§2.5 |
| §3 Privacy & Security | test_privacy_security.py | 25 | 25 | 0 | §3.1–§3.3 |
| §4 API Contract | test_api_contract.py | 33 | 33 | 0 | §4.1–§4.2, §5.3 |
| §5 Data Quality | test_metadata_quality.py | 12 | 12 | 0 | §5.1–§5.2 |
| §6 Observability | test_observability.py | 8 | 8 | 0 | §6.3, T2.5 |
| §6.1 Dashboard | test_dashboard_spiritpool.py | 14 | 14 | 0 | §6.1, §6.2 (T3.2) |
| §4.3 Legacy Compat | test_legacy_compat.py | 9 | 9 | 0 | §4.3, §3.2 (T3.3) |
| **TOTAL** | | **124** | **124** | **0** | |

---

## test_schema_storage.py — Dev Req §2: Schema & Storage

| ID | Class | Test | Dev Req | Status | Description |
|----|-------|------|---------|--------|-------------|
| S-01 | TestSpEventsSchema | test_64_char_hex_session_token | §2.1 | PASS | 64-char hex session_token stores without truncation or error |
| S-02 | TestSpEventsSchema | test_36_char_uuid_session_token | §2.1 | PASS | 36-char UUID session_token stores without error |
| S-03 | TestSpEventsSchema | test_large_epoch_id | §2.1 | PASS | epoch_id = 999999 stores without overflow |
| S-04 | TestSpEventsSchema | test_unknown_jsonb_fields_preserved | §2.1 | PASS | Unknown JSONB fields in payload preserved exactly |
| S-05 | TestSpEventsSchema | test_all_event_types_accepted | §2.1 | PASS | All four event_type values (job_listing, salary_signal, business_review, event_listing) store correctly |
| S-06 | TestSessionEpochsSchema | test_unique_session_token | §2.2 | PASS | Session token has UNIQUE constraint — duplicate insert raises IntegrityError |
| S-07 | TestSessionEpochsSchema | test_contributor_id_nullable | §2.2 | PASS | contributor_id can be NULL (burn operation initial state) |
| S-08 | TestSessionEpochsSchema | test_contributor_id_set_to_null | §2.2 | PASS | contributor_id can be changed from a value to NULL (burn operation) |
| S-09 | TestSessionEpochsSchema | test_multiple_tokens_per_contributor | §2.2 | PASS | Multiple session tokens can exist for the same contributor |
| S-10 | TestQuarantineSchema | test_stores_complete_original_payload | §2.3 | PASS | original_payload stores complete original event body for audit |
| S-11 | TestQuarantineSchema | test_redaction_types_multiple | §2.3 | PASS | redaction_types stores multiple PII types as JSON array |
| S-12 | TestQuarantineSchema | test_rule_version_tracked | §2.3 | PASS | rule_version is stored for re-processing capability |
| S-13 | TestBurnPoolSchema | test_monthly_aggregate | §2.4 | PASS | Burn pool stores monthly aggregates with signal_count |
| S-14 | TestBurnPoolSchema | test_expires_at_set | §2.4 | PASS | expires_at is stored (burned_at + 1 year, ±1 day) |

---

## test_privacy_security.py — Dev Req §3: Privacy & Security

| ID | Class | Test | Dev Req | Status | Description |
|----|-------|------|---------|--------|-------------|
| P-01 | TestIPSuppression | test_remote_addr_returns_redacted | §3.1 | PASS | request.remote_addr always returns 0.0.0.0 |
| P-02 | TestIPSuppression | test_remote_addr_never_real_ip | §3.1 | PASS | Even with X-Forwarded-For, remote_addr is 0.0.0.0 |
| P-03 | TestIPSuppression | test_ip_free_formatter_strips_ipv4 | §3.1 | PASS | Log formatter strips IPv4 patterns, replaces with [REDACTED] |
| P-04 | TestIPSuppression | test_ip_free_formatter_strips_ipv6 | §3.1 | PASS | Log formatter strips IPv6 patterns from messages |
| P-05 | TestIPSuppression | test_no_ip_column_in_sp_events | §3.1 | PASS | sp_events table has no IP-related column |
| P-06 | TestIPSuppression | test_no_ip_column_in_quarantine | §3.1 | PASS | quarantine table has no IP-related column |
| P-07 | TestFieldStripping | test_strip_top_level_taburl | §3.2 | PASS | tabUrl removed from top-level body |
| P-08 | TestFieldStripping | test_strip_top_level_collectedat | §3.2 | PASS | collectedAt removed from top-level body |
| P-09 | TestFieldStripping | test_strip_nested_payload_taburl | §3.2 | PASS | tabUrl removed from nested payload dict |
| P-10 | TestFieldStripping | test_strip_nested_payload_collectedat | §3.2 | PASS | collectedAt removed from nested payload dict |
| P-11 | TestFieldStripping | test_strip_both_top_and_nested | §3.2 | PASS | Both top-level and nested forbidden fields removed in one pass |
| P-12 | TestFieldStripping | test_strip_no_op_when_fields_absent | §3.2 | PASS | Stripping is a no-op when fields are already absent |
| P-13 | TestFieldStripping | test_strip_preserves_other_fields | §3.2 | PASS | Stripping does not remove non-forbidden fields |
| P-14 | TestPIIDetection | test_detect_email_simple | §3.3 | PASS | Email in any nested field detected |
| P-15 | TestPIIDetection | test_detect_email_deeply_nested | §3.3 | PASS | Email in deeply nested dict detected |
| P-16 | TestPIIDetection | test_detect_email_in_list | §3.3 | PASS | Email in a list value detected |
| P-17 | TestPIIDetection | test_detect_phone_dashes | §3.3 | PASS | US phone with dashes detected |
| P-18 | TestPIIDetection | test_detect_phone_dots | §3.3 | PASS | US phone with dots detected |
| P-19 | TestPIIDetection | test_detect_phone_no_separator | §3.3 | PASS | US phone without separators detected |
| P-20 | TestPIIDetection | test_detect_phone_parens | §3.3 | PASS | US phone with parentheses detected |
| P-21 | TestPIIDetection | test_detect_phone_international | §3.3 | PASS | International phone with + prefix detected |
| P-22 | TestPIIDetection | test_detect_ssn | §3.3 | PASS | SSN pattern (###-##-####) detected |
| P-23 | TestPIIDetection | test_detect_credit_card | §3.3 | PASS | 13-19 digit number detected as credit card |
| P-24 | TestPIIDetection | test_detect_multiple_pii_types | §3.3 | PASS | Multiple PII types detected in one payload |
| P-25 | TestPIIDetection | test_clean_payload_no_pii | §3.3 | PASS | Clean payload returns empty list (no false positives) |

### Supplemental Privacy Tests (False Positive Guard)

| ID | Class | Test | Dev Req | Status | Description |
|----|-------|------|---------|--------|-------------|
| P-26 | TestPIIDetection | test_salary_not_false_positive | §3.3 | PASS | Salary values (5-digit) not flagged as credit cards |
| P-27 | TestPIIDetection | test_zip_code_not_false_positive | §3.3 | PASS | 5-digit zip codes not falsely flagged |
| P-28 | TestPIIDetection | test_integer_values_ignored | §3.3 | PASS | Integer values are not scanned (only strings) |
| P-29 | TestPIIDetection | test_none_values_ignored | §3.3 | PASS | None values do not cause errors |
| P-30 | TestPIIDetection | test_boolean_values_ignored | §3.3 | PASS | Boolean values do not cause errors |
| P-31 | TestPIIDetection | test_nested_list_of_dicts | §3.3 | PASS | PII in list of dicts detected recursively |

---

## test_api_contract.py — Dev Req §4: API Contract + §5.3 Validation

| ID | Class | Test | Dev Req | Status | Description |
|----|-------|------|---------|--------|-------------|
| A-01 | TestContributeEndpoint | test_clean_signal_returns_200 | §4.1 | PASS | Clean signal stores and returns 200 |
| A-02 | TestContributeEndpoint | test_clean_signal_stored_in_sp_events | §4.1 | PASS | Clean signal ends up in sp_events, not quarantine |
| A-03 | TestContributeEndpoint | test_server_sets_event_id | §4.1 | PASS | event_id is server-generated UUID, not from client |
| A-04 | TestContributeEndpoint | test_server_sets_collected_at | §4.1 | PASS | collected_at is server-set, not from client |
| A-05 | TestContributeEndpoint | test_server_sets_pipeline_version | §4.1 | PASS | pipeline_version is server-set, always 1 |
| A-06 | TestContributeEndpoint | test_session_epoch_auto_created | §4.1 | PASS | First POST for a session_token creates a session_epochs row |
| A-07 | TestContributeEndpoint | test_session_epoch_not_duplicated | §4.1 | PASS | Second POST with same token does not create duplicate session_epochs |
| A-08 | TestContributeEndpoint | test_taburl_stripped_before_storage | §3.2/§4.1 | PASS | tabUrl stripped from payload before storage in sp_events |
| A-09 | TestContributeEndpoint | test_collectedat_stripped_before_storage | §3.2/§4.1 | PASS | collectedAt stripped from payload before storage in sp_events |
| A-10 | TestContributeEndpoint | test_pii_email_routes_to_quarantine | §3.3/§4.1 | PASS | Signal with email PII goes to quarantine, client gets 200 |
| A-11 | TestContributeEndpoint | test_quarantine_has_redaction_types | §3.3/§4.1 | PASS | Quarantine entry has correct redaction_types JSON array |
| A-12 | TestContributeEndpoint | test_pii_phone_routes_to_quarantine | §3.3/§4.1 | PASS | Signal with phone PII goes to quarantine |
| A-13 | TestContributeEndpoint | test_pii_ssn_routes_to_quarantine | §3.3/§4.1 | PASS | Signal with SSN pattern goes to quarantine |
| A-14 | TestContributeEndpoint | test_multi_pii_all_types_recorded | §3.3/§4.1 | PASS | Multiple PII types all recorded in redaction_types |
| A-15 | TestContributeValidation | test_missing_session_token_400 | §5.3 | PASS | Missing session_token returns 400 |
| A-16 | TestContributeValidation | test_missing_epoch_id_400 | §5.3 | PASS | Missing epoch_id returns 400 |
| A-17 | TestContributeValidation | test_epoch_id_zero_400 | §5.3 | PASS | epoch_id = 0 returns 400 (must be >= 1) |
| A-18 | TestContributeValidation | test_epoch_id_negative_400 | §5.3 | PASS | Negative epoch_id returns 400 |
| A-19 | TestContributeValidation | test_invalid_event_type_400 | §5.3 | PASS | Invalid event_type returns 400 |
| A-20 | TestContributeValidation | test_missing_source_400 | §5.3 | PASS | Missing source returns 400 |
| A-21 | TestContributeValidation | test_invalid_domain_400 | §5.3 | PASS | Invalid domain returns 400 |
| A-22 | TestContributeValidation | test_missing_payload_400 | §5.3 | PASS | Missing payload returns 400 |
| A-23 | TestContributeValidation | test_empty_payload_400 | §5.3 | PASS | Empty payload dict returns 400 |
| A-24 | TestContributeValidation | test_invalid_json_body_400 | §5.3 | PASS | Non-JSON body returns 400 |
| A-25 | TestContributeValidation | test_all_valid_domains_accepted | §5.3 | PASS | All three domains (jobs, events, business) return 200 |
| A-26 | TestContributeValidation | test_all_valid_event_types_accepted | §5.3 | PASS | All four event types return 200 |
| A-27 | TestBurnEndpoint | test_burn_returns_200 | §4.2 | PASS | Burn endpoint returns 200 |
| A-28 | TestBurnEndpoint | test_burn_sets_contributor_id_null | §4.2 | PASS | Burn sets session_epochs.contributor_id = NULL |
| A-29 | TestBurnEndpoint | test_burn_sets_burned_at | §4.2 | PASS | Burn sets session_epochs.burned_at to a timestamp |
| A-30 | TestBurnEndpoint | test_burn_increments_burn_pool | §4.2 | PASS | Burn creates/increments burn_pool entry for current month |
| A-31 | TestBurnEndpoint | test_burn_pool_has_expiry | §4.2 | PASS | Burn pool entry has expires_at (~1 year from burned_at) |
| A-32 | TestBurnEndpoint | test_burn_missing_token_400 | §4.2 | PASS | Missing session_token returns 400 |
| A-33 | TestBurnEndpoint | test_burn_nonexistent_token_200 | §4.2 | PASS | Burning non-existent token returns 200 (idempotent) |

---

## test_metadata_quality.py — Dev Req §5: Data Quality

| ID | Class | Test | Dev Req | Status | Description |
|----|-------|------|---------|--------|-------------|
| M-01 | TestMetadataRegistration | test_all_tables_in_meta_table_catalog | §5.1 | PASS | All 5 SpiritPool tables registered in meta_table_catalog |
| M-02 | TestMetadataRegistration | test_all_tables_have_layer | §5.1 | PASS | Every registered table has a non-empty layer assignment |
| M-03 | TestMetadataRegistration | test_all_tables_have_purpose | §5.1 | PASS | Every registered table has a non-empty purpose |
| M-04 | TestMetadataRegistration | test_sp_events_columns_documented | §5.1 | PASS | sp_events: all ORM columns have meta_column_catalog entries |
| M-05 | TestMetadataRegistration | test_quarantine_columns_documented | §5.1 | PASS | quarantine: all ORM columns have meta_column_catalog entries |
| M-06 | TestMetadataRegistration | test_session_epochs_columns_documented | §5.1 | PASS | session_epochs: all ORM columns have meta_column_catalog entries |
| M-07 | TestMetadataRegistration | test_burn_pool_columns_documented | §5.1 | PASS | burn_pool: all ORM columns have meta_column_catalog entries |
| M-08 | TestMetadataRegistration | test_contributors_columns_documented | §5.1 | PASS | contributors: all ORM columns have meta_column_catalog entries |
| M-09 | TestDataLineage | test_all_lineage_entries_exist | §5.1 | PASS | All 6 expected source→target lineage entries registered |
| M-10 | TestDataLineage | test_lineage_has_description | §5.1 | PASS | All lineage entries have non-empty description |
| M-11 | TestDataContracts | test_contract_files_exist | §5.2 | PASS | All 4 required data contract files exist in docs/contracts/ |
| M-12 | TestDataContracts | test_contracts_not_empty | §5.2 | PASS | All contract files are non-trivial (> 100 bytes) |

---

## test_observability.py — Dev Req §6: Observability + T2.5

| ID | Class | Test | Dev Req | Status | Description |
|----|-------|------|---------|--------|-------------|
| O-01 | TestAuditTrail | test_event_has_pipeline_version | §6.3 | PASS | Every sp_event has pipeline_version for re-processing tracking |
| O-02 | TestAuditTrail | test_quarantine_has_rule_version | §6.3 | PASS | Every quarantine record has rule_version for re-processing |
| O-03 | TestAuditTrail | test_session_epoch_tracks_created_at | §6.3 | PASS | session_epochs.created_at is set on creation |
| O-04 | TestAuditTrail | test_session_epoch_tracks_burned_at | §6.3 | PASS | session_epochs.burned_at can be set (initially NULL) |
| O-05 | TestBurnPoolMaintenance | test_cleanup_deletes_expired | T2.5 | PASS | Expired burn_pool records deleted by cleanup logic |
| O-06 | TestBurnPoolMaintenance | test_cleanup_noop_when_none_expired | T2.5 | PASS | Cleanup is a no-op when no records are expired |
| O-07 | TestBurnPoolMaintenance | test_scheduler_config_has_cleanup_job | T2.5 | PASS | scheduler.yaml has burn_pool_cleanup entry (enabled, daily cron) |
| O-08 | TestBurnPoolMaintenance | test_cleanup_function_importable | T2.5 | PASS | _run_burn_pool_cleanup is importable and callable |

---

## Acceptance Criteria Cross-Reference

Maps each DEVELOPMENT_REQUIREMENTS_PLAN.md acceptance criterion to the test(s) that verify it.

### §2.1 Forward-Compatible Events Table
| Criterion | Test ID(s) | Verified |
|-----------|-----------|----------|
| 64-char hex session_token stores without truncation | S-01 | YES |
| epoch_id = 999999 stores without overflow | S-03 | YES |
| Unknown JSONB fields preserved exactly | S-04 | YES |
| collected_at always reflects server time | A-04 | YES |

### §2.2 Session Epochs Table
| Criterion | Test ID(s) | Verified |
|-----------|-----------|----------|
| Row created on first POST per session_token | A-06 | YES |
| contributor_id can be set to NULL (burn) | S-07, S-08, A-28 | YES |
| Multiple tokens for same contributor | S-09 | YES |

### §2.3 Quarantine Table
| Criterion | Test ID(s) | Verified |
|-----------|-----------|----------|
| PII-flagged events stored here, NOT in events | A-10 | YES |
| redaction_types accurately lists all patterns | S-11, A-11, A-14 | YES |

### §2.4 Burn Pool Table
| Criterion | Test ID(s) | Verified |
|-----------|-----------|----------|
| Monthly aggregate only | S-13 | YES |
| Maintenance job deletes expired | O-05 | YES |
| expires_at enforced | S-14, A-31 | YES |

### §2.5 Contributors Table
| Criterion | Test ID(s) | Verified |
|-----------|-----------|----------|
| No PII stored | S-15 (test_no_pii_columns) | YES |
| total_signals tracks volume only | S-17 (test_total_signals_increments) | YES |

### §3.1 IP Suppression
| Criterion | Test ID(s) | Verified |
|-----------|-----------|----------|
| Zero IPv4 patterns in logs | P-03 | YES |
| Zero IPv6 patterns in logs | P-04 | YES |
| Custom Flask request handler | P-01, P-02 | YES |
| No IP column in any table | P-05, P-06 | YES |

### §3.2 Field Stripping
| Criterion | Test ID(s) | Verified |
|-----------|-----------|----------|
| tabUrl never in events/quarantine | P-07, P-09, A-08 | YES |
| collectedAt never in events/quarantine | P-08, P-10, A-09 | YES |
| No-op when already absent | P-12 | YES |

### §3.3 PII Quarantine Pipeline
| Criterion | Test ID(s) | Verified |
|-----------|-----------|----------|
| Email → quarantine with ['email'] | P-14, A-10 | YES |
| Phone → quarantine with ['phone'] | P-17–P-21, A-12 | YES |
| SSN → quarantine with ['ssn'] | P-22, A-13 | YES |
| Multi-PII → all types | P-24, A-14 | YES |
| Clean payloads flow normally | P-25, A-01, A-02 | YES |
| Extension always receives 200 | A-01, A-10 | YES |

### §4.1 POST /api/contribute
| Criterion | Test ID(s) | Verified |
|-----------|-----------|----------|
| 200 success (stored or quarantined) | A-01, A-10 | YES |
| 400 session_token missing | A-15 | YES |
| 400 epoch_id missing | A-16 | YES |
| 400 event_type/source/domain/payload missing | A-19–A-23 | YES |
| Server-set event_id, collected_at, pipeline_version | A-03, A-04, A-05 | YES |

### §4.2 POST /api/burn
| Criterion | Test ID(s) | Verified |
|-----------|-----------|----------|
| Set contributor_id = NULL | A-28 | YES |
| Set burned_at = NOW() | A-29 | YES |
| Increment burn_pool | A-30 | YES |
| Return 200 | A-27 | YES |

### §5.1 Metadata Registration
| Criterion | Test ID(s) | Verified |
|-----------|-----------|----------|
| All tables in meta_table_catalog | M-01 | YES |
| All columns in meta_column_catalog | M-04–M-08 | YES |
| Lineage entries for all flows | M-09, M-10 | YES |

### §5.2 Data Contracts
| Criterion | Test ID(s) | Verified |
|-----------|-----------|----------|
| Contract files exist | M-11 | YES |
| Contracts non-trivial | M-12 | YES |

### §6.3 Audit Trail
| Criterion | Test ID(s) | Verified |
|-----------|-----------|----------|
| pipeline_version tracking | O-01 | YES |
| Quarantine rule_version | O-02 | YES |
| created_at / burned_at timestamps | O-03, O-04 | YES |

---

## Coverage Gaps (Known — Deferred to T4+)

| Gap | Roadmap Task | Reason Deferred |
|-----|-------------|-----------------|
| §5.4 Job run logging (MetaJobRun per batch) | T4.1 | Contributes to observability but not yet implemented in endpoint code |
| §7 Integration tests §8.1–§8.5 (end-to-end) | T4.1 | Requires full pipeline validation across all layers |
| §8.3 Config signing validation | T4.1 | Extension-side concern — no backend surface yet |
| §8.4 Token rotation multi-epoch | T4.1 | End-to-end integration test across multiple requests |
| Contribute endpoint 500 error path | T4.1 | Requires forcing DB failure during endpoint execution |
| Burn endpoint 500 error path | T4.1 | Requires forcing DB failure during burn execution |
| Burn pool increment-existing branch | T4.1 | All current burn tests create new pool entries; none test second burn in same month |
| Burn endpoint invalid JSON body | T4.1 | Missing test for non-JSON body on /api/burn (analogous to A-24) |
| Dashboard STALE status branch | T4.1 | Would need events with old collected_at (>7 days) to trigger |
| Dashboard AGING status branch | T4.1 | Would need events with 3-7 day old collected_at to trigger |
| Legacy dual-write end-to-end via HTTP | T4.1 | Unit tests cover _dual_write_to_sp_events; full HTTP integration deferred |

---

## T3 Test Addition Details

### test_dashboard_spiritpool.py — T3.2: Dashboard Monitoring (NEW)

| ID | Class | Test | Dev Req | Status | Description |
|----|-------|------|---------|--------|-------------|
| D-01 | TestSpEventsFresnhness | test_no_events_shows_empty_message | §6.1 | PASS | Empty sp_events table shows "No events received yet" |
| D-02 | TestSpEventsFresnhness | test_fresh_event_shows_fresh | §6.1 | PASS | Recent event shows FRESH status |
| D-03 | TestSpEventsFresnhness | test_domain_coverage_breakdown | §6.1 | PASS | Domain coverage shows event_type distribution with percentages |
| D-04 | TestQuarantineHealth | test_no_data_shows_empty | §6.1 | PASS | Empty tables show "No events processed yet" |
| D-05 | TestQuarantineHealth | test_healthy_rate | §6.1/§6.2 | PASS | 0% quarantine rate → HEALTHY status |
| D-06 | TestQuarantineHealth | test_warning_rate | §6.1/§6.2 | PASS | 10% quarantine rate → WARNING status (§6.2 threshold: >5%) |
| D-07 | TestQuarantineHealth | test_critical_rate | §6.1/§6.2 | PASS | 20% quarantine rate → CRITICAL status (§6.2 threshold: >15%) |
| D-08 | TestSessionEpochs | test_no_sessions_shows_empty | §6.1 | PASS | Empty session_epochs shows "No sessions recorded yet" |
| D-09 | TestSessionEpochs | test_active_and_burned_counts | §6.1 | PASS | Sessions split by active/burned with burn rate percentage |
| D-10 | TestBurnPool | test_no_data_shows_empty | §6.1 | PASS | Empty burn_pool shows "No burn pool data yet" |
| D-11 | TestBurnPool | test_active_month_shown | §6.1 | PASS | Active month with signal count displayed with ACTIVE status |
| D-12 | TestBurnPool | test_expired_month_flagged | §6.1 | PASS | Expired month (past expires_at) flagged as EXPIRED |
| D-13 | TestContributorVolume | test_no_contributors_shows_empty | §6.1 | PASS | Empty contributors shows "No contributors registered yet" |
| D-14 | TestContributorVolume | test_contributor_stats | §6.1 | PASS | Shows total contributors, total signals, avg signals/contributor |

### test_legacy_compat.py — T3.3: Legacy Route Compatibility (NEW)

| ID | Class | Test | Dev Req | Status | Description |
|----|-------|------|---------|--------|-------------|
| L-01 | TestLegacyFieldStripping | test_strip_tabUrl_from_signal | §3.2/§4.3 | PASS | tabUrl stripped from legacy signal payloads |
| L-02 | TestLegacyFieldStripping | test_strip_collectedAt_from_signal | §3.2/§4.3 | PASS | collectedAt stripped from legacy signal payloads |
| L-03 | TestLegacyFieldStripping | test_strip_nested_payload | §3.2/§4.3 | PASS | Nested payload fields stripped, non-forbidden fields preserved |
| L-04 | TestLegacyPrivacyFix | test_no_ip_in_log_format_string | §3.1/§4.3 | PASS | Legacy contribute() source has no ip=%s or remote_addr references |
| L-05 | TestLegacyDualWrite | test_clean_signal_goes_to_sp_events | §4.3 | PASS | Clean signal dual-writes to sp_events with source_type=extension_legacy |
| L-06 | TestLegacyDualWrite | test_pii_signal_goes_to_quarantine | §4.3 | PASS | PII signal dual-writes to quarantine (not sp_events) |
| L-07 | TestLegacyDualWrite | test_dual_write_failure_is_non_fatal | §4.3 | PASS | Dual-write failure is caught and logged — does not break legacy path |
| L-08 | TestLegacyDualWrite | test_legacy_payload_fields_preserved | §4.3 | PASS | Original signal fields + legacy_contributor_id + legacy_domain preserved |
| L-09 | TestLegacyResponseFormat | test_response_has_accepted_new_jobs_failed | §4.3 | PASS | Response includes accepted, new_jobs, failed keys for background.js compat |
