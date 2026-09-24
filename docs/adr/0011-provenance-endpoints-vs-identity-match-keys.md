# ADR-0011: Provenance endpoints vs identity match keys

**Status:** Proposed
**Date:** 2026-09-23
**Phase:** 4 (remediation of the 2026-09-22 review, session S5)
**Decides for:** R06, R17, R58, R101; sets the contract S6 implements (plus R52, R55)
**Owner decisions:** D4.1–D4.5 ([remediation checklist](../reviews/2026-09-22-remediation-checklist.md)),
D3.5 carry-over (platform menu URLs)

## Context

[ADR-0004 §4](./0004-modular-monolith-identity-and-lifecycle.md) says Evidence
"retains the Source Endpoint chain needed to recover the original public source
URL", that Captures record fetch attempts, that Evidence uses "a reproducible
locator, such as a field path", and that rejected input "remains Bronze data
with an explicit outcome or reason code". The code at `main@02c534e` meets none
of these for discovery data:

- **One field does two jobs (R06).** `BronzeObservation.canonical_url` is the
  only way to give a Capture a Source Endpoint, and it is also Identity's exact
  URL match key: `source_record_ids_for_canonical_url` returns every record with
  *any* Capture at that endpoint, and `resolve_source_record_observation` assigns
  by it. ADR-0009/0010 therefore force `canonical_url = None` on every
  discovery observation (a shared brand website must never merge locations), so
  no Overture, website, or menu-URL row has an endpoint. The source URL survives
  only inside `source_payload` or the `bundle_path` string.
- **Failures leave no trace (R17).** Every Capture is `outcome="succeeded"`.
  A robots-disallowed site, a 5xx homepage, a site with no menu, or a blank-name
  POI writes nothing, so failures are invisible and every run re-crawls them
  (the D3.9 caveat).
- **Locators are record keys, not field paths (R58).** `overture:place:{gers}`,
  `website:{gers}`, `menu-url:{gers}`; the excerpt recipe (e.g. `name + "\x1f" +
  category`) lives only in pipeline code.
- **No arrival time (R101).** Captures and Versions have no server timestamp;
  Overture's `fetched_at` is the release date at 00:00 UTC.
- Two neighbours S6 fixes under the same contract: the Source Record is inserted
  before its URL is validated, without a savepoint (R52); and the exact-retry key
  includes the raw `--release` glob, so a differently spelled release path
  appends ~10k duplicate versions (R55).

Two schema facts shape the fix:

1. `bronze.source_endpoint.canonical_uri` is **globally unique**, and an
   endpoint belongs to one Source (Capture's composite FK enforces the same
   Source). Recording endpoints for every namespace breaks this at once: the
   Overture and website namespaces both read the same Overture release, and the
   Phase 5 scraper will fetch the pages menu-URL discovery already fetched.
2. Bronze rows cannot be updated or deleted (row triggers); Identity's append-only
   and Identity-owned tables also refuse `TRUNCATE`. The ~10k rows on the Pi can't be fixed in place.

### Owner decisions (D4, 2026-09-23)

- **4.1** Always record where data came from (Source Endpoint); make "match
  identity by this URL" a separate, opt-in field.
- **4.2** Record failed fetches in Bronze with an outcome and reason (migration OK).
- **4.3** Early malformed data may be deleted rather than preserved when keeping
  it adds complexity; before production, do a full purge and rebuild.
- **4.4** Evidence locators become real field paths (e.g. `$.websites[0]`).
- **4.5** Add a server "ingested at" timestamp, in the same migration as 4.2.
- **D3.5 carry-over:** platform menu URLs (Toast, DoorDash, …) should be
  collected even when they duplicate the site's own menu, with the site's own
  menu preferred. ADR-0010 Amendment 3 deferred "can a venue hold several menu
  URLs" to this ADR.

## Decision

Split "where this came from" from "match identity by this URL": every Capture
records a Source Endpoint, while Identity reads only a separate, opt-in match
endpoint stored on the Record Version. Captures also record failed, skipped, and
rejected attempts with a reason code; Evidence locators become JSONPath field
paths whose excerpt hash the contract computes; Bronze gains `ingested_at`.
The Pi database is rebuilt, not migrated.

