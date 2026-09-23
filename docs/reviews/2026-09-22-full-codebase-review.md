# Full codebase review at `557fa3c`

**Date:** 2026-09-22. **Owner:** Fortune. **Reviewer:** Claude Code (agent), with
ten read-only slice reviewers. **Branch:** `docs/full-codebase-review`.
**Reviewed commit:** `557fa3ca02126e6c703155617c77668a25e4160c` (`main` after PR #21).
**Migration head:** `5f3a9c1e7b24`.

This is a findings document for owner triage. **Nothing was fixed.** Each fix
becomes its own scoped unit (see [§8](#8-recommended-fix-units)); fixes that touch
models, migrations, dependencies, `infra/`, CI, or auth/secrets still stop for owner
review under CLAUDE.md. Green CI and this document are not acceptance of anything.

## 1. Scope and commit

All tracked files at `557fa3c`: `alembic/`, `packages/helios_core/`, `apps/api/`,
`apps/discovery/`, `config/`, `test/`, `infra/`, `.github/`, tooling config, and the
docs tree (README, ROADMAP, CLAUDE.md, CONTRIBUTING, ADR-0001–0010, RFC-0001, plans,
reviews, retro). ADRs and the
[ADR-0004 review guide](./0004-architecture-review-guide.md) "accepted interpretation"
table were the reference; where docs and code disagree the code was treated as
ground truth and the drift is listed in [§7](#7-doc-drift).

Out of scope, by instruction: the Orange Pi staging host (no SSH, no remote runs),
live network crawling (discovery reviewed statically, through its tests, and with
offline `httpx.MockTransport` snippets), the host PostgreSQL on `localhost:5432`
(the V1 legacy archive — never connected to), and `.env` (never read; see §3.5).

## 2. Method

1. **Baseline.** Strict `make ci` and `alembic check` on a disposable
   `imresamu/postgis:16-3.4` container (`127.0.0.1:55432/helios_test`), then five
   reruns of the three concurrency suites to look for flakes.
2. **Slices.** Ten read-only reviewer agents, one per slice (A schema/migrations,
   B identity, C provenance/Bronze, D menu, E gold, F API, G discovery, H tests,
   I infra/CI/tooling, J docs). None had DB, network, or write access; each
   returned `file:line`, severity, failure scenario, and evidence.
3. **Verification.** Every finding in the tables below was checked against the
   code by the lead reviewer. "Reproduced" means it was demonstrated on the
   disposable DB or with an offline snippet; "Read" means confirmed by reading the
   cited lines; "Plausible" means the code path is real but the failure was not
   executed. Subagent claims that could not be confirmed were dropped or corrected
   (see [§9](#9-dropped-corrected-and-unverified-items)). Duplicates across slices
   were merged; the "Slice" column keeps the original references.
4. **Severity rubric** (as briefed): **Critical** = data loss/corruption, security
   hole, or accepted-ADR invariant violation reachable in normal use; **High** =
   reachable correctness bug; **Medium** = latent bug, or high-cost invariant with no
   guarding test; **Low** = cleanup, dead config, minor drift; **Info** =
   observations and questions.

A note on "reachable": no production Menu data exists yet (Menu extraction is
Phase 5, and every discovered Establishment is still `provisional`, see R105). The
Menu/Gold Highs (R01–R03) are reachable through the accepted, public commands and
reproduce with test-constructed data, but have no production blast radius today.
The discovery Highs (R04–R08) are reachable on the next `resolve_urls` run.

## 3. Baseline verification

### 3.1 Strict CI (disposable DB, 2026-09-22)

`DATABASE_URL=postgresql+psycopg://helios:helios@127.0.0.1:55432/helios_test HELIOS_STRICT_DB_TESTS=1 make ci`

| Step | Result |
|---|---|
| `make lint` (pre-commit, all hooks incl. ruff, ruff-format, mypy) | all Passed |
| `make typecheck` (`mypy .`) | `Success: no issues found in 99 source files` |
| `make test` | **631 passed, 0 skipped, 0 failed, 2 warnings** in 292.43 s |
| Coverage (`--cov=.`) | 7,241 statements, 298 missed, **96%** total — includes `test/`; non-test code is **91%** (2,825 stmts, 248 missed; R112) |
| `uv lock --check` | `Resolved 59 packages` — OK |
| `uv run alembic check` | `No new upgrade operations detected.` |

Warnings: (1) `StarletteDeprecationWarning: Using httpx with starlette.testclient is
deprecated; install httpx2 instead.` (2) `'HTTP_422_UNPROCESSABLE_ENTITY' is
deprecated. Use 'HTTP_422_UNPROCESSABLE_CONTENT' instead.` (both R47).
`alembic check` also logs a benign `SAWarning: Did not recognize type 'geometry'`
from PostGIS/Tiger tables that `include_object` filters out.

This reproduces the last recorded strict figure (PR #21: 631 passed / 0 skipped,
`alembic check` clean). The non-strict figure in the brief (185 passed / 446
skipped, 42%) is the owner's 2026-09-22 run and was not re-derived here.

Lowest non-test coverage: `apps/discovery/__main__.py` 0%, `apps/discovery/resolve_urls.py`
0%, `apps/api/export_openapi.py` 0%, `apps/discovery/overture.py` 58%,
`packages/helios_core/db/url.py` 67% (the `postgresql://` normalization lines run
only in CI, which uses that URL form), `apps/discovery/audit.py` 80%.

### 3.2 Concurrency reruns

`test_identity_concurrency.py`, `test_menu_concurrency.py`,
`test_provider_concurrency.py` (101 tests) rerun five times back to back:
**101 passed each run (505/505)**, 66.6–68.9 s per run. No flakes observed. The
`deadlock detected` lines in the PostgreSQL log come from the two intentional
composed-deadlock retry tests (`test_provider_concurrency.py:263`,
`test_menu_concurrency.py:298`).

### 3.3 The baseline is order-dependent (new finding R11)

After the full run, running `pytest test/test_gold_catalog.py` alone against the
same database fails **4/4** with `InFailedSqlTransaction`; the server log shows
`ERROR: scope is not eligible with the exact current record/event` first. The suite
is green only because `test_gold_catalog.py` sorts before `test_menu_precedence.py`,
which commits remapped/retired Menu families. On a fresh container,
`pytest test/test_menu_precedence.py test/test_gold_catalog.py` gives 4 failed,
22 passed. A second strict run against a reused
`*_test` database is therefore **not** a valid acceptance signal until R01/R11 are
fixed; always use a fresh container.

### 3.4 Leads from the brief

| Lead | Result |
|---|---|
| README dated 2026-09-18, says API is health-only and discovery unimplemented | Confirmed (§7, README) |
| ROADMAP "ADR-0007 = prod hosting" (~L834) and stale §6.4 ledger | Confirmed, plus more stale forward numbers (§7) |
| `pyproject.toml` named `helios-learning` | Confirmed (R96) |
| `mypy.ini` dead sections (`helios_parsing`, `selectolax`, `overpy`, `h3`) | Confirmed (R91); `duckdb` ships `py.typed` so its ignore is also unneeded |
| `ruff.toml` dead per-file-ignores (`apps/scraper/`, `S101`, `PLR2004`) | Confirmed (R92) |
| CODEOWNERS legacy `/packages/**/db/models/` | Confirmed dead (R95) |
| CI `postgresql://` URL without `+psycopg` | **Not an issue.** `Settings._normalize_database_url` normalizes it and every consumer (`db/session.py:20`, `alembic/env.py:18`, `test/conftest.py:30`, test subprocesses) reads the normalized value |

### 3.5 Secrets

- `.env` is gitignored (`.gitignore:18`) and `git log --all -- .env` is empty; it
  was never committed and was not read.
- Secret-pattern scan of the `557fa3c` tree and of every ref's history (AWS/OpenAI/
  Google/GitHub/Slack key shapes, private keys, `key|secret|token = <20+ chars>`):
  **no real credential found.** History hits are placeholder `.env.example` values
  (letters and underscores only), synthetic hex fixtures in V1 tests, and scraped
  third-party HTML pages in V1 commit `13e0afd` (R117). No Critical security issue.

## 4. Summary

| Severity | Count |
|---|---|
| Critical | 0 |
| High | 8 |
| Medium | 32 |
| Low | 56 |
| Info | 21 |
| **Total** | **117** |

The schema and migration layer is in good shape: linear chain, single head, the FK
matrix holds with no `CASCADE`, all decision/menu tables reject mutation, deferred
triggers are real, reviewed SQL artifacts still match the migrations byte for byte,
and ORM↔migration parity was confirmed offline. The problems cluster in three
places:

1. **Menu selection / Gold refresh** (R01–R03, R19–R24, R31): the full-catalog
   refresh cannot survive any Identity correction, and the selector can attribute a
   retired predecessor's facts to its successor. The test suite hides the first bug
   through file ordering.
2. **Discovery URL pipeline and crawler** (R04–R08, R13–R16, R32–R36): robots.txt
   compliance (an ADR-0010 hard requirement) is not met, human `needs_review`
   decisions are overridden, the manual registry cannot correct a bad menu URL,
   and every run permanently appends duplicate Bronze rows.
3. **Verification gaps** (R10, R11, R27–R31): model/migration drift is not gated,
   several "rejects mutation" tests would still pass with the triggers removed, and
   application write paths never fire deferred constraints under test.

## 5. Ranked findings

Verified column: **Reproduced** (demonstrated on the disposable DB or by offline
snippet), **Read** (confirmed by reading the cited lines), **Plausible** (real code
path, failure not executed). All paths are repo-relative.

### 5.1 Critical

None.

### 5.2 High

| # | Slice | Location | Summary | Failure scenario | Verified |
|---|---|---|---|---|---|
| R01 | E1 | `packages/helios_core/domains/menu/selection.py:473-483`; `domains/menu/enumeration.py:122-124`; `gold/catalog.py:47-48` | `_live_scope` catches `SubjectNotEligibleError` from the SQL guard without a savepoint, so the transaction is already aborted when enumeration `continue`s. `refresh_full_catalog` crashes whenever any family's head scope is no longer eligible. | Any remap/unassign/retire/split of a record that has Menu pages → the next full-catalog refresh raises `InFailedSqlTransaction`; Gold can never be rebuilt while that head exists (pages are append-only, so indefinitely). Same in the bounded refresh for a non-live scope, so an `unresolved_scope` row can never be written. | **Reproduced** (§3.3; PG log `scope is not eligible…` then `current transaction is aborted`) |
| R02 | E2 | `selection.py:385-403`, `:633-635`, `:842-844` | `_stream_heads` returns heads for every subject in the family; `_current_gate` passes (returns `None`) when the requested subject owns no head; price/content candidates are not filtered by `page.subject_id`. | Record remapped from A (retired) to B before B has its own page → a request for B selects A's price and content and Gold stores a `priced` row for B with `price_scope_subject_id = A`. Violates ADR-0004 §5 (retired predecessor excluded from current views). Currently masked by R01 on the full-catalog path. | Read |
| R03 | D1 | `selection.py:555-591` vs `:674-707` | Content selection checks base (pin) validity only for `inherit` nodes; price selection treats any node with a `base_id` or a based ancestor as base-dependent. | Organization stream withdraws → a local `replace` node still returns local content while its price is `unresolved_base`. ADR-0005 §4: an invalid base "blocks dependent current content; only independent supported local additions survive". | Read |
| R04 | B1, G5 | `apps/discovery/url_pipeline.py:222-231`, `:288`, `:320` | `_persist_and_assign` treats `needs_review` like `unresolved` and auto-assigns; it also assigns to `venue.organization_subject_id` without checking the Organization is current. | (1) A human `unassign`s a wrong website record → the next monthly run re-assigns it with `actor_class="rule"`, confidence 1, contradicting `commands.py:529-530`. (2) After an Organization merge/retire, the assign raises `ValueError(... not current)` and, because the run is one transaction (R15), every later run fails the same way. `pipeline.py:210` handles `needs_review` correctly; no test covers either path. | Read |
| R05 | G1 | `apps/discovery/web_client.py:161-179`, `:205-207` | robots.txt is evaluated with stdlib `RobotFileParser`, which applies the first matching rule (not the longest) and ignores `*`/`$` wildcards (RFC 9309 §2.2). Disallowed paths are fetched, breaking ADR-0010 §3's hard requirement. | `Allow: /` + `Disallow: /menu` → `can_fetch` True; `Disallow: /*menu` → True; `/menu` is fetched and persisted. `Crawl-delay` is ignored. | **Reproduced** (snippet) |
| R06 | C1 | `packages/helios_core/provenance/contracts.py:242-273`, `:287`; `apps/discovery/pipeline.py:88-92`; `url_pipeline.py:183-194`; `web_client.py:43-46` | `BronzeObservation.canonical_url` is both the only way to record a Source Endpoint and Identity's exact URL match key (`identity/commands.py:542-545`). ADR-0009/0010 require it be `None`, so no discovery Evidence has an endpoint chain; menu-URL Evidence does not reference the fetched page/sitemap (ADR-0010 §2). | Accepted interpretation "Evidence retains the public Source Endpoint chain so a later API can return the original source URL on demand" is unmet for all ~10k Overture rows and every website/menu-URL row; the URL survives only in namespace-specific `source_payload` or the `bundle_path` glob. Bronze is immutable, so every further Pi run adds rows that can never be backfilled. Not rated Critical because the URL is still recoverable from payload. | Read |
| R07 | G3 | `url_pipeline.py:296-301` | The "already has a menu-URL record" check returns before the registry override is consulted. | The operator adds `menu_url:` to `config/sources.yaml` to fix a bad crawled URL and re-runs → nothing changes, ever. Same when the website changes. Defeats the registry's stated purpose (`config/sources.yaml:3-5`). | Read |
| R08 | G2 | `web_client.py:205-212`; `apps/discovery/menu_url.py:74-80`, `:126-129` | Any 200 HTML response counts as a verified menu page. | `<a href="#">Menu</a>` (a hamburger toggle) resolves to the homepage, which is persisted as the menu URL; a site that returns 200 for every path (SPA / soft 404) gets `/menu` with `signal="well_known"`. With R07 the wrong URL is permanent. | **Reproduced** (snippet: `MenuUrlDiscovery(menu_url='https://x.com/', signal='crawled')`) |

### 5.3 Medium

| # | Slice | Location | Summary | Failure scenario | Verified |
|---|---|---|---|---|---|
| R09 | —, A8, F5, I18 | `packages/helios_core/config.py:20`; `alembic/env.py:18`; `apps/api/seed.py:87`, `:107-111`; `apps/discovery/__main__.py:74-84`; `apps/discovery/resolve_urls.py:51-61` | The default `DATABASE_URL` is `localhost:5432/helios` — the same host:port:dbname as the V1 legacy archive, which was listening on this machine during the review. Alembic and all three write CLIs use it with no guard. `seed.py` is also non-idempotent and writes a non-canonical fingerprint. | A bare `uv run alembic upgrade head`, `python -m apps.api.seed`, or `python -m apps.discovery…` with `DATABASE_URL` unset targets the archive (whether the default credentials would authenticate was deliberately not tested). On the Pi, the seed adds 5 duplicate real-venue rows per run that discovery can never dedupe (`franklinbarbecue` vs `franklin barbecue`). | Read (host port observed listening; no connection made) |
| R10 | I1, A5 | `.github/workflows/ci.yml:80-84`; `alembic/env.py:115-121` | No CI step or test runs `alembic check` / `compare_metadata`; CLAUDE.md lists it as part of DB acceptance. Even when run, `compare_server_default` is off and autogenerate cannot see CHECKs, partial-index predicates, triggers, or functions. | A models.py change without a migration passes all five checks and merges. Parity is correct today (offline comparison found none), but nothing keeps it so. | Read |
| R11 | new | `test/test_gold_catalog.py:185-259`; `test/test_menu_precedence.py` | Test outcome depends on file order and on DB freshness; the suite hides R01. | Rerunning strict CI against a reused `*_test` DB fails 4/4 Gold catalog tests; a new test file that sorts earlier and commits a remap would turn CI red for unrelated work. | **Reproduced** |
| R12 | C3 | `provenance/contracts.py:278-282`, `:391-397`; `identity/commands.py:305-307`, `:533-570` | Lock-order inversion: `resolve_source_record_observation` locks the Source Record (`FOR NO KEY UPDATE`) in `persist`, then Subjects; `assign/remap/unassign` lock Subjects, then the Source Record. The comments at `contracts.py:275-277` and `commands.py:537-538` describe the opposite. | Re-observation of record R concurrent with a remap/unassign of R → `40P01`; in discovery that rolls back the whole run. No test pairs these operations. | **Reproduced** (T2 real resolve aborted with 40P01 against remap-ordered locks) |
| R13 | new | `web_client.py:172-177` | robots.txt fetch failure (network error, 401/403, 5xx) is treated as allow-all. RFC 9309 treats 5xx/unreachable as full disallow. | A site with a flaky or 503 robots.txt is crawled as if unrestricted. | Read |
| R14 | new | `web_client.py:73-77`, `:144`, `:212` | `follow_redirects=True` with no scheme/host/IP policy; robots and the per-host throttle apply to the pre-redirect host only; the persisted menu URL is the final redirect target. | A restaurant site (or compromised one) redirects `/menu` to another host (robots never checked), to a third-party ordering site, or to a private address on the Pi's LAN (`192.168.1.x`); the response is cached under `var/` and the URL persisted to Bronze. | Read |
| R15 | new | `resolve_urls.py:45-61`; `__main__.py:74-84`; `packages/helios_core/geo.py:107-112` | Both discovery CLIs run the entire job in one DB transaction and commit once at the end; Nominatim HTTP errors and `raise_for_status` propagate. | A crawl of ~8k websites at ~1 req/s/host runs for hours holding row locks; one exception (R04 case 2, a Nominatim 429, a deadlock per R12) loses every DB write of the run. | Read |
| R16 | C11 | `url_pipeline.py:272-292`; `resolve_urls.py:43` | The website observation is re-persisted every run with `observed_at=now`, so the exact-retry check never matches. | Each monthly run appends a Capture + Version + Evidence per venue (~8k immutable rows) with identical content; the CLI docstring says these venues are "skipped". | Read |
| R17 | C2 | `provenance/contracts.py:34-51`, `:324-352`; `pipeline.py:197-200`; `url_pipeline.py:303-306` | Bronze cannot record a failed fetch or rejected input with a reason code; every call writes `outcome="succeeded"`. Website Captures record no fetch at all and hash a derived payload. | Robots-disallowed, non-200, or not-found menu crawls and blank-name POIs leave no Bronze trace (ADR-0004 §4: rejected input "remains Bronze data with an explicit outcome or reason code"). | Read |
| R18 | B3, G15 | `packages/helios_core/identity/normalize.py:17-18`, `:29-38`; `pipeline.py:214` | NFKD + `[^0-9a-z]` drops every non-ASCII letter, not just accents. | `'Chinese Restaurant 金龍'` and `'Chinese Restaurant 福州'` both fingerprint to `'chinese restaurant'`; `'Đông Phương'` == `'Ông Phương'`. Two bilingual-named venues within 50 m are auto-merged — the expensive wrong-merge ADR-0009 §2 guards against. All-CJK names fall back to the raw, unnormalized string. | **Reproduced** (snippet) |
| R19 | E3 | `selection.py:385-403`, `:842`; `enumeration.py:118-122` | `_stream_heads` has no `ORDER BY`; the selector gates on the first of the subject's heads in dict order, enumeration on the lowest id. | A subject owning two heads under different resolution events can be gated differently by the two paths and by query plan, so identical data rebuilds to different Gold rows (ADR-0006 §6). | Plausible |
| R20 | E4 | `packages/helios_core/gold/refresh.py:102-113` | The bounded refresh deletes per family present in the request list, not per requested scope. | A scope that closed or lost all priced targets produces no requests, so its old `priced` rows stay; bounded(S) ≠ full-catalog(S). | Read |
| R21 | E6, D5 | `selection.py:466-484` → `alembic/versions/b72e6a90c431_add_provider_scope_contracts.py:174-215`; `gold/catalog.py:47` | The read-side selector re-admits scopes through the writer's guard, taking `FOR NO KEY UPDATE` row locks and a shared advisory lock until commit; Gold adds no serialization or retry. | A long full-catalog refresh blocks Identity writers and `persist_menu`, makes `rebuild_identity_projections` fail fast, and can deadlock against other refreshes or writers; likely unusable in a read-only transaction. | Read (deadlock Plausible) |
| R22 | D2 | `selection.py:275-285` | `_canonical_native_path` maps a base-linked node to the base's bare native path, losing base-page identity. | JSON-LD pins Organization page O1 and DOM pins O2; both inherit `(s-food, i-burger)` and compete as one target, contrary to proposal §5 "different pinned bases remain separate". | Read |
| R23 | D3 | `selection.py:233-242`, `:298-304` | `_target_node` returns the first node with a matching canonical path from an unordered graph load; the DB allows two nodes in one page to share a canonical path. | A suppress node and a direct addition resolving to the same path → content is suppressed or not depending on heap order. | Read |
| R24 | D4 | `selection.py:776-787` | The Organization "head" claim is not filtered by the observation cutoff O and not checked against the pinned subject in history mode. | History query with O=10:00 returns a head claim observed at 11:00 (ADR-0005 §9). | Read |
| R25 | B2 | `identity/commands.py:539`, `:596-653` | `prior` comes from `session.get`, which can return a stale identity-map object because `current_resolution` is maintained by triggers the ORM does not see. | Within one transaction: re-observe R, human-assign R to S, re-observe R → S is not in the locked set, so the fallback unassigns a valid mapping to `needs_review`. | Plausible |
| R26 | E5 | `test/import_boundaries.py:44-92`; `test/test_schema_layout.py:233-248` | `boundary_violations` has no rule branch for owner `packages.helios_core.gold`, so scanning `helios_core/gold` checks nothing. | Gold importing Menu/Identity ORM or `apps` (ADR-0006 §5/§7) passes CI. Current Gold code is compliant. | **Reproduced** (snippet returned `[]`) |
| R27 | H1 | `test/test_bronze_provenance.py:103-107`, `:342-369`; `test/test_identity_schema.py:1413-1433` | "Rejects DELETE/UPDATE" assertions use `pytest.raises(DBAPIError)` with no `match`/SQLSTATE; for any row with children an FK `RESTRICT` error satisfies them. | Dropping `reject_provenance_mutation` or `reject_history_mutation` leaves most of these tests green; childless rows (a failed Capture, an adjudication-only superseded event) become deletable unnoticed. | Read |
| R28 | H2, A1, B4 | `test/test_identity_schema.py` (absent cases); `alembic/versions/3f8b2c1d9a74_add_shared_identity_foundation.py:779-797` | No failing-case test for: TRUNCATE of the seven Identity history tables (sole guard for leaf tables `resolution_evidence`, `subject_change_member`, `subject_change_evidence`, `applied_subject_change`); mutation of `subject_currentness`/`subject_lineage`; UPDATE/DELETE of `applied_subject_change`; Subject kind immutability; remap `to == from` and remap wrong-`from`. | A regression in `validate_projection_mutation` lets `UPDATE identity.subject_currentness SET is_current = true` un-retire a Subject with CI green. | Read (grep for each message) |
| R29 | H3 | `test/conftest.py:118-124`; `test/test_discovery.py`, `test_url_pipeline.py`, `test_api_venues.py` | Application write paths (`run_discovery`, `resolve_urls`, `seed_sample_venues`) are only tested inside the savepoint fixture, which never fires deferred constraint triggers. | A violation of `ct_subject_exact_typed_grain` / `ct_resolution_event_support` in those paths first fails at the production commit. | Read |
| R30 | H4 | `test/test_identity_concurrency.py:165-172`, `:366-428`, `:589-593`, `:625-629` | Command-path serialization tests count any `DBAPIError` (including `40P01`) as "rejected"; the overlapping-change fixture shares one subject, so a lock-order cycle cannot occur. | A lock-order regression producing deadlocks still passes `sorted(results) == ["committed", "rejected"]`. | Read |
| R31 | E7, D6 | `test/test_gold_catalog.py:166-210`; `test/test_gold_refresh.py:97-242`; `test/test_menu_precedence.py:748-788`, `:900`, `:979-993` | Untested: retired/remapped/pending exclusion from Gold (only `closed`), stale-scope removal between refreshes, Organization-scoped rows, M06 base remap/retire, M08/M12 revival under O with a real predecessor, M12 tie-break (asserts `in {1000, 1100}`), M10 channel-wildcard in selection, M11 different bases, suppression/replacement in selection. | R01–R03 and R22–R24 all sit in these untested branches. | Read |
| R32 | G4 | `url_pipeline.py:141-144`; `resolve_urls.py:36` | `--limit N` always takes the first N Establishments by id, including already-processed ones. | Chunked runs (`--limit 500`, the obvious workaround for R15) never get past venue 500. | Read |
| R33 | G6 | `menu_url.py:163-165`; `url_pipeline.py:262` | Well-known candidates are joined to the site root, discarding the website's path; the registry is keyed by host. | Venues on shared platforms (Toast, Facebook) are all probed at `https://order.toasttab.com/menu`, `https://www.facebook.com/menu`; a 200 assigns the same unrelated URL to all of them. | **Reproduced** (snippet) |
| R34 | G7 | `menu_url.py:27-29`, `:74-80`, `:158`, `:201` | The menu lexicon has false positives and sitemap matches can crowd out homepage anchors under `MAX_CANDIDATES = 8`. | `/menu-of-services`, `/wp-admin/nav-menus.php`, `/food-safety-policy`, "Food Bank Donations" match; ten `/blog/food-post-N` sitemap URLs push out `<a href="/dinner">Dinner Menu</a>`. | **Reproduced** (snippet, by slice G) |
| R35 | G8, H7 | `test/test_web_client.py:20-38`, `:36`, `:61`; `test/test_geo.py:22` | No test exercises the rate limiter (every test sets `min_interval_s=0.0`; `web_client.py:134` never runs), redirects, or robots 401/403/5xx. | A throttle regression or a redirect robots bypass passes CI; ADR-0010 calls etiquette a hard requirement. | Read |
| R36 | G9 | `pipeline.py:207-209` | A POI re-observed and resolved by GERS id is only counted; name/address/coordinate changes never reach Place/Organization, and venues that close or leave Overture are never retired. | Monthly refreshes keep first-seen data forever; `/v1/venues` keeps serving closed venues; dedupe compares against stale coordinates. | Read |
| R37 | F3 | `apps/api/openapi_snapshot.json`; `apps/api/schemas.py:36-41`; `apps/api/routes/venues.py:61`, `:84` | The published OpenAPI documents 422 as FastAPI's `HTTPValidationError`, omits 400/404/500, and never publishes `ErrorResponse` or the `code` enum; the snapshot test locks this in. | A frontend generating its client from `/openapi.json` expects `detail` to be an array and has no typed `code` values (ADR-0008 §4 "stable, documented enum"). | **Reproduced** (snapshot components: `HTTPValidationError, ValidationError, VenueList, VenueResponse`) |
| R38 | F6 | `packages/helios_core/db/session.py:20`; `apps/api/main.py:43-50` | No `connect_timeout`, `pool_timeout`, or `pool_pre_ping`; psycopg's default connect timeout is 130 s and all handlers are threadpool `def`s. | A black-holed DB holds a worker thread per request for ~130 s; the pool of 40 fills and `/healthz` stalls, so the compose healthcheck fails a live process. | Read (psycopg `_DEFAULT_CONNECT_TIMEOUT = 130`); hang Plausible |
| R39 | J1 | `CLAUDE.md:76-77` | The only named exemption to the migration stop-and-ask rule ("the current `Venue` stub") refers to a table dropped by `32700b86d018`. | An agent may treat the real venue Identity tables (9,996 rows on the Pi) as an exempt scaffold. | Read |
| R40 | J2 | `CLAUDE.md:37`; `CONTRIBUTING.md:14-15` | "`make ci` — same as CI" is false: CI also builds the Docker image and runs tests in strict mode against PostGIS; local `make ci` skips DB tests by default. | "`make ci` passed" gets reported as DB acceptance when 446 tests skipped. | Read |

### 5.4 Low

| # | Slice | Location | Summary and failure scenario | Verified |
|---|---|---|---|---|
| R41 | F1 | `apps/api/pagination.py:28-31`; `routes/venues.py:86` | Integers ≥ 2⁶³ in a cursor or path id reach Postgres as `::BIGINT` → `bigint out of range` → 500 `internal_error` instead of 400/404. | **Reproduced** (real PG: both 500) |
| R42 | F2 | `apps/api/main.py:25-31`; `observability.py:63-68`; `errors.py:89-100` | 500 responses bypass the request-id and CORS middleware: no `X-Request-ID`, no `Access-Control-Allow-Origin`, so the browser cannot read the error body or its `trace_id`. | **Reproduced** |
| R43 | F8 | `apps/api/errors.py:82-87` | Every non-404 HTTPException maps to `code: "internal_error"` (405 included) and `exc.headers` is dropped, so 405 has no `Allow` header. | **Reproduced** |
| R44 | F9 | `apps/api/main.py:49-50`; `test/test_healthz.py:41` | `/readyz` 503 body is `{"status": "unavailable"}`, not the ADR-0008 envelope, and the exception is not logged. | **Reproduced** |
| R45 | F10 | `packages/helios_core/config.py:21-23` | `CORS_ALLOW_ORIGINS='["*"]'` is accepted despite "never a wildcard" (credentials off, so exposure is public read data only). | Reproduced (snippet, slice F) |
| R46 | F11 | `apps/api/main.py:25-30` | No `expose_headers=["X-Request-ID"]`, so cross-origin JS can never read the request id. | Read |
| R47 | F12 | `apps/api/errors.py:77`; test client | Deprecated `HTTP_422_UNPROCESSABLE_ENTITY` (removal would turn 422s into 500s); Starlette 1.3.1 deprecates `httpx` for `TestClient` in favour of `httpx2` — the package ADR-0008 called "bogus". Both appear as CI warnings. | **Reproduced** (baseline warnings) |
| R48 | F13 | `apps/api/observability.py:27-46` | Only structlog is configured; uvicorn/stdlib logs (including the re-raised 500 traceback) are unstructured and lack `request_id`. | Read |
| R49 | F14 | `test/test_api_venues.py:26`, `:125-146` | All error-envelope tests require a DB (the client fixture takes `session`), so `make test` without a DB checks none; no 405, header-vs-`trace_id`, 500-header, or overflow tests. | Read |
| R50 | F7 | `apps/api/schemas.py:25-26` | ISO-8601 **UTC** timestamps are not enforced; a DB session with a non-UTC `TimeZone` serializes `-06:00` offsets. Latent (the PostGIS image defaults to UTC). | Read |
| R51 | F4 | `apps/api/routes/venues.py:22-27`; `apps/api/db.py:3-5` | `apps/api` imports Identity ORM models; ADR-0008 §9 says "published contracts/queries only", while ADR-0004 §7's diagram allows `apps -> identity`. ADR conflict for the owner to resolve; no test guards either reading. | Read |
| R52 | C4 | `provenance/contracts.py:227-232` vs `:242-273` | The Source Record is inserted before `canonical_url` is validated, with no savepoint; a caller that catches the `ValueError` and commits leaves an undeletable version-less record. No current caller does. | Read |
| R53 | C5 | `alembic/versions/6344725640bd_add_bronze_provenance_foundation.py:28-37` | Bronze has no `BEFORE TRUNCATE` trigger (Identity and Menu do). Verified protected today only transitively: `TRUNCATE bronze.evidence` → FK refusal; `TRUNCATE bronze.source CASCADE` → `identity.resolution_event is append-only and cannot be truncate`. Untested. | **Reproduced** |
| R54 | C6 | `6344725640bd…:291-296` | Immutability triggers pin only listed columns: `source.kind`, `source_endpoint.endpoint_kind`, `source_record.first_seen_at` remain updatable. | Read |
| R55 | C7 | `provenance/contracts.py:288-309` | The exact-retry key includes `bundle_path` and the locator and has no DB unique constraint; re-running a release with a differently spelled `--release` appends ~10k duplicate versions. | Read |
| R56 | C8, B5, A4 | `provenance/contracts.py:201-212`; `identity/commands.py:52-71`; `3f8b2c1d9a74…:35` | Timezone-naive datetimes, `bool`/`float` confidence, and >5-decimal confidence are accepted; `NUMERIC(6,5)` silently rounds (`0.123456` → `0.12346`). Menu rejects scale explicitly. | **Reproduced** (DB rounding; snippet) |
| R57 | C9 | `url_pipeline.py:115-122` | "Latest" Overture version is chosen by `max(id)`, not `observed_at`; a backfilled older release drives URL resolution. | Read |
| R58 | C10 | `pipeline.py:78`, `:86-87`; `url_pipeline.py:284-285`, `:316-317` | Evidence locators are record keys (`overture:place:{gers}`), not field paths; the excerpt recipe lives only in code. | Read |
| R59 | A2 | `test/test_menu_schema.py:276-277` | The TRUNCATE case accepts `0A000`, so removing `trg_menu_no_truncate` from 8 of 9 FK-referenced tables would go unnoticed. | Read |
| R60 | A3 | `6344725640bd…`; `3f8b2c1d9a74…:445`, `:582`; `b72e6a90c431…:27` | DB checks are looser than Python: `btrim` trims ASCII spaces only (`btrim(E'rule\t') = E'rule\t'`); no CHECK on `source.kind`, `endpoint_kind`, `capture.outcome`; no `isfinite` on Bronze times, and `to_char('infinity')` is NULL, so `capture_business_key` can collide. | **Reproduced** (DB) |
| R61 | B6 | `identity/commands.py:178-194` | `_refresh_subject_readiness` reads without `populate_existing` and refreshes Organizations only; an Establishment's stored `eligible` survives its parent's demotion (admission re-checks, so no hole today). | Read |
| R62 | B7 | `commands.py:338-341` → `identity/contracts.py:66` → `b72e6a90c431…:200-209` | Readiness refresh locks sibling records resolved to the same Organization after the Subject, a second inversion against persist-first re-observation. | Plausible |
| R63 | B8 | `3f8b2c1d9a74…:178-184`; `pipeline.py:197`, `:214` | Organization name CHECK uses ASCII `btrim`; a zero-width-space name survives, and names > 255 chars abort the discovery transaction (`String(255)`). | Read |
| R64 | D7 | `domains/menu/commands.py:79` | Replay orders members by `repr(sorted(row.items()))`; `Decimal("0.1")` vs stored `0.1000` can reorder and raise a false `MenuConflictError`. | Reproduced (snippet, slice D) |
| R65 | D8 | `selection.py:412-414`, `:601` | Canonical business-key tie-break compares `repr` strings (not ascending in general) and content uses a surrogate id, which proposal §5 excludes. | Reproduced (snippet, slice D) |
| R66 | D9 | `domains/menu/commands.py:176-181`; `d83f0a21c592…:556-562` | Replay keys on the version's canonical key while the DB derives `next_revision` from the surrogate version id; once duplicate Bronze versions exist, no correction can be written. | Read |
| R67 | D10 | `selection.py:819-822` | Reports `withdrawn` when any kind's head is a tombstone even if another live head merely lacks the target. | Read |
| R68 | D11 | `selection.py:95-118` | `SelectionRequest`/`ContextRef` unvalidated: a naive `valid_from` silently returns `absent`; a naive `E` raises `TypeError`. | Read |
| R69 | E8 | `gold/refresh.py:48-50` | `staleness_seconds` can be negative (E before `observed_at`) with no CHECK. | Read |
| R70 | E9 | `gold/refresh.py:43-118` | History-mode requests are accepted and written into the "current" table with no mode column. | Read |
| R71 | E10 | `gold/models.py:49-63`, `:146`; `refresh.py:38-40` | The grain unique index includes unbounded `target_path` TEXT (ASCII-escaped JSON) plus `root_key VARCHAR(512)`; deep or non-ASCII paths can exceed the ~2.7 kB btree limit and abort the refresh. | Plausible |
| R72 | G10, H9 | `apps/discovery/registry.py:39-41`, `:60-64`, `:108-113`; `test/test_registry.py:79-82` | Registry `host` is not validated (scheme/port/path pass and never match); a missing registry file silently loads as `{}`, so the "must always parse" test passes if the file is deleted. | Reproduced (snippet, slice G) |
| R73 | G11 | `url_pipeline.py:146-154`, `:314`; `pipeline.py:162-167` | Menu-URL records are per GERS id on per-POI Organizations, not "one per chain" (ADR-0010 decision 3); a deduped Establishment with two Overture records is processed twice. | Read |
| R74 | G12 | `web_client.py:193-203`; `menu_url.py:128-129` | Homepage links resolve against the original URL, not the post-redirect URL, and `<base href>` is ignored; a cross-host redirect drops every homepage link. | Reproduced (snippet, slice G) |
| R75 | G13 | `menu_url.py:151-159`; `web_client.py:198` | Sitemap index children are treated as candidates, `Sitemap:` lines in robots.txt ignored, no `.xml.gz`. | Reproduced (snippet, slice G) |
| R76 | G14 | `url_pipeline.py:98-108` | `_coerce_website` retries garbage with `https://` prepended (`'http:/site.com'` → `https://http/site.com`). | Reproduced (snippet, slice G) |
| R77 | G16 | `test/test_discovery_audit.py:140-142`; `test/fixtures/golden_matches.json` | The golden-set test re-implements the match rule (without the `or name` fallback) instead of calling `_dedupe_candidates`, and the fixture's positives are all pairs the matcher itself merged, so precision 1.000 is largely by construction. | Read |
| R78 | G17 | `apps/discovery/audit.py:336-346` | `"label": "wrong" if check.flagged else "ok"` inside a comprehension filtered by `if check.flagged` — always `"wrong"`. | Read |
| R79 | new | `web_client.py:112-124`, `:150-157` | No response-size cap (`response.text` fully buffered); cache writes are not atomic (a crash leaves corrupt JSON that raises on the next run); transient failures and robots.txt are cached forever. | Read |
| R80 | H5 | `test/test_provider_concurrency.py:254`; `test/test_menu_concurrency.py:376`; Barrier waits in `test_identity_concurrency.py` | Some concurrency tests can hang rather than fail (no `lock_timeout`, untimed `Barrier.wait()`), and CI has no `pytest-timeout` or `timeout-minutes` (6 h default). | Plausible |
| R81 | H6 | `test/test_menu_replay.py:141`; `test/test_menu_schema.py:80`, `:101`, `:585`, `:637`, `:696`, `:743`, `:959` | Menu lifecycle/graph rejections asserted with broad catches (`ck_menu_lifecycle` never named; 6 SQLSTATEs accepted). | Read |
| R82 | H8 | `test/test_legacy_identity_reset.py:429-431`; `test/provider_support.py:56-59` | Restore-to-head in `finally` uses `check=False` (a failed restore misattributes later failures); `migrate()` omits `-c`/`cwd`, so it depends on running from the repo root. | Read |
| R83 | H10 | `test/test_schema_layout.py:250`, `:270-277` | The parser-isolation guard scans a nonexistent `packages/helios_parsing`; the flush-never-commit test omits `gold/refresh.py`. | Read |
| R84 | I2 | `.dockerignore:12-13`, `:27-28`; `infra/Dockerfile:25` | Patterns (`.env`, `__pycache__/`, `*.py[cod]`) match only at the context root; a nested `infra/.env` (compose's default env file for `-f infra/docker-compose.yml`) would be baked into the image. Only the root `.env` exists today. | Read (Docker semantics); compose path Plausible |
| R85 | I3 | `README.md:112`; `.env.example:6`; `config.py:18` | Nothing reads the root `.env` (Settings has no `env_file`; the makefile's compose call has no `--env-file`), yet README says `cp .env.example .env` and `.env.example` says compose reads it. | Read |
| R86 | I4 | `infra/docker-compose.yml:31`, `:42` | `${DATABASE_URL:-…}` interpolates from the operator's shell; an exported localhost URL is passed into containers, `migrate` fails and `api` never starts. | Read |
| R87 | I5 | `infra/Dockerfile:9-10`; `ci.yml:22`, `:40`, `:74`, `:91` | Dockerfile says uv `0.12.0` "matches local and CI"; local is 0.11.7 and CI's `setup-uv@v4` is unpinned, so the required lockfile check runs under a floating uv. | Read |
| R88 | I6 | `makefile:20-21` | `uv lock --check` runs after `uv run` steps that silently re-lock a stale lockfile, so it cannot fail locally (CI still catches it). | Read |
| R89 | I7 | `.github/workflows/ci.yml:1-14` and action refs | No `permissions:` block, actions pinned to mutable major tags, no `timeout-minutes`. | Read |
| R90 | I8 | `infra/Dockerfile:7`, `:10`, `:30`; `infra/docker-compose.yml:8`; `ci.yml:59` | Base/DB images pinned by tag, not digest, including the self-labelled "(test)" PostGIS fork (ADR-0002). | Read |
| R91 | I9 | `mypy.ini:10-31` | Global `strict = True` already applies everywhere; per-module `strict` sections are redundant and the `helios_parsing`/`selectolax`/`overpy`/`h3`/`duckdb` stanzas are dead. | Read |
| R92 | I10 | `ruff.toml:32-33` | Per-file-ignores for unselected `S101`/`PLR2004` and nonexistent `apps/scraper/`; no `S` (bandit) rules at all (e.g. S314 on sitemap XML parsing). | Read |
| R93 | I11 | `.pre-commit-config.yaml:22`; `uv.lock` | Pre-commit ruff `v0.15.12` vs locked ruff `0.15.18`; editor/`uv run ruff format` output can fail the gate. | Read |
| R94 | I12 | `.pre-commit-config.yaml:13-14`, `:44-46` | `check-added-large-files` is a no-op under `--all-files` in CI, and the Conventional Commits hook never runs in CI (squash titles like `Plan 0002 step 06 (#17)` merged unchecked). | Read |
| R95 | I13 | `.github/CODEOWNERS:7` | `/packages/**/db/models/` matches nothing; CODEOWNERS does not flag `db/base.py` (schema allowlist), `db/model_registry.py`, `alembic/env.py`, `.github/workflows/`, or `infra/`. | Read |
| R96 | I15 | `pyproject.toml:2-4`, `:30` | Project named `helios-learning` ("learning/tooling workspace"); `pytest-asyncio` unused; `pydantic`/`starlette` imported directly but undeclared; lower-bound-only pins. Runtime deps otherwise match the approved list exactly. | Read |

### 5.5 Info

| # | Slice | Location | Observation | Verified |
|---|---|---|---|---|
| R97 | F15 | `apps/api/pagination.py:19-33` | Cursor is unsigned base64 of the id and trivially forgeable; harmless (public data, keyset lower bound), but `test_api_pagination.py:17` claims otherwise. | Reproduced (snippet, slice F) |
| R98 | F16 | `apps/api/routes/venues.py:51-58` | Only the Establishment's own currentness is checked; after an Organization/Place merge or retire the venue still shows the retired Organization's name. Provisional Establishments are served (by design, ADR-0009). | Read |
| R99 | F17 | `apps/api/observability.py:54` | Inbound `X-Request-ID` is trusted verbatim as log id, header, and `trace_id`. | Read |
| R100 | F18 | `test/test_openapi_contract.py:19-25` | The snapshot test is strict equality, not a breaking-change check; regenerating the snapshot in the same PR passes it. | Read |
| R101 | C12 | `provenance/contracts.py:286`; `provenance/models.py:147-151` | No server-side ingest timestamp on Capture/Version; for Overture `fetched_at` is the release date at 00:00 UTC. | Read |
| R102 | C13 | `pipeline.py:76`; `url_pipeline.py:183` | `json.dumps(..., default=str)` makes `Decimal("1.5")` and `"1.5"` hash equal; `content_hash` is caller-supplied and never checked against the payload. | Reproduced (snippet, slice C) |
| R103 | A6 | `3f8b2c1d9a74…:1842`; `6344725640bd…:299-338` | These downgrades destroy all Identity/Bronze history without saying so; Identity uses `DROP SCHEMA identity CASCADE`, unlike later migrations' no-CASCADE stance. | Read |
| R104 | A7 | `a466cf4bc4e0…:39-41`, `:316-331` | Legacy downgrade narrows `TEXT` back to `VARCHAR(500)` and pairs `CREATE SCHEMA IF NOT EXISTS` with `DROP SCHEMA IF EXISTS`. | Read |
| R105 | B10 | `identity/commands.py:155-194`; `b72e6a90c431…:106-147` | No application calls `mark_subject_eligible`; Organizations become eligible as a side effect of website assignment, but every discovered Establishment stays `provisional`, so no Establishment-scoped Menu write is possible yet. | Read |
| R106 | B11 | `alembic/versions/91f4c2a7d6e8_fix_typed_grain_update_trigger.py:28-39` | Establishment parent links are immutable in the DB; fixing R98 needs new Establishments plus remaps, not re-pointing. | Read |
| R107 | B12 | `3f8b2c1d9a74…:1024-1047` | Stored `readiness` has no DB guard (INSERT/UPDATE to `eligible` succeed); admission's feature re-check covers it. | Read |
| R108 | D12 | `selection.py` ranking; `d83f0a21c592…:705-709` | Within one kind all contenders share one page, so the ADR-0005 §11 "observation time" rank can never decide; items under the structural `Unsectioned` section have no native path and are never selected or enumerated. | Read |
| R109 | E11 | `gold/refresh.py`; `gold/catalog.py:48` | Byte-identical rebuild holds only for identical caller-supplied E; current mode at a past E still uses today's Identity; the full-table DELETE churns dead tuples each run. | Read |
| R110 | G18 | `apps/discovery/overture.py:25-53`, `:101-125`, `:175` | Fixed category list plus `%restaurant%` (not ADR-0009's "food_and_beverage family"; likely misses e.g. `wine_bar`); coordinates from float32 `bbox`; `INSTALL httpfs` downloads at runtime; pinned `DEFAULT_RELEASE` ages out. | Read |
| R111 | G19 | `apps/discovery/pipeline.py:228-230` | Ambiguous records stay `unresolved` with no review queue; they are recounted every run. | Read |
| R112 | H11 | `makefile` `test`; `ci.yml:84` | Coverage is inflated by test files (96% overall, 91% non-test), migrations and PL/pgSQL are never measured, and there is no `fail_under`. | Reproduced (slice H read `.coverage`) |
| R113 | I14 | `infra/docker-compose.yml`; `apps/discovery/__main__.py:47`; `resolve_urls.py:32` | No volume for `/app/var`; any containerised discovery run loses the geocode and site caches. How the Pi runs discovery is not documented in the repo. | Read (invocation unverified) |
| R114 | I16 | `infra/docker-compose.yml` | No top-level `name:` (project/volume namespace `infra`) and no `restart:` policies, so Pi staging does not survive a reboot. | Read |
| R115 | I17 | `.github/workflows/ci.yml:10-12` | `cancel-in-progress: true` also applies to pushes to `main`, so rapid merges can leave `main` commits without a completed run. | Read |
| R116 | I19 | `infra/Dockerfile`; `ci.yml:118-130` | No image `HEALTHCHECK`; `test/` and `docs/` ship in the image; the smoke test covers `/healthz` only; CI builds amd64 while the Pi builds arm64 locally. | Read |
| R117 | — | git history | No committed secret (§3.5). V1 history (`13e0afd`, reachable from `main`) contains scraped third-party HTML pages with their own tracking tokens; not project credentials. | Reproduced (masked scan) |

## 6. Per-slice notes

**A. Schema & migrations.** Strongest area. Linear chain of nine revisions, single
head `5f3a9c1e7b24`. All 166 Menu, 9 provider and 9 Gold `op.execute` statements
appear verbatim in `docs/reviews/sql/`; the FK matrix holds with every FK
`RESTRICT`/`NO ACTION`; all seven Identity decision tables reject row mutation and
TRUNCATE; all nine Menu tables reject UPDATE/DELETE/TRUNCATE and admit through a
BEFORE INSERT guard; the 15 constraint triggers are `DEFERRABLE INITIALLY
DEFERRED`; the registry covers all 31 tables; `include_object` resolves parent
tables for columns/indexes/constraints. Weaknesses are verification (R10, R28,
R59) and DB checks looser than Python (R56, R60).

**B. Identity.** ADR-0004 §5 transitions and the Subject-change rules (single kind,
cardinality, new split outputs, survivor, no cycles, current inputs, support) are
enforced in the database and tested with `match=`. Python/SQL readiness parity
holds by construction. Issues are lock ordering (R12, R62), a stale-read edge case
(R25), and the fingerprint (R18).

**C. Provenance/Bronze.** Upserts are race-safe (`ON CONFLICT DO NOTHING` +
reselect), exact retries reuse one Capture/Version/Evidence under READ COMMITTED
(tested sequentially and concurrently), A→B→A appends, and Evidence has exactly one
target. The design gap is the overloaded `canonical_url` (R06) and the lack of
failure/rejection capture (R17).

**D. Menu.** Imports only published contracts; `persist_menu` uses a savepoint and
compares whole aggregates on replay; revision forks are blocked by unique
constraints; heads are chosen at K before O filtering. Selection has several
correspondence and lifecycle gaps (R02, R03, R22–R24) that sit in untested
branches (R31).

**E. Gold.** Model and migration are identical; money is BIGINT minor units with a
currency FK; evidence arrays are sorted; DELETE (not TRUNCATE) keeps readers
consistent. The refresh inherits the selector's problems (R01, R02, R19) and adds
per-family bounded semantics (R20) and read-path locking (R21).

**F. API.** Pagination is correct (limit+1, null cursor exactly on the last page,
insert-safe keyset); malformed cursors and bad limits map to 400/422 envelopes;
sessions are per-request and closed; the 9-field projection and `/v1` prefix match
ADR-0008; the live OpenAPI equals the snapshot. Gaps are edge-case status codes and
headers (R41–R44) and the documented error contract (R37).

**G. Discovery.** ADR-0009/0010 identity hazards are respected: `canonical_url` is
`None` everywhere, GERS keys are the external key, dedupe is fingerprint + ≤ 50 m
(inclusive), `yaml.safe_load` is used, sitemap parsing rejects DOCTYPE/ENTITY
payloads, and the category SQL is parameterized. The crawler and URL pipeline carry
most of the High findings (R04, R05, R07, R08).

**H. Tests.** Strict mode really converts every DB skip into a failure; deferred
constraints are fired explicitly where tested; blocking detection polls
`pg_blocking_pids` with deadlines rather than fixed sleeps; committed rows use UUID
tokens. Weaknesses are broad exception assertions (R27, R81), missing guards
(R28), savepoint-only write-path tests (R29), and order dependence (R11).

**I. Infra/CI/tooling.** Five CI job names match CLAUDE.md; the Tests job is
strict; the Docker image is multi-stage, non-root, `--frozen`, and excludes the
root `.env`; compose binds Postgres and the API to 127.0.0.1 and runs migrations as
a one-shot. Gaps are drift gating (R10) and hardening/cleanup (R84–R96).

**J. Docs.** All ADRs carry Status/Date; supersession links match; only two broken
relative links exist. Status text across README, ROADMAP, plans and the retro lags
PRs #18–#21 (§7).

## 7. Doc drift

Grouped by file. "Code wins" per CLAUDE.md; each item is a docs-only fix unless noted.

**CLAUDE.md**
- `:76-77` "the current `Venue` stub" — dropped by `32700b86d018` (R39).
- `:37` "`make ci` … same as CI" — CI also runs Docker and strict DB tests (R40).
- `:43` "`make lint` — ruff check + format" — runs every pre-commit hook incl. mypy
  and `ruff --fix`; also `CONTRIBUTING.md:39`.
- `:44` "mypy --strict on `packages.helios_core.*`" — global strict over the repo
  (`mypy.ini:3`); also ADR-0001:40-41.
- `:71-72` Conventional Commits "enforced" — local `commit-msg` hook only (R94);
  also `CONTRIBUTING.md:24-25`, `ROADMAP.md:978`.

**README.md**
- `:6-12` status dated 2026-09-18, "the API has health endpoints only".
- `:44` 530-test figure; `:70-96` "What's here now" omits `domains/menu/`,
  `geo.py`, `apps/discovery/`, `config/sources.yaml`; `:88` price index "deferred to
  its own ADR" (ADR-0007 exists); `:89-90` `/healthz` + `/readyz` "so far";
  `:100-101` discovery and product API "not" implemented.
- `:109`, `:158` clone URL `github.com/First-Helios/First-Helios`; `git remote` is
  `4Fortune8/First-Helios` (also ADR-0002:20 and the crawler User-Agent at
  `apps/discovery/__main__.py:25`, `resolve_urls.py:24`; a UA contact URL that does
  not resolve would matter for Nominatim's usage policy — not checked offline).
- `:112` `cp .env.example .env` — nothing reads it (R85).

**ROADMAP.md**
- `:13` "Last revised 2026-09-18 … Menu and Gold remain unimplemented"; `:1191`
  "Last updated: 2026-09-17".
- Phase 1 (`:370`, `:477-490`, `:514-524`) still lists accepted work as pending;
  Phase 2 (`:371`, `:602-603`) "Planned" with unversioned `GET /venues`; Phase 4
  (`:710-715`) lists `config/sources.yaml` and menu-URL discovery as remaining.
- Forward ADR numbers: `:606` "ADR-0005: API conventions" (is 0008); `:342`, `:399`,
  `:739` "ADR-0006: Scraper framework"; `:298`, `:309`, `:834` "ADR-0007: Prod
  hosting". Same stale numbers at RFC-0001:294, :297, Plan 0001:203, ADR-0010:164.
- §6.4 ledger (`:996-1007`, `:1034`) has no rows for 0007–0010; "Unassigned | API
  conventions | Planned" is ADR-0008 Accepted; Plan 0002 still "Approved". ADR-0009's
  own drift note (`:278-280`) misquotes the ledger.
- H3 leftovers after ADR-0009 dropped H3: `:58`, `:313-314`, `:800`, `:802`, `:809`,
  `:1111`; RFC-0001:82, :105, :156, :295, :346; Plan 0001:67, :170.
- §4.1 layout (`:160`, `:198-252`, `:675`) shows `identity.py`, `db/models/`,
  `apps/api/tests/`.
- `:982`, `:984`, `:1038` PR template fields, "coverage diff", `chore` issue template
  do not exist; `:1055` `alembic check` "Planned (Phase 1)" (still not in CI, R10);
  `:1057` OpenAPI diff "Planned" (already live); `:1086` compose "Postgres only";
  `:1090` "4 jobs" (five); `:1093-1094` contradictory merge-commit boxes; 530/278 test
  counts at `:484`, `:487`, `:516`.

**ADRs**
- ADR-0001:22 `postgis/postgis` (superseded by `imresamu/postgis`); `:44-45` four CI
  jobs; `:46-49`, `:73-75` web framework "not yet chosen" (closed by ADR-0008).
- ADR-0002:82-84 Docker image "not yet a required status check".
- ADR-0003:146 broken anchor `#phase-1--domain-model--migrations` (heading now ends
  "— IN PROGRESS").
- ADR-0004:426-429 and review guide `:32-35` reference removed
  `db/models/venue.py` and `test/test_venue_identity_schema.py`.
- ADR-0005:3 status "provider implementation remains gated on CI-image PostGIS
  validation" (provider and Menu are merged).
- ADR-0006:5-7 header "full-catalog enumeration deferred" (accepted 2026-09-20 per
  `:224-226`); point 4 `as_of` column (none; `effective_instant` plays the role) and
  a three-value `price_state` (table allows eight); owner decision 4's Organization
  claims "in the same table with explicit scope" (only `organization_claim_count` +
  separate Organization-subject rows).
- ADR-0008:222-223 calls `httpx2` bogus and `httpx` a dev dependency (`httpx` is
  runtime per ADR-0009; Starlette now recommends `httpx2`, R47).
- ADR-0009:114-117 unchanged POI "re-uses its immutable version" (only an exact
  retry does) and locator "parquet release + row" (is `overture:place:{gers}`).
- ADR-0010:72-73 "adds no runtime dependency" (adds PyYAML, `pyproject.toml:14`);
  `:96-98` menu-URL Evidence points at the fetched page (R06); §3 "HEAD/GET" (GET
  only); stop-and-ask list still asks about JSON-Schema.

**Plans, reviews, retro, notes**
- Plan 0001 (`:86`, `:154`, `:158`, `:178`, `:196`): only Step 0 marked done;
  `config/regions.yaml` does not exist.
- Plan 0002 Step 5 proposal (`:5`, `:8`): "No Menu schema or contract is implemented".
- Step-6 reviews (`0002-step-6-gold-read-models.md:44-45`, `:62`;
  `…full-catalog-refresh.md:97`) say the import-boundary test covers Gold (R26); the
  full-catalog review says a broken mapping "yields no rows" (it crashes, R01).
- Retro `2026-09-21-phase-4.md:86-87`, `:131-135`: menu-URL "not built" (PR #21
  built it).
- `docs/HumanDevNotes/MLDataExtractionPlan.md:24` links an absolute local path.
- `LEARNING_GUIDE.md`: `packages/core/`/`packages/parsing/` paths (`:280`, `:282`,
  `:336`, `:387`, `:606`), `docs/adr/0002-session-lifecycle.md`, scraper ADR as
  "ADR-0003" (`:462`, `:493`, `:497-499`), "You won't use triggers in V2" (`:328`),
  H3 (`:606`, `:663-665`).

**Code docstrings and comments**
- `gold/refresh.py:8-9` "Full-catalog enumeration is deferred"; `gold/__init__.py:4-5`
  does not export `refresh_full_catalog`; `gold/models.py:3-4` grain omits
  `source_record_id`/`root_key`.
- `apps/api/seed.py:3-5` "no venue discovery yet"; `apps/api/schemas.py:5` and
  `pagination.py:4-5` claim UTC and non-forgeable cursors (R50, R97).
- `apps/discovery/resolve_urls.py:7-9` "skipped" (R16); `url_pipeline.py:3` "each
  current Establishment" (iterates Overture records); `menu_url.py:10-12`
  "registrable site" (strips `www.` only); `audit.py:10-12`, `:17-18` describe a
  worksheet read-back that no code performs.
- `provenance/contracts.py:275-277` and `identity/commands.py:537-538` lock-order
  comments (R12); `provenance/models.py:74` Capture = "completed source-fetch
  attempt" (R17); `identity/normalize.py:29-38` "de-accent … deliberately
  conservative" (R18); `domains/menu/commands.py:199` replay "without … new writes".
- `test/test_api_pagination.py:17` "cannot trivially forge"; `test_menu_precedence.py:979`
  name claims predecessor revival coverage it lacks.

**Config / templates**
- `.github/pull_request_template.md:16` has no strict-DB / `alembic check` line.
- `.env.example` lacks `CORS_ALLOW_ORIGINS`; `.gitignore:11-15`, `:40` carry V1
  leftovers; `infra/Dockerfile:9` uv-version claim (R87).

## 8. Recommended fix units

Ordered. Each is sized as one reviewable PR. ⚠ marks a CLAUDE.md stop-and-ask path
(models, migrations, dependencies, `infra/`/CI/deploy config, auth/secrets) or a
change to owner-accepted ADR behaviour that needs explicit owner review.

**Hold the next `resolve_urls` run on the Pi until FU-1 and FU-2 land and FU-3 is
decided.** Bronze is immutable, so rows written before those fixes (duplicate
website versions, endpoint-less evidence, wrong menu URLs) can never be cleaned up.

| Order | Unit | Findings | Paths | Flags |
|---|---|---|---|---|
| **FU-1** | **Crawler etiquette and fetch safety.** RFC 9309 robots matching (longest match, `*`/`$`, honour `Crawl-delay`), robots 5xx/unreachable ⇒ disallow, redirect policy (http/https only, re-check robots and throttle per hop or restrict to the same registrable host, reject loopback/link-local/private IPs), response size cap, atomic cache writes, expiring robots/negative cache. Tests with `MockTransport` incl. rate limiting and redirects. | R05, R13, R14, R79, R35, R74 | `apps/discovery/web_client.py`, `test/test_web_client.py` | None if hand-rolled in stdlib. ⚠ Adopting a robots library (e.g. `protego`) is a new runtime dependency. |
| **FU-2** | **URL pipeline correctness.** Respect `needs_review` and skip non-current Organizations; let a registry entry supersede an existing menu URL (needs a decided mechanism: remap vs new observation); skip re-persisting unchanged websites; reject `#`/self/homepage menu candidates and require stronger verification than "200 HTML"; keep the website path for shared platforms; make `--limit` progress; commit per batch. | R04, R07, R08, R15, R16, R32, R33, R34, R72, R73, R76 | `apps/discovery/url_pipeline.py`, `menu_url.py`, `resolve_urls.py`, `registry.py`, tests | None. Registry-supersession semantics touch ADR-0010 §4 — confirm with owner. |
| **FU-3** | **Evidence/endpoint provenance ADR.** Decouple "record where this came from" from "use this URL as an Identity match key"; record failed/rejected fetches with outcome and reason; decide what the ~10k existing endpoint-less rows mean. ADR first, then stop. | R06, R17, R101 | `docs/adr/`, then `packages/helios_core/provenance/contracts.py`, discovery callers | ⚠ ADR + likely contract change; reason codes may need a Capture column (models + migration). |
| **FU-4a** | **Gold refresh survives Identity corrections.** Savepoint (or pre-check) around `_live_scope`; filter heads and candidates by requested subject; `ORDER BY` in `_stream_heads`; make Gold tests rerun-safe and add retired/remapped/pending exclusion tests. | R01, R02, R19, R11, R31 (Gold part) | `domains/menu/selection.py`, `enumeration.py`, `gold/*`, `test/test_gold_*` | ⚠ Changes owner-accepted ADR-0005/0006 selector behaviour; no models/migrations. |
| FU-4b | **Selector semantics.** Content base validity matches price; base identity in canonical paths; deterministic target-node choice; O-filter the Organization head claim; tests for M06/M08/M10–M12, suppression and replacement. | R03, R22, R23, R24, R31 (selector part), R65, R67, R68 | `domains/menu/selection.py`, `test/test_menu_precedence.py` | ⚠ ADR-0005 behaviour; owner review. |
| FU-5 | **Safe DB targeting.** Remove the default `DATABASE_URL` (or refuse the legacy host:port:db), guard write CLIs, make the seed idempotent with canonical fingerprints (or delete it now that discovery exists). | R09 | `packages/helios_core/config.py`, `apps/api/seed.py`, CLI entrypoints | Compose passes `DATABASE_URL` explicitly, so no `infra/` change should be needed; verify. |
| FU-6 | **Merge-gate hardening.** Add `alembic check` (with `compare_server_default=True`) to the Tests job; `permissions: contents: read`; `timeout-minutes`; pin uv; optionally SHA-pin actions and add `pytest-timeout`. | R10, R80, R87, R89, R94, R115 | `.github/workflows/ci.yml`, `alembic/env.py`, `pyproject.toml` | ⚠ CI is the only merge gate; `pytest-timeout` is a new dev dependency. |
| FU-7 | **Identity lock order.** Make re-observation take Subject locks before the Source Record (or the reverse everywhere); fix the comments; add resolve-vs-remap/unassign and sibling-record concurrency tests; `populate_existing` on `prior`. | R12, R25, R62, R30 | `provenance/contracts.py`, `identity/commands.py`, `test/test_identity_concurrency.py` | ⚠ Concurrency-sensitive accepted code; owner review. |
| FU-8 | **Fingerprint normalization.** Keep non-ASCII letters (casefold + NFKC, strip only combining marks), handle `Đ`/`Ø`/`ı` and U+02BC; recompute stored `organization.name_fingerprint`. | R18 | `identity/normalize.py`, `apps/discovery/pipeline.py` | ⚠ Matching-policy change (ADR-0009 §2) plus a data recompute on the Pi. |
| FU-9 | **Test hardening.** SQLSTATE/message-matched rejection assertions; missing Identity guard tests; real-commit tests for discovery/URL/seed write paths; fix concurrency outcome classification; Gold import-boundary rule; hang guards; registry file-exists check. | R26, R27, R28, R29, R30, R59, R81, R82, R83, R49 | `test/` only | None. |
| FU-10 | **API contract polish.** Bound ints (cursor/id) to BIGINT; 500s through request-id/CORS; `expose_headers`; proper 405 code + `Allow`; document `ErrorResponse`/`code` enum in OpenAPI; `/readyz` envelope + logging; DB connect/pool timeouts; UTC serializer; reject `*` origins; replace deprecated constant. | R37, R38, R41–R48, R50 | `apps/api/*`, `openapi_snapshot.json`, `db/session.py` | OpenAPI change is a published-contract change; owner review. |
| FU-11 | **Tooling cleanup.** `.dockerignore` `**/` patterns; compose env handling; image digests; mypy/ruff dead config and version skew; CODEOWNERS paths; rename the project in `pyproject.toml`; declare `pydantic`/`starlette`; drop `pytest-asyncio`. | R84–R86, R88, R90–R93, R95, R96 | `infra/`, `pyproject.toml`, `uv.lock`, `mypy.ini`, `ruff.toml`, `.pre-commit-config.yaml`, `.github/CODEOWNERS` | ⚠ `infra/` and dependency changes. Split into an `infra/` PR and a config-only PR. |
| FU-12 | **Docs drift.** Everything in §7, including the two Medium CLAUDE.md items. | R39, R40, §7 | docs, docstrings | CLAUDE.md is the owner's rulebook — owner review. |
| FU-13 | **Schema tightening (low priority).** Bronze TRUNCATE trigger and full-row immutability; Unicode-aware `btrim`; CHECKs on blank kinds/outcome; `isfinite` on Bronze times; confidence scale checks; Gold `staleness_seconds >= 0`. | R53, R54, R56, R60, R63, R69 | `alembic/versions/`, `**/models.py` | ⚠ Models + migrations. |

**Recommended first fix unit: FU-1 (crawler etiquette and fetch safety).** It fixes
the only High findings with external blast radius (third-party sites, the Pi's
LAN), it gates the next planned operational step (the Pi `resolve_urls` coverage
run), it is confined to `apps/discovery/web_client.py` plus tests, and it touches no
stop-and-ask path if the RFC 9309 matcher is written against the stdlib. If no crawl
is planned soon, start with FU-4a instead: R01 is the only reproduced High.

## 9. Dropped, corrected, and unverified items

- **Corrected:** slice B cited `normalize.py:218-239`; the file is 68 lines — the
  real lines are `:17-18`, `:29-38` (R18). Slice I stated the legacy host service
  was stopped; `127.0.0.1:5432` was listening during this review (R09).
- **Dropped (unverifiable offline):** a claim that the CI Tests job ran 32 minutes
  on 2026-09-21; the documented Pi `docker compose … run --rm` invocation (no such
  text exists in the repo; R113 kept as Info without it).
- **Plausible, not executed:** R19, R25, R62, R71, R80, R84 (compose env path), and
  the hang/deadlock halves of R21 and R38. Each cites a real code path.
- **Not reviewed:** runtime behaviour on the Orange Pi; live Overture/Nominatim/site
  responses; whether the default credentials would authenticate against the legacy
  archive (deliberately not attempted).

## Appendix: reproduction notes

- **R01 / R11.** On any `*_test` DB that has already run the full suite:
  `HELIOS_STRICT_DB_TESTS=1 DATABASE_URL=… uv run pytest test/test_gold_catalog.py`
  → 4 failed (`InFailedSqlTransaction`). Minimal order, verified on a fresh
  container: `pytest test/test_menu_precedence.py test/test_gold_catalog.py` →
  4 failed, 22 passed.
- **R12.** Seed record R resolved to Place S1 plus Place S2 (committed). T1 takes
  `pg_advisory_xact_lock_shared(48454, 2)`, then `SELECT … FROM identity.subject
  WHERE id IN (S1, S2) ORDER BY id FOR UPDATE` (the order `_record_resolution`
  uses). T2 calls `resolve_source_record_observation` for a new observation of R. T1
  then requests `SELECT … FROM bronze.source_record WHERE id = R FOR NO KEY UPDATE`
  → PostgreSQL reports `deadlock detected` and T2 aborts with `40P01`.
- **R53.** `BEGIN; TRUNCATE bronze.evidence; ROLLBACK;` → FK refusal;
  `BEGIN; TRUNCATE bronze.source CASCADE; ROLLBACK;` → `identity.resolution_event is
  append-only and cannot be truncate`.
- **R41.** `GET /v1/venues/99999999999999999999` and
  `GET /v1/venues?cursor=OTIyMzM3MjAzNjg1NDc3NTgwOA==` → 500 `internal_error`.
