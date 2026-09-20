# Step 5 bounded Menu writer — independent technical review and disposition

**Date:** 2026-09-19. **Owner:** Fortune. **Branch:** `Plan-0002-Step-5`.
**Reviewed HEAD:** `02549a44f6da051288be3489127ed78d9a62c017`
(the prior unit's drift-fix commit), on the provider acceptance base
`de71d52f1b07ca363cc6cf8aa7a56cd2bc04ab3b`; branch and HEAD verified without
switching, working tree clean.
**Disposition:** the bounded Menu writer, its migration and both concrete SQL
directions are review drafts. Owner Menu SQL acceptance is **not** inferred from
green tests or from the instruction to review. See
[§Owner disposition](#owner-disposition).

This record is the independent review requested by the
[writer review](0002-step-5-menu-writer-review.md#limits-next-unit-and-remaining-estimate)
and the [provider acceptance/handoff](0002-step-5-provider-acceptance-and-menu-handoff.md).
It does not rewrite that history. ADR-0005 and its reconciled proposal
(accepted 2026-09-17) and the corrected provider implementation and both
provider SQL directions (accepted 2026-09-18, "All looks good on the
implementation guide, All proposals approved") remain settled and were not
re-requested. The five accepted provider artifacts are unchanged.

## Scope reviewed

The nine-table `menu` schema and single revision `d83f0a21c592` after
`b72e6a90c431`; the [models](../../packages/helios_core/domains/menu/models.py),
[contracts](../../packages/helios_core/domains/menu/contracts.py) and
[commands](../../packages/helios_core/domains/menu/commands.py); the
[migration](../../alembic/versions/d83f0a21c592_add_immutable_menu_aggregates.py);
the [concrete upgrade SQL](sql/0002-step-5-menu-upgrade.sql) and
[concrete downgrade SQL](sql/0002-step-5-menu-downgrade.sql); the focused Menu
tests (schema, replay/lifecycle, concurrency, migration, boundaries). Provider
artifacts were checked only for byte-preservation, not re-reviewed.

## Findings

**No Menu-only defect required correction. No source, migration, SQL or test
byte was changed by this review.** All six reviewed Menu artifacts remain at the
hashes recorded in the writer review, and the five accepted provider artifacts
remain byte-identical.

The one real defect from the prior unit — the ORM index `ix_menu_evidence_page`
on `menu.evidence_link (page_id)` that revision `d83f0a21c592` did not create —
was already fixed at HEAD `02549a4`. This review confirmed the fix is coherent
across all four surfaces: the model declares it, the revision issues the
`CREATE INDEX` (migration line 398), the concrete upgrade SQL contains it
(line 329), and it exists in a freshly built database. `alembic check` reports
no drift.

Points examined and judged correct / intentional, not defects:

- **Immutability.** `menu.reject_mutation` rejects `UPDATE`/`DELETE`/`TRUNCATE`
  on all nine tables and `INSERT` on `currency`; verified live (both a currency
  `UPDATE` and an extra-currency `INSERT` were rejected with SQLSTATE 23514).
- **Admission vs. deferred integrity.** Live checks run `BEFORE INSERT`
  (`admit_page`/`admit_member`, each calling the complete Identity local/base
  batch before `menu.lock_admission`); immutable graph/support/correspondence
  runs in the deferred `ct_menu_integrity` constraint trigger and is also forced
  eagerly by the command's explicit `menu.check_aggregate`. Matches ADR-0005 §7.
- **Commands never commit.** `persist_menu` wraps work in `begin_nested`
  (savepoint) and forces `check_aggregate`; there is no `session.commit`.
  `read_aggregate` is read-only. A caught reference error cannot leave a
  supported prefix committable.
- **SQL synchronization.** Both concrete artifacts are byte-identical to fresh
  offline `alembic --sql` generation except a single trailing blank line (the
  documented terminal-whitespace normalization). No `CASCADE`; 9 `CREATE TABLE
  menu.` / 9 `DROP TABLE menu.`. Downgrade drops only Menu-owned objects in
  dependency order and restores revision `b72e6a90c431`.
- **`menu.whitespace()`** enumerates exactly Python `str.strip()`'s 29
  whitespace code points (compared directly against a freshly built database).
- **Design conformance** to ADR-0005's eleven normative decisions (nine
  tables/one immutable aggregate; direct/inherited/structural support;
  inherit/replace/suppress; pins through ordinary supersession; subject/version/
  event-independent stream identity; withdrawal tombstone + explicit
  restoration/rebasing; admission ≠ deferred integrity; providers own
  policy/locks; accepted-claim history with K/O/E deferred to selection; context
  intersection; USD-only, price scope never inferred).
- **Observations left to the selector unit, not defects:** `menu.check_context`
  treats a NULL half-open bound and a NULL `service_period` as compatible
  (only a fully-bounded empty overlap or a genuine channel/period conflict
  fails); repeated `require_resolved_scopes` + `lock_admission` per inserted
  member is the accepted correctness-first serialization, not a throughput claim.

## Verification (fresh disposable data, 2026-09-19)

Re-run from a newly provisioned, empty database — not the prior unit's run.
Every count is from this run.

| Check | Evidence |
|---|---|
| Strict `make ci` | All pre-commit hooks Passed; `mypy --strict` **Success, 56 source files**; `uv lock --check` clean. Tests: **508 passed, 0 failed, 0 errors, 0 skipped**, **248.91s**, exit 0; coverage **98%**. |
| Menu package coverage | `models.py` **100%**, `commands.py` **95%**, `contracts.py` **95%**. |
| Menu tests | **229**: schema 145, replay/lifecycle 20, concurrency 48, migration 3, boundaries 13 (independently collected). |
| Concurrency tests | **101** total (**48 Menu** + 39 provider + 14 foundation), run inside `make ci` with 0 skips: both race orders, stronger-isolation rollback/revalidation, real deadlock retry, whole-transaction `40001`/`40P01` retry. |
| Migration round trips | **3** `test_menu_migration` tests passed: seeded upgrade→seed→downgrade→re-upgrade over both the Alembic path and the checked-in concrete SQL, plus SQL-generation equality. |
| Drift & head | `alembic check`: **No new upgrade operations detected**; `alembic heads`/`current` both **d83f0a21c592** (single head). |
| SQL synchronization | Both artifacts equal fresh offline generation (one trailing blank line only); no `CASCADE`; 9 `CREATE`/9 `DROP TABLE menu.`. |
| Live raw-SQL probes | Fresh DB has 9 `menu` tables, USD seeded, `ix_menu_evidence_page` present, `admission_fence` sequence present, immutability `UPDATE`/`INSERT` rejected, `whitespace()` == Python `str.strip()` (29 code points). |
| Menu artifact hashes | All **6** byte-identical to the writer review packet. |
| Provider preservation | All **5** accepted provider artifact SHA-256 byte-identical. |

Environment: `/snap/docker/current/bin/docker` (29.8.0) with sandbox
escalation, image `imresamu/postgis:16-3.4`, digest
`sha256:6da75969915039b7356058b4310d43fde88c275ada982c2dfee29da68445ff4d`,
PostgreSQL **16.4** / PostGIS **3.4.3**, fresh disposable
`helios_menu_review_test` on a distinct container/port. The task-owned
container and its anonymous volume were removed after the run; the developer
stack container `helios-postgres` and volume `infra_postgres_data` were not
touched. No application data was used. This verifies the bounded writer, schema
and both concrete SQL directions on disposable data only — a correctness result,
not a throughput claim, and not owner acceptance of the Menu SQL.

### Reviewed Menu artifact hashes (unchanged)

| Artifact | SHA-256 |
|---|---|
| Revision d83f0a21c592 | `cc5cc345215511687ac16adf6c1a741ba83dff0903ed368f5a03d8ee45f3b153` |
| Concrete upgrade SQL | `55d4c4f36757e8ea188ca968984cdbc4de441f994fe546f6437d7db2c365f097` |
| Concrete downgrade SQL | `b3820db752de822ccebb3700b77498aab7f31983e72ca68e8a0a7019a63d6400` |
| Models | `c99ce3e10654e7799b7d1a3bf63aadf765de90bd86a1f74d2ba411f49e7942c0` |
| Contracts | `64610ca0fa3e1d42921d8981922b4552e72ca0956fbf00bbd0665eecd4ae7227` |
| Commands | `1205ce6ef428a987c8d524572ffbc68fe925663aba2b3d9675faa835d16286ae` |

## Owner disposition

Menu implementation, migration `d83f0a21c592` and both concrete Menu SQL
directions are presented for an explicit owner decision against the hashes
above. Green CI, clean drift and this review are **not** acceptance.

**Status: accepted by owner Fortune on 2026-09-19.** In this session, presented
the bounded Menu writer, revision `d83f0a21c592` and both concrete Menu SQL
directions against the hashes above, with the clean fresh-data verification
recorded here, and asked for an explicit disposition. Fortune's decision:
**"Accept as-is"** — accept the Menu implementation, migration and both concrete
SQL directions at the reviewed hashes. No correction or condition was requested.

This is a real supplied decision, not inferred from green tests or this review.
It accepts the six Menu artifacts at their recorded SHA-256 values; those bytes
are unchanged. It does not authorize the pure current/history selector, ranking,
application-data execution, Gold, APIs, extraction, ML, fuzzy matching, Step 6,
a new dependency, or any deployment. Future changes to these artifacts require
their own scoped review rather than rewriting this decision.