### 1. The observation contract

`BronzeObservation` (in `packages/helios_core/provenance/contracts.py`) changes:

| Field | Today | After |
|---|---|---|
| `source_url` | — | **Required.** Where the observed bytes were read. Stored as the Capture's Source Endpoint. Never read by Identity. |
| `identity_match_url` | — | Optional, default `None`. The only URL Identity may match on. Must be HTTP(S). |
| `canonical_url` | provenance + match key | **Removed** (split into the two fields above). |
| `endpoint_kind` | caller-supplied, default `"https"` | **Removed**; derived from the endpoint's scheme. |
| `capture_outcome` | free text, always `"succeeded"` | `"succeeded"` only; non-success goes through §4's separate command. |
| `evidence_locator` | free text | A §5 JSONPath into `source_payload`. |
| `evidence_excerpt_hash` | caller-computed | **Removed**; the contract computes it from the locator (§5). |

`PersistedBronzeObservation.canonical_url` becomes `identity_match_url`, and
`source_record_ids_for_canonical_url` becomes
`source_record_ids_for_identity_match_url`.

Identity's URL path keeps its behaviour, but keyed on the match endpoint:

- `source_record_version.identity_match_endpoint_id` (nullable) references a
  `source_endpoint` of the **same Source**. The lookup returns records with a
  Version carrying that match endpoint, **not** records with a Capture there.
  So 10k Overture records that share one release endpoint never match each
  other.
- The `FOR NO KEY UPDATE` serialization lock moves to the match endpoint and is
  taken only when `identity_match_url` is set. The provenance endpoint gets no
  row lock beyond the key-share lock the Capture FK takes, so one shared release
  endpoint doesn't serialize discovery. Lock order otherwise stays as it is
  today (S8 reviews Identity lock order separately).
- URL matching stays within one Source, as it is today: the global
  `canonical_uri` uniqueness already refuses a second Source at the same URL.
- No production caller sets `identity_match_url` after this ADR. ADR-0010's
  registry `location_unique` flag remains the only planned opt-in, and it needs
  its own decision before use.

Every URL in the observation (`source_url`, `identity_match_url`) is validated
and canonicalized **before any insert**, and the whole persist runs inside a
savepoint (`session.begin_nested()`, as `persist_menu` does), so a caller that
catches the error can't commit a half-written record (R52).

### 2. Source Endpoints

- **Unique per Source, not globally:** `UNIQUE (source_id, canonical_uri)`
  replaces `UNIQUE (canonical_uri)`. An endpoint row means "a location this
  Source read". Two namespaces reading the same public location each get their
  own row, which the composite Capture FK requires anyway.
- **Every Capture has an endpoint:** `capture.source_endpoint_id` becomes
  `NOT NULL`.
- **Allowed schemes** (`endpoint_kind` = the scheme, enforced by a CHECK):

  | Kind | Canonical form | Used for |
  |---|---|---|
  | `https` / `http` | `canonicalize_http_url` (unchanged) | fetched web pages |
  | `s3` | `s3://<bucket, lowercased>/<key prefix>/`; glob segments (`*`, `?`, `[`) and everything after them are cut back to the last `/` | Overture release |
  | `repo` | `repo:<relative POSIX path>`; no leading `/`, no `.`/`..` segments | files in this repo, e.g. `repo:config/sources.yaml` |

  A later API may show `http(s)` endpoints as links and may show `s3` endpoints
  as their public HTTPS equivalent. It never shows `repo` endpoints as links; they
  mean "Helios's curated registry".

### 3. What each namespace records

"Where the bytes came from" is the rule. A derived namespace points at its
upstream input, not at the value it asserts: the website namespace never
fetches the website, so recording the website as the endpoint would claim a
fetch that didn't happen.

