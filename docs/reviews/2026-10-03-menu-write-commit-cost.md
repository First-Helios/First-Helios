# Menu-write commit cost: root cause and measured fix (ADR-0005 Amendment 1)

Session A, 2026-10-03. Follows ADR-0013 Amendment 8 item 6: one large page (`llm` and
`jsonld` streams, over 1,000 rows) took at least 1 h 25 min to commit on the laptop,
and a full extraction pass waits for a fix. This record finds the cause, measures the
current schema and two prototype changes, and backs the proposal in
[ADR-0005 Amendment 1](../adr/0005-immutable-menu-snapshots-and-selection.md#amendment-1-2026-10-03-proposed-commit-time-integrity-check-cost).

**Measured only.** The prototypes were applied by hand to disposable `*_test`
databases; no migration, model or repository code changed. The fix itself is a
migration under `alembic/versions/` (stop-and-ask), so it waits for the owner.

## Cause

Two costs multiply at commit:

1. **Once per row.** Each of the eight Menu tables has the deferred constraint trigger
   `ct_menu_integrity`, which runs `menu.check_aggregate(page)` for every inserted
   row. Every run checks the whole page, so a page of R rows is checked R times.
2. **Whole-catalogue path walks.** `check_aggregate` calls `menu.node_path` for every
   node and price. `node_path`'s recursive step joins `menu.nodes(NULL)`, which is every
   section, item, variant and modifier of every page in the database. The plan is a
   sequential scan of all four tables per call (`EXPLAIN` of `node_path('item', 1)`:
   `Seq Scan` on `menu_section`, `menu_item`, `menu_variant`, `menu_modifier` under the
   recursive union). So each check also grows with the number of Menu nodes already
   stored.

Commit cost is roughly R × (nodes + prices on the page) × path depth × stored nodes:
quadratic in page size, and linear in the corpus on top of that. A full pass would slow
down with every page it wrote. `node_path` is also used by the price selector
(`packages/helios_core/domains/menu/selection.py`, `_path_applicability_ids`), so the
Gold refresh likely has the same corpus-linear cost per node; that was not measured
here.

## Method

- Environment: cloud container, 4 vCPU, 15 GB RAM, PostgreSQL 16.14 (local, no
  PostGIS; the schema doesn't use it), the repository at `d00618c` migrated to head
  (`7c2e4b9d1f3a`). Not the laptop and not the Pi; ratios matter, not absolute times.
- Page: the test fixture's aggregate (`test/menu_support.py::aggregate`) widened to
  n priced items in one section: 1 page, 1 section, n items, 1 applicability, n prices
  and n + 3 + n Evidence links (rows = 4n + 6). Written with `persist_menu`, then
  committed; flush (`persist_s`, includes the command's own explicit
  `check_aggregate`) and commit (`commit_s`, the deferred triggers) timed separately.
- Corpus probe: a 10-item page committed before and after bulk-loading 20 or 100
  pages of 100 items (the bulk load ran with `ct_menu_integrity` disabled, only to grow
  the corpus; `persist_menu` still checked each bulk page once).
- Prototypes (scratch SQL, not committed):
  - **B, keyed path:** a new `menu.node(kind, id)` that reads one node by primary key,
    and `menu.node_path` rewritten to follow parent and base edges through it
    (`CROSS JOIN LATERAL (node(parent) UNION node(base))`) instead of joining
    `nodes(NULL)`. Same signature and rows.
  - **A, once per aggregate state:** a `BEFORE INSERT` trigger on the eight tables
    bumps a transaction-local counter (`set_config('helios_menu.generation', …,
    true)`); `menu.check_integrity` skips a page whose last check in this transaction
    saw the current counter, and records it after a successful check. Any Menu insert
    since a page's last check forces a re-check, so `SET CONSTRAINTS … IMMEDIATE`
    mid-transaction stays covered.
- Runs shared the 4 vCPUs (each in its own database): the baseline was measured twice,
  once beside a CI run and once beside three other benchmarks, and agreed within 15 %
  (n=100: 233.6 s and 225.8 s; the table uses the second).

## Results

**Commit time by page size** (fresh database each, corpus = the earlier pages of the
same run):

| Variant | n=10 (46 rows) | n=25 (106) | n=50 (206) | n=100 (406) |
|---|---|---|---|---|
| Current schema | 2.43 s | 13.33 s | 52.78 s | 225.78 s |
| B keyed path only | 3.73 s | 18.71 s | 72.30 s | 288.90 s |
| A once per state only | 0.08 s | 0.13 s | 0.26 s | 0.56 s |
| **A + B** | **0.10 s** | **0.19 s** | **0.33 s** | **0.66 s** |

The current schema is quadratic (×4.0–4.3 per doubling). A + B is linear (about
1.6 ms per row at n=100, ~340× faster). B alone is slower on a near-empty database:
the per-row repetition dominates and the lateral lookups cost more than scanning a few
rows.

**Commit time of a 10-item page vs stored Menu nodes:**

| Variant | 11 nodes | 2,042 nodes | 10,122 nodes |
|---|---|---|---|
| Current schema | 2.48 s | 6.47 s | not run (~4 min per 100-item page to build) |
| B keyed path only | 3.92 s | 3.26 s | — |
| A once per state only | 0.05 s | — | 0.53 s (flush 0.23 → 0.61 s) |
| **A + B** | **0.08 s** | **0.07 s** | **0.08 s** (flush 0.31 → 0.20 s) |

A alone still grows with the corpus (×10 commit at 10k nodes, and the flush's explicit
check grows too). B removes the corpus term. Only A + B is flat in the corpus and linear
in page size.

**Invariants.** With A + B applied to a migrated `*_test` database (the 8
`trg_menu_generation` triggers present before and after the run), the existing Menu,
Gold and menu-API suites pass unchanged in strict mode: `test_menu_schema`,
`test_menu_replay`, `test_menu_precedence`, `test_menu_concurrency`,
`test_menu_extraction`, `test_menu_boundaries`, `test_gold_refresh`,
`test_gold_price_index`, `test_gold_catalog`, `test_api_venue_menu`: **339 passed**.
The schema-rebuilding migration suites (`test_menu_migration`, `test_gold_migration`,
`test_gold_price_index_migration`) were left out because they would replace the
patched functions; the real migration runs them.

**Repository baseline.** On `d00618c` with no patch, `HELIOS_STRICT_DB_TESTS=1 make ci`
passed (1,355 tests, coverage 92 %) and `alembic upgrade head && alembic check` passed.

## What this doesn't show

- Laptop or Pi times, or the real 1,000-row two-stream page; RUN-A-01 below does that
  after the migration merges.
- Pages with an Organization base pin (`base_organization_page_id`), deep section
  trees or variants and modifiers: the benchmark page is one section of priced items.
  The invariant suites cover those shapes for correctness, not for time.
- Gold refresh time (expected to benefit from B; not measured).

## Owner-run checklist RUN-A-01 (after the migration merges)

Re-time the page that took 1 h 25 min, on a disposable clone, never on
`helios_laptop` itself. Not a gate: the migration's tests already show the cost is
linear (below); this confirms the absolute time on the laptop before the first full
pass.

1. On the laptop, check out `main` at the merge commit; paste `git rev-parse HEAD`.
2. With no other connections to `helios_laptop`:
   `createdb -T helios_laptop helios_a1_retime`.
3. Against the clone only: `DATABASE_URL=…/helios_a1_retime uv run alembic upgrade head`,
   then paste `alembic current` (expect `db40e9424cba (head)`).
4. Re-extract the large page's Version on the clone with the extract CLI and its saved
   raw answers (`var/replay/menu-extract/`). The coordinating session confirms the exact
   command and that the page is due on the clone before this step, since the due set
   depends on the pipeline version at the time.
5. Paste the CLI's `extraction run complete` line and the page's commit time
   (`extraction started` to completion for a one-page run).
6. `dropdb helios_a1_retime`.

**Implemented** (2026-10-08) in revision `db40e9424cba`, both changes as proposed.
Tests: `test/test_menu_commit_check.py` (a later insert after an `IMMEDIATE` check is
rechecked; a savepoint rollback can't skip a check; one `check_aggregate` call per
page at commit; old and new `node_path` give identical rows on every node of a
nested, base-pinned, variant and modifier fixture plus a self-parented section).
SQL snapshots: [upgrade](./sql/2026-10-08-a1-menu-commit-check-upgrade.sql),
[downgrade](./sql/2026-10-08-a1-menu-commit-check-downgrade.sql). Re-measured on a
CI-image PostgreSQL (`imresamu/postgis:16-3.4`, 100-item page, 406 rows): commit
0.45 s.