| Namespace (`source_kind`) | `source_url` (endpoint) | Capture `content_hash` | Capture `fetched_at` | Evidence locator (into the Version payload) |
|---|---|---|---|---|
| `overture` (`poi_snapshot`) | canonical release prefix, e.g. `s3://overturemaps-us-west-2/release/2026-08-19.0/theme=places/type=place/` | hash of the row JSON (as today) | release date (as today, keeps re-runs exact retries) | `$['name','primary_category']` |
| `website-resolution` (`website`), origin `overture` | the same Overture release prefix (its own endpoint row) | the Overture Version's `content_hash` | run time | `$.website` |
| `website-resolution`, origin `registry` | `repo:config/sources.yaml` | SHA-256 of the registry file bytes | run time | `$.website` |
| `menu-url-discovery` (`menu_url`), discovered | the **final fetched URL** of the verified page (after redirects) | SHA-256 of that page's body bytes as received | time of the actual fetch (from the cache entry when replayed) | `$.menu_url` |
| `menu-url-discovery`, registry | `repo:config/sources.yaml` | SHA-256 of the registry file bytes | run time | `$.menu_url` |

- The Overture GERS id stays the record's `external_key`. Endpoint + GERS id
  together identify the source row, so "return the original source" for an
  Overture fact means the release location plus the place id.
- Website payloads gain `derived_from`:
  `{"namespace": "overture", "external_key": <gers>, "locator": "$.websites[<i>]"}`
  (`i` = the Overture website entry used), making D4.4's `$.websites[0]` a
  checkable pointer into the upstream Version. It deliberately holds no
  upstream hash, so a new release that doesn't change the website doesn't write
  a new version (ADR-0010 Amendment 2, R16).
- Menu-URL payloads gain `found_via`: the homepage or sitemap URL that produced
  the candidate, or `null` for well-known paths, platform-hosted websites, and
  the registry. This records ADR-0010 §2's "the fetched page / sitemap that
  yielded it" without a second Capture.
- `bundle_path` is not set by discovery. It stays for a future durable replay
  bundle. The disk cache under `var/` expires after 7 days, so it's not
  evidence. With the release in a canonical endpoint instead of `bundle_path`,
  two spellings of one `--release` produce the same retry key (R55).

### 4. Failed, skipped, and rejected attempts (D4.2)

A Capture is **one acquisition attempt and its outcome**. This replaces the
"completed source-fetch attempt" docstring. New column `capture.reason_code`:

| `outcome` | Meaning | `reason_code` | Version? |
|---|---|---|---|
| `succeeded` | read, produced an observation | `NULL` | yes |
| `failed` | tried, got nothing usable | required | no |
| `skipped` | not fetched because policy forbids it | required | no |
| `rejected` | read, but the input fails validation | required | yes (source-faithful payload), **not** admitted to Identity |

DB CHECKs: `outcome` is one of the four; `reason_code IS NULL` exactly when
`outcome = 'succeeded'`; `reason_code ~ '^[a-z][a-z0-9_]*$'`. The code list
lives in the contract as a `Literal`, not in the DB, so adding a code needs no
migration. Initial codes:

- **skipped:** `robots_disallowed`, `robots_unavailable` (5xx, network error,
  refused redirect), `crawl_delay_too_long`, `non_public_host`,
  `redirect_refused`, `platform_root`
- **failed:** `http_<status>` (e.g. `http_404`, `http_503`), `network_error`,
  `too_large`, `not_html`, `no_menu_found`
- **rejected:** `blank_name`

Recording grain:

- **Menu-URL discovery: at most one Capture per site per attempt**, not one per
  HTTP request. Its endpoint is the canonical website URL that was attempted,
  and its reason is the attempt's overall result (e.g. robots unreachable →
  `skipped/robots_unavailable`; every candidate rejected →
  `failed/no_menu_found`). These rows are site-keyed, so chain locations
  sharing a site share the history.
- **Re-crawl window:** `resolve_urls` doesn't crawl a site whose latest
  menu-URL-discovery Capture there is `failed` or `skipped` and less than
  **20 days** old (a named constant; D4.7). A chunked run spread over days never
  re-crawls, and the next monthly run tries again. This closes the D3.9
  caveat.
- **Overture blank-name POIs:** persisted as a Source Record + Version with a
  `rejected/blank_name` Capture via `persist_source_record_observation`
  directly. They are never passed to Identity, so they sit in Bronze with zero
  resolution events, as ADR-0004 §4 allows.
- **Not recorded:** an Overture website string that `_coerce_website` rejects.
  The raw string is already in the Overture Version, and the run report counts
  it.

New contract command `record_capture_attempt(session, *, source_namespace,
source_kind, source_url, fetched_at, outcome, reason_code, content_hash=None)`
writes a Capture with no Version. A read contract
`latest_capture_at(session, namespace, url)` serves the re-crawl window. A
failure is **never** written as a Record Version, so the saved menu-URL stays
the latest version and D3.7 ("replace only when re-discovery succeeds") holds.

The `skipped` rows also give the D2 follow-up its data: how many sites robots
actually blocks, measured on the first Pi run.

### 5. Evidence locators (D4.4)

A version-targeted locator is a **restricted RFC 9535 JSONPath** into
`source_payload`:

```text
locator  = "$" 1*segment
segment  = "." name / "[" index "]" / "[" quoted *( "," quoted ) "]"
name     = (ALPHA / "_") *(ALPHA / DIGIT / "_")
index    = 1*DIGIT
quoted   = "'" 1*char "'"          ; char excludes "'" and "\"
```

A union (`['a','b']`) is allowed only as the last segment. A locator must select
at least one value. The **excerpt** is the canonical JSON array of the selected
values, in selector order:
`json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`,
and `excerpt_hash = "sha256:" + hexdigest`. The provenance contract evaluates
the path, computes the hash, and refuses a locator that selects nothing, so any
reader can check Evidence with the payload and this paragraph alone. The
evaluator is about 40 lines of stdlib Python, with no JSONPath dependency.

A DB CHECK requires version-targeted locators to start with `$`.
Capture-targeted locators (byte ranges or selectors into fetched HTML) are left
to the Phase 5 extraction ADR.

### 6. `ingested_at` (D4.5)

`ingested_at timestamptz NOT NULL DEFAULT now()` on `capture`,
`source_record_version`, and `evidence`. Evidence is included because
capture-targeted Evidence (Phase 5) can arrive long after its Capture. The value
is the writing transaction's start time, set by the server and never supplied
by callers. It is **not** part of the exact-retry key or any canonical key.
`fetched_at` (when the source was read, or the release date for Overture) and
`observed_at` keep their meanings. The existing immutability triggers already
reject updates to the new columns.

### 7. Several menu URLs per venue (D3.5 carry-over)

**Yes, the provenance contract allows it.** Nothing in Bronze or Identity
limits how many Source Records are assigned to one Subject; only the
menu-URL `external_key` scheme (one key per venue) limits it today. The grain
becomes **one Source Record per (venue, menu source)**:

- `external_key = <gers>` holds the venue's **own-site** menu (signals
  `registry`, `well_known`, `crawled`).
- `external_key = <gers>|<platform host>` (e.g. `…|toasttab.com`) holds one
  record per ordering platform. The payload adds `"platform": "<host>"`. A
  menu URL on a platform host always goes here, including a venue whose
  website is itself a platform page.
- Each record is versioned, assigned, and needs-review-protected on its own,
  exactly as today (ADR-0010 Amendment 2). Chain venues sharing a platform page
  share one endpoint row, which the per-Source uniqueness of §2 allows.
- **Preference is a read-side rule, not an overwrite:** own-site first, then
  platform records by host. It belongs to the Gold `venue_url` projection /
  Phase 5 scraper input (ADR-0010 §2), which carries the signal and platform.
- Social links (Facebook, Instagram, Linktree) and platform roots stay excluded
  (ADR-0010 Amendment 3).

S6 adopts the key rule, so no platform URL is written under a bare `<gers>`
key after S6. Collecting platform links **even when an own-site menu
verifies** is a discovery-logic change, proposed as follow-up session **S6b**
(D4.6). It doesn't gate the Pi run: a run before S6b just collects platform
menus for fewer venues, and a later run adds the rest.

### 8. Existing rows: purge and rebuild (D4.3)

The owner chose deletion over preserving pre-ADR history. The Bronze triggers
block `DELETE`, and Identity's append-only tables block `TRUNCATE`, so the purge is a **database
rebuild**, not row deletion. No trigger is weakened.

- The S6 migration begins with a precondition: if any `bronze.capture` has a
  NULL endpoint, or any version-targeted Evidence locator doesn't start with
  `$`, it raises `ADR-0011: this database holds pre-ADR-0011 Bronze rows;
  rebuild it (see ADR-0011 §8)` and changes nothing. CI databases are empty and
  pass.
- **Pi procedure** (the owner runs it; S6 writes it into the S6 PR body and
  ADR-0009 §3's ops notes, and no agent runs it): stop the stack, remove the
  Postgres data volume, `docker compose up` (the one-shot `migrate` service
  builds the schema at head), then re-run `python -m apps.discovery` and, after
  the Pi gate, `resolve_urls`.
- Consequence: the 9,996 venues are re-minted with **new Subject ids**, and the
  precision-audit worksheet (PR #20) refers to old ids. Re-run the audit on the
  rebuilt data before relying on its numbers.
- The same procedure is the "full purge and rebuild before production" the
  owner asked for. Nothing in this ADR depends on pre-ADR rows surviving.

### 9. Migration shape (S6 writes it; hand-reviewed SQL under `docs/reviews/sql/`)

One Alembic revision, after the precondition in §8:

```sql
-- source_endpoint: unique per Source; scheme-derived kind
ALTER TABLE bronze.source_endpoint DROP CONSTRAINT uq_source_endpoint_canonical_uri;
ALTER TABLE bronze.source_endpoint
  ADD CONSTRAINT uq_source_endpoint_source_canonical_uri UNIQUE (source_id, canonical_uri);
ALTER TABLE bronze.source_endpoint
  ADD CONSTRAINT ck_source_endpoint_kind CHECK (endpoint_kind IN ('http', 'https', 's3', 'repo'));

-- capture: endpoint required; outcome + reason; arrival time
ALTER TABLE bronze.capture ALTER COLUMN source_endpoint_id SET NOT NULL;
ALTER TABLE bronze.capture ADD COLUMN reason_code varchar(64);
ALTER TABLE bronze.capture ADD CONSTRAINT ck_capture_outcome
  CHECK (outcome IN ('succeeded', 'failed', 'skipped', 'rejected'));
ALTER TABLE bronze.capture ADD CONSTRAINT ck_capture_reason_matches_outcome
  CHECK ((outcome = 'succeeded') = (reason_code IS NULL));
ALTER TABLE bronze.capture ADD CONSTRAINT ck_capture_reason_code_format
  CHECK (reason_code IS NULL OR reason_code ~ '^[a-z][a-z0-9_]*$');
ALTER TABLE bronze.capture ADD COLUMN ingested_at timestamptz NOT NULL DEFAULT now();

-- source_record_version: opt-in identity match endpoint; arrival time
ALTER TABLE bronze.source_record_version ADD COLUMN identity_match_endpoint_id bigint;
ALTER TABLE bronze.source_record_version
  ADD CONSTRAINT fk_source_record_version_match_endpoint_source
  FOREIGN KEY (identity_match_endpoint_id, source_id)
  REFERENCES bronze.source_endpoint (id, source_id) ON DELETE RESTRICT;
CREATE INDEX ix_source_record_version_identity_match_endpoint_id
  ON bronze.source_record_version (identity_match_endpoint_id)
  WHERE identity_match_endpoint_id IS NOT NULL;
ALTER TABLE bronze.source_record_version ADD COLUMN ingested_at timestamptz NOT NULL DEFAULT now();

-- evidence: field-path locators for version targets; arrival time
ALTER TABLE bronze.evidence ADD CONSTRAINT ck_evidence_version_locator_jsonpath
  CHECK (source_record_version_id IS NULL OR left(locator, 1) = '$');
ALTER TABLE bronze.evidence ADD COLUMN ingested_at timestamptz NOT NULL DEFAULT now();

-- canonical keys: capture key gains reason_code, version key gains the match endpoint
CREATE OR REPLACE FUNCTION bronze.capture_business_key(...)   -- 'capture-v2'
CREATE OR REPLACE FUNCTION bronze.record_version_info(...)    -- 'version-v2'
```

- `now()` is `STABLE`, so adding the columns doesn't rewrite rows or fire the
  immutability triggers.
- The canonical keys are computed on read (Menu replay comparison, selector
  tie-break strings), not stored, so bumping their version tags changes no
  stored data. S6 confirms that Menu/Gold tests stay green.
- The downgrade reverses each step. It can't restore `NULL` endpoints or global
  uniqueness if post-ADR data violates them, and it fails loudly if so.
- The ORM models (`provenance/models.py`) change to match, and `alembic check`
  must be clean.

### 10. Tests S6 must add (the acceptance for this ADR)

"Return the original source URL on demand": a new read contract
`source_endpoint_for_evidence(session, evidence_id)` walks Evidence →
(Version →) Capture → Endpoint. For **each namespace row in §3**, a test runs
the real pipeline on fixtures and gets back the expected endpoint, kind,
`fetched_at`, and capture hash:

1. Overture: endpoint = canonical release prefix. The locator re-evaluated on
   the payload reproduces `excerpt_hash`.
2. Overture, R55: two spellings of one release glob produce one endpoint and
   exact retries (no new rows).
3. Website from Overture: endpoint = release prefix; `derived_from.locator`
   resolves in the upstream Overture Version.
4. Website from the registry, and menu-URL from the registry: endpoint =
   `repo:config/sources.yaml`; capture hash = the registry file's SHA-256.
5. Discovered menu-URL: endpoint = the post-redirect page URL; capture hash =
   the served body's SHA-256; `fetched_at` = the fetch time.
6. Platform menu: stored under `<gers>|<host>`, with its own endpoint. Two chain
   venues share one endpoint row.
7. Failures: robots disallow, robots 5xx, homepage 503, and no menu found each
   write one `failed`/`skipped` Capture with the right reason and no Version. A
   second run inside the window doesn't crawl that site (fake resolver call
   count). The saved menu-URL stays current.
8. Blank-name POI: `rejected/blank_name` Capture + Version, zero resolution
   events.
9. Decoupling: two records sharing a `source_url` without `identity_match_url`
   are not URL-matched. The existing URL-match tests pass when ported to
   `identity_match_url`, including the concurrency tests.
10. Schema: each new CHECK rejects a bad row. `ingested_at` is server-set and
    excluded from retry detection. The same URI under two Sources gives two
    endpoint rows, and under one Source one row.
11. R52: an invalid URL raises before any insert; Bronze row counts are
    unchanged even if the caller catches the error and commits.
12. Migration: upgrade on a database with an endpoint-less Capture fails with
    the §8 message. Upgrade → downgrade → upgrade works on an empty database.
    The generated SQL byte-matches the committed file.

## Alternatives considered

| Question | Option | Pros | Cons |
|---|---|---|---|
| Split | **Provenance on Capture, opt-in match endpoint on Version (chosen)** | Fixes R06 at the root; Identity semantics and locking unchanged when opted in; match key immutable next to the observation that asserted it | Schema change on Bronze; six test observation helpers (~30 `canonical_url` references) change |
| | Record endpoints, Identity keeps matching on Capture endpoints | No new column | Every Overture record shares one release endpoint and they'd all URL-match: the ADR-0009 collapse hazard |
| | Identity-owned match-key table | Keeps Bronze purely source-faithful | Mutable Silver state separate from the asserting observation; new lock ordering to prove |
| | Drop URL matching entirely | Least code | Against D4.1 (keep it opt-in); the registry `location_unique` flag is its planned user |
| Endpoint uniqueness | **Per Source (chosen)** | Two namespaces can read one location; matches the composite FK | Same URI can appear once per Source |
| | Global (today) | — | Fails as soon as Overture and website both record the release |
| | Source-less endpoints | One row per location | Reworks the composite Capture FK; bigger migration |
| Website endpoint | **Upstream input (chosen)** | True: says where the claim came from | Website URL itself is only in the payload |
| | The website URL (checklist sketch) | One-line rule; clickable | Claims a fetch that never happened; hash isn't of its bytes; collides with platform-hosted menus under global uniqueness |
| Failures | **Capture-only rows with outcome + reason (chosen)** | ADR-0004 already defines Captures as attempts; no new table; site-keyed history | Captures without Versions need their own lookup |
| | Failure Versions | Reuses the record query | Latest version becomes a failure and breaks D3.7 "keep the saved URL" |
| | Separate failure table | Explicit | New table duplicating Capture |
| Locator | **Restricted JSONPath, contract computes excerpt (chosen)** | Checkable from payload alone; no dependency | Not full RFC 9535 |
| | Full JSONPath library | Complete | New runtime dependency for five fixed paths |
| Existing rows | **Rebuild the Pi database (chosen, D4.3)** | No untraceable rows; migration can require endpoints | New Subject ids; audit re-run |
| | Leave as pre-ADR history (original ⭐) | No ops step | Nullable endpoint forever; two provenance regimes to explain |
| Menu URLs per venue | **One record per (venue, menu source) (chosen)** | Independent history, review, and assignment per source; read-side preference | More records per venue |
| | List in one payload | One record | Any change rewrites the whole list; one Evidence for several sources |
| | One URL, platform as fallback (today) | Simple | Loses platform menus the owner wants |

## Consequences

- **Every Bronze row can answer "where did this come from"** through one walk,
  for every namespace. Identity can no longer collapse records by accident,
  because nothing it reads is set by default.
- **Failures become data:** dead and robots-blocked sites stop being re-crawled
  every run, and the robots follow-up gets real numbers.
- **Harder:** a ⚠ migration on existing Bronze tables (S6 stops for review), a
  contract signature change across both discovery pipelines and six test
  observation helpers (~30 `canonical_url` references), and a Pi
  rebuild that re-mints every venue id.
- **New conventions to learn:** the `s3` and `repo` endpoint schemes (`repo` is
  Helios-specific), the reason-code list, and the JSONPath subset.
- **Chain venues multiply records, not endpoints:** 50 locations sharing one
  menu page are 50 records and 50 Captures pointing at one endpoint row.
- Menu selector tie-break strings change with the key version bump. Ordering
  stays deterministic, and no stored data changes.

## For review (owner)

- **D4.6** When to collect platform menus alongside an own-site menu: follow-up
  **S6b** (⭐; S6 only adopts the `<gers>|<host>` key rule) or inside S6.
- **D4.7** Re-crawl window after a failed/skipped attempt: ⭐ 20 days, or another
  value.
- The `repo:` scheme for registry-origin rows, and the website endpoint being
  the upstream Overture release rather than the website itself (a deliberate
  departure from the checklist's S5 sketch, see §3).

## References

- [2026-09-22 review](../reviews/2026-09-22-full-codebase-review.md) R06, R17,
  R52, R55, R58, R101, FU-3; [remediation checklist](../reviews/2026-09-22-remediation-checklist.md) D4, S5, S6
- [ADR-0004](./0004-modular-monolith-identity-and-lifecycle.md) §4 provenance, §5 Evidence chain
- [ADR-0009](./0009-venue-discovery-source-dedupe-and-schedule.md) §1 and "A concrete hazard"
- [ADR-0010](./0010-website-and-menu-url-resolution.md) §2 and Amendments 2–3
- [RFC 9535](https://www.rfc-editor.org/rfc/rfc9535) JSONPath
- On acceptance, S6 adds amendment pointers to ADR-0004 §4 (Capture meaning),
  ADR-0009 §1 (Overture locator/`bundle_path`), and ADR-0010 §2 (persistence,
  menu grain).
