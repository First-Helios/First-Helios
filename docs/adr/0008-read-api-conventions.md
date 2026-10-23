# ADR-0008: Read-API framework and conventions (First Light)

**Status:** Accepted — Unit A (venues read endpoints); Unit B (staging deploy)
not built, a separate reviewed unit
**Date:** 2026-09-20
**Accepted:** 2026-09-20 by the owner (Unit A); all four open conventions
confirmed as-implemented, see [Owner decision](#owner-decision)
**Amended:** 2026-09-23 — error `code` enum, `/readyz` envelope, CORS/timeouts/
request-id hardening, see [Amendment 1](#amendment-1-2026-09-23-api-polish)
(review session S9; owner decisions D7)
**Amended:** 2026-09-28 — the API may read Identity ORM models directly, see
[Amendment 2](#amendment-2-2026-09-28-api-reads-identity-models-directly)
(review session S16; owner decision D6.5)
**Amended:** 2026-10-21 — accepted history is read through the Menu selector's
history mode, see [Amendment 3](#amendment-3-2026-10-21-history-reads-through-the-menu-selector)
(session P7-1; [ADR-0018](./0018-venue-filters-and-item-price-history.md) Q9)
**Amended:** 2026-10-22 — `source_url` on each menu, read at request time through the
provenance contract, see [Amendment 4](#amendment-4-2026-10-22-source_url-on-each-menu)
(session P8-6; [ADR-0019](./0019-public-v1-site.md) §5 step 4)
**Amended:** 2026-09-28 — venue lifecycle filtering, see
[S13 section](#s13-venue-lifecycle-filtering-2026-09-28) ([ADR-0012](./0012-venue-lifecycle.md) §3–§4)
**Closes:** the web-framework deferral in
[ADR-0001](./0001-stack-choice.md) ("Web framework (Phase 7+): not yet chosen in
code … reaffirmed or revised in a dedicated ADR once `apps/api/` exists").
**Extends:** [ADR-0004](./0004-modular-monolith-identity-and-lifecycle.md) (module
boundaries), [ADR-0006](./0006-gold-menu-read-models.md) (Gold read models).
**Implements (proposes):** [ROADMAP Phase 2 — First Light](../../ROADMAP.md#phase-2--first-light-read-api--staging-deploy),
[RFC-0001 work-plan PR 4](../rfc/0001-menu-pricing-first.md).

> **ADR-number drift (flagged per CLAUDE.md "the code wins").** ROADMAP Phase 2
> forward-references "**ADR-0005:** API conventions", and Phase 5 references
> "**ADR-0006:** Scraper framework choice". Both numbers were assigned by
> creation order to other decisions — **0005 = immutable Menu snapshots**,
> **0006 = Gold menu read models**. This API-conventions ADR therefore takes the
> next free number, **0008** (0007 = the price index). The scraper-framework and
> prod-hosting ADRs take the next free numbers when written. This ADR does not
> renumber anything; it records the divergence for the owner to reconcile in
> ROADMAP.
> *Resolved in S16 (2026-09-28): ROADMAP no longer carries planned ADR numbers;
> [README.md](../../README.md#decisions) is the ADR index.*

## Context

Phase 1 is complete and merged: Bronze provenance, shared Identity
(Place/Organization/Establishment), the immutable Menu graph and selector, and
the Gold `gold.current_menu` read model with its bounded and full-catalog
refreshes. `apps/api/` currently exposes only `GET /healthz` (liveness) and
`GET /readyz` (DB ping); there is **no read endpoint over any domain data**, and
no venue is seeded (discovery is Phase 4).

Phase 2 "First Light" is the thinnest real end-to-end slice: one read-only
resource served from Identity/Gold, deployed to staging. Its explicit purpose is
to **prove the DB → API → deploy path once, early, and to establish the API
conventions every later endpoint inherits** (the full price-index API is
Phase 7). Because those conventions are inherited system-wide, they are worth
settling in one ADR before the first route exists — exactly what ADR-0001
deferred until now.

**What is already settled and not reopened here:**

- The API is **read-only, no auth** in V1; CORS is locked to the single
  frontend origin (ROADMAP §2, §4.4).
- **Cursor-based pagination, not offset** (ROADMAP §4.4: "O(1) at any page").
- **Uniform error shape** `{detail, code, trace_id}` (ROADMAP §4.4).
- **OpenAPI published at `/docs`, schema at `/openapi.json`, diffed in CI for
  breaking changes** (ROADMAP §4.4, Phase 7).
- Wire format is a contract: **Pydantic response models separate from ORM**;
  SQLAlchemy objects never leak to the wire (ROADMAP Phase 2).
- Money is integer currency minor units, never float; freshness (`as_of`,
  staleness) is surfaced in the wire, not hidden (ROADMAP Phase 7, ADR-0006).
- `apps/*` compose modules via **published contracts** and may read `gold`,
  `domains.menu`, `identity`, `provenance`; they never reach through a module to
  its ORM (ADR-0004 §2, §7).

**What is not settled, and is why this ADR exists:**

- **The web framework is ratified only in code, not by ADR.** FastAPI +
  `uvicorn` already ship (`apps/api/main.py`, `pyproject.toml`), but ADR-0001
  explicitly left the ratification to "a dedicated ADR once `apps/api/` exists,
  since it's a bigger surface than a one-line ratification covers." This is that
  ADR.
- **What "a venue" *is* on the wire** now that the `venue` table is gone
  (ADR-0004 replaced it with Place/Organization/Establishment). The resource,
  its id, and its fields must be defined against the real identity grains.
- **Concrete forms of the settled principles:** the cursor encoding and its
  ordering key; the page-size default and cap; the `code` vocabulary and the
  404-vs-empty-list rule; the **versioning scheme** (URL prefix vs header vs
  none yet); and whether First Light includes any menu data or venues-only.
- **Two additive dependencies/config Phase 2 needs:** `structlog` is **not yet a
  dependency** (only `fastapi`/`pydantic`/`uvicorn`/`httpx2` are), and
  `config.py` has only `database_url` — CORS origins need a new setting. Adding a
  logging library is a new runtime dependency (CLAUDE.md stop-and-ask, though a
  library, not a service); the staging systemd/deploy work touches `infra/`
  (CLAUDE.md stop-and-ask).

Per CLAUDE.md, these are proposed here and stopped for owner review before any
route, model, config, dependency, or deploy change.

## Decision (proposed)

Ratify FastAPI + Pydantic v2 as the API stack and adopt the conventions below as
the contract every read endpoint inherits. Implement nothing until the owner
accepts; then First Light ships one venue resource under these rules.

1. **Framework — ratify FastAPI + Pydantic v2 + uvicorn.** Reaffirms ADR-0001's
   roadmap target now that `apps/api/` is real. Rejected alternatives
   (Flask/Litestar/Django) in the table below. This closes ADR-0001's deferral.

2. **The "venue" resource is a projection of `identity.establishment`.** A venue
   on the wire is an Establishment (an Organization operating at a Place):
   `id` = the Establishment's `subject_id`; fields drawn from the joined
   Organization (`canonical_name`, `organization_kind`) and Place (`address`,
   `latitude`, `longitude`), plus `operating_status` and the effective interval.
   Place and Organization are **not** separately addressable resources in
   First Light. **Review surface:** the exact field list, and whether closed /
   non-operating Establishments appear (proposed: included, with
   `operating_status` surfaced, never silently hidden — mirrors the freshness
   principle).

3. **Pagination — opaque cursor over a stable total order.** `GET /venues`
   returns `{items: [...], next_cursor: str | null}`. The cursor is an opaque
   base64 token encoding the last row's ordering key over a **stable, unique**
   sort (proposed: `subject_id` ascending), so pages are O(1) and insert-safe.
   `?limit=` with a **default 50, hard cap 200** (review surface: the numbers).
   Offset pagination is rejected (O(n) deep pages, drift under writes).

4. **Error shape and 404 semantics.** Every non-2xx body is
   `{detail: str, code: str, trace_id: str}`. `code` is a **stable, documented
   enum** (proposed initial set: `not_found`, `validation_error`,
   `invalid_cursor`, `internal_error`) — clients switch on `code`, never on
   `detail` prose. **A missing single resource is `404 not_found`; an empty
   collection is `200` with `items: []`** — absence of one is an error, absence
   of many is a valid empty result.

5. **Wire contract conventions (inherited by every endpoint).** Pydantic v2
   response models live in `apps/api` (e.g. `apps/api/schemas/`), separate from
   ORM; no SQLAlchemy object is ever serialized directly. Field names are
   `snake_case`. **Money is an integer `amount_minor` plus a `currency_code`**,
   never a float or a formatted string. **Timestamps are ISO-8601 UTC.** Any
   priced or time-sensitive payload carries **`as_of`** and a staleness age
   (ADR-0006, ROADMAP Phase 7). Enums are serialized as their string value.

6. **Versioning — URL prefix `/v1` (review surface).** All domain routes mount
   under `/v1` (`/v1/venues`); `/healthz` and `/readyz` stay unversioned
   operational endpoints. Proposed over header-based versioning for
   cache/proxy/debuggability simplicity. The OpenAPI schema is served at
   `/openapi.json`, docs at `/docs`, and a **committed schema snapshot is diffed
   in CI so breaking changes fail the build** (ROADMAP §4.4).

7. **Observability — `structlog` with per-request IDs.** Add `structlog` (new
   runtime dependency — owner approval required): JSON logs in staging/prod,
   human-readable in dev, a middleware assigning a request id that becomes the
   `trace_id` returned in error bodies. Cheap now, painful to retrofit under
   traffic (ROADMAP Phase 2).

8. **CORS and settings.** Add a `cors_allow_origins` setting (default: the single
   frontend origin, configurable) to `config.py`; no wildcard. **No auth, no
   rate limiting** in this phase (ROADMAP §2; Phase 8).

9. **Module boundary.** `apps/api` reads via published contracts/queries from
   `identity` and `gold` only; it holds no ORM write path and no business logic
   beyond shaping the wire model. A read that needs current menu content uses
   `gold.current_menu` (already the accepted read model), never the Menu selector
   or raw observations directly.

10. **Explicit non-goals of this ADR / First Light.** No auth, rate limiting,
    TLS, public domain, or hosted prod (Phase 8); no price index or aggregate
    endpoints (Phase 7, ADR-0007 deferred); no write API; no discovery, scraper,
    extraction, or ML; no new service dependency (queue/cache/search). The
    staging systemd/deploy specifics land as their own reviewed unit under
    `infra/` (CLAUDE.md stop-and-ask), not silently inside the API PR.

## Alternatives considered

| Option | Pros | Reason not proposed |
|---|---|---|
| **Flask / Litestar / Django REST** instead of FastAPI | Flask familiar; Litestar fast; DRF batteries-included | FastAPI already ships and works; Pydantic v2 + OpenAPI are native; ADR-0001 already targeted it. Switching is churn with no gain; Django couples data layer to a framework ADR-0001 rejected. |
| **Offset/limit pagination** | Trivial `LIMIT/OFFSET`; jump to any page | O(n) deep pages and result drift under concurrent writes; ROADMAP §4.4 explicitly chose cursor. |
| **Header/media-type versioning** (`Accept: …;v=1`) | No URL churn across versions | Harder to cache, proxy, curl, and read in logs; URL prefix is simpler for a small read API and can coexist with headers later. |
| **No versioning yet** | Less scaffolding now | The wire is a cross-repo contract with a separate frontend; a version prefix is cheap insurance against a breaking change with no migration path. |
| **Serialize ORM models directly** (`from_attributes`) | Less boilerplate | Leaks schema into the contract; a column rename becomes a silent breaking API change. ROADMAP Phase 2 mandates separate response models. |
| **Expose Place/Organization as first-class resources now** | More RESTful surface | First Light is deliberately one resource; more resources = more contract to freeze before there is data. Additive later. |
| **`print`/stdlib logging instead of structlog** | No new dependency | No structured fields or request-id correlation; retrofitting logging under traffic is the exact pain Phase 2 calls out. |

## Consequences

**Easier**

- Every later endpoint (price index, menu, price-history in Phase 7) inherits a
  settled pagination/error/versioning/money/freshness contract instead of
  re-deciding per route.
- The DB → API → deploy path is proven once, early, against a real deployment,
  de-risking every later phase (ROADMAP Phase 2 rationale).
- A committed OpenAPI snapshot + CI diff turns "breaking change" into a build
  failure, not a frontend surprise.

**Harder / accepted costs**

- Two additive dependencies/config to approve: `structlog` (library) and a
  `cors_allow_origins` setting; plus the `infra/` staging-deploy unit
  (stop-and-ask), which is real ops work, not code.
- Cursor pagination is more code than offset (opaque token encode/decode,
  stable-order guarantee) — the accepted trade for correctness at depth.
- Defining "venue" as an Establishment projection means a venue with no resolved
  Organization or Place is either excluded or partially null; the field-nullability
  policy (Decision point 2) must be deliberate, not incidental.
- First Light serves seeded/fixture data (no discovery yet); the endpoint is real
  but the catalog is not — honest, and the seed command is a Phase 2 deliverable.

## Owner decision

**Accepted by the owner on 2026-09-20.** Unit A (venues read endpoints) was first
built under delegated design authority ("continue … For design constraints you are
to trust your best judgment … keep all work on this branch for later review")
while the owner was away, held on branch `feat/phase-2-first-light` with nothing
pushed, merged, or deployed. On 2026-09-20 the owner conducted the explicit review
that delegation deferred and **confirmed all four open conventions
as-implemented** (field list + closed-venue visibility; 50/200 page size; `/v1`
versioning; the `structlog`/`httpx`/`cors` dependency and config changes). This
section now records that owner disposition, not merely the delegated build.

**Choices made (the review surface — accept, amend, or revert):**

1. **FastAPI + Pydantic v2 ratified** (closes ADR-0001's deferral).
2. **"Venue" = current `identity.establishment` projection**: `id` = establishment
   `subject_id`; fields = Organization `canonical_name`/`organization_kind`,
   Place `address`/`latitude`/`longitude`, `operating_status`, effective interval.
   **Only current (non-retired) Establishments are served** (join
   `subject_currentness.is_current`); closed venues **are** shown with
   `operating_status` surfaced (not hidden). Place/Organization are not separate
   resources yet.
3. **Conventions:** opaque base64 cursor over `subject_id`; page default **50**,
   hard cap **200**; error `code` set `{not_found, validation_error,
   invalid_cursor, internal_error}`; **404 for a missing single, 200 `[]` for an
   empty collection**; **`/v1`** URL versioning (`/healthz`,`/readyz` unversioned).
4. **Additive dependency/config added:** `structlog` (runtime) + request-id
   middleware; `cors_allow_origins` setting (default `http://localhost:5173`).
   Also replaced the unused/bogus `httpx2` dev dependency with real `httpx`
   (needed by FastAPI's `TestClient`) and added `pydantic.BaseModel` to ruff's
   runtime-evaluated base classes.
5. **Staging deploy (Unit B) deliberately NOT done:** `infra/` systemd/runbook is
   a hard CLAUDE.md stop-and-ask and needs the Orange Pi host — left for a
   separate reviewed unit.

**Owner disposition (2026-09-20) — all accepted as-implemented:**

1. Venue field list and closed-venue visibility (2): **accepted** — the 9-field
   projection stands; only current (`is_current`) Establishments are served and
   closed venues remain visible with `operating_status` surfaced, not hidden.
2. Page-size default/cap and versioning (3): **accepted** — `50` default, `200`
   hard cap, and the `/v1` URL prefix stand.
3. Dependency and config changes (4): **accepted** — `structlog` (runtime),
   `httpx` replacing the bogus `httpx2` (dev), and the `cors_allow_origins`
   setting (default `http://localhost:5173`) all approved.

Green tests, CI, or the presence of this document are **not** owner acceptance
(CLAUDE.md; ADR-0006/0007 precedent); this disposition is that explicit owner
acceptance, recorded here rather than inferred from the passing build.

## Amendment 1 (2026-09-23): API polish

The 2026-09-22 codebase review (R37, R38, R41-R50, R99) found several gaps
between this ADR's conventions and the shipped code. Owner decisions D7
(remediation checklist) settle:

- **Error `code` enum grows by two** (D7.1). The set in Decision point 4 above
  was `{not_found, validation_error, invalid_cursor, internal_error}`; it is
  now `{not_found, validation_error, invalid_cursor, method_not_allowed,
  service_unavailable, internal_error}`. A `405` reports `method_not_allowed`
  (with an `Allow` header) instead of `internal_error`; any other unmapped 4xx
  reports `validation_error` instead of `internal_error`; a `/readyz` failure
  reports `service_unavailable` (next point).
- **`/readyz` returns the standard envelope** (D7.2), not the ad hoc
  `{"status": "unavailable"}` body: `503 {detail, code: "service_unavailable",
  trace_id}`, and the failure is logged.
- **CORS never accepts a wildcard** (D7.3): `CORS_ALLOW_ORIGINS` containing
  `"*"` now fails Settings validation at startup instead of being silently
  accepted. `expose_headers=["X-Request-ID"]` was also added, so cross-origin
  JavaScript can read the header the ADR already promised in error bodies as
  `trace_id`.
- **DB connect/pool timeouts** (D7.4): `connect_timeout=5s`, `pool_timeout=10s`,
  `pool_pre_ping=True` on the engine, so a black-holed database fails fast
  instead of holding a worker thread per request for psycopg's ~130s default.
- **Inbound `X-Request-ID` is validated, not trusted verbatim** (D7.5): only
  ≤64 characters from `[A-Za-z0-9._-]` are echoed back; anything else (oversize,
  control/CRLF characters) is replaced with a freshly minted id.
- **Unhandled exceptions are caught by the request-id middleware itself**, not
  an app-level `Exception` handler, so a `500`'s response still carries
  `X-Request-ID` and CORS headers (previously it carried neither: FastAPI
  routes a bare `Exception` handler through Starlette's `ServerErrorMiddleware`,
  which sits outside every user middleware).
- **Overflowing ids/cursors are rejected, not 500'd.** `venue_id` and a decoded
  cursor are bounded to the Postgres `BIGINT` range (`400`/`422`), instead of
  reaching a `::BIGINT` comparison and raising a driver error.
- **The published OpenAPI documents the real contract**: every route declares
  `responses=` with `ErrorResponse` (not FastAPI's default
  `HTTPValidationError`/`ValidationError`), and `code` is a Literal enum in the
  schema. The committed snapshot was regenerated; see PR for the diff.
- **Timestamps are enforced UTC on the wire** regardless of the DB session's
  `TimeZone` setting, via an explicit serializer rather than relying on server
  configuration.
- **Left alone:** the `httpx` → `httpx2` TestClient deprecation warning
  (Decision point 4's `httpx2` note was already reversed in the owner
  disposition below; `httpx2` is not a real, usable replacement — swapping
  back was out of scope for this session and is not a one-line change).

## Amendment 2 (2026-09-28): API reads Identity models directly

Review finding R51: Decision point 9 says `apps/api` reads "via published
contracts/queries" only, while [ADR-0004 §7](./0004-modular-monolith-identity-and-lifecycle.md)'s
import diagram allows `apps -> identity`. The shipped routes import
`Establishment`, `Organization`, `Place` and `SubjectCurrentness` from
`packages/helios_core/identity/models.py` (`apps/api/routes/venues.py`). Owner
decision D6.5 (remediation checklist) settles it in ADR-0004's favour:

- A read-only app (`apps/api`) may import Identity ORM models directly to query
  them. `apps` is the composition root (ADR-0004 §7).
- This covers reads only. `apps/api` has no write path: its session is never
  committed (`apps/api/db.py`) and it adds no rows. Changes to which Subject a
  record belongs to go through Identity commands
  (`packages/helios_core/identity/commands.py`), as ADR-0004 §8 and
  [ADR-0012 §1](./0012-venue-lifecycle.md) require.
- Pydantic response models stay separate from the ORM (Decision point 5): no
  SQLAlchemy object reaches the wire.

## Amendment 3 (2026-10-21): history reads through the Menu selector

Decision point 9 says a read of current menu content uses `gold.current_menu`,
never the Menu selector. It says nothing about history, and Gold holds current
answers only ([ADR-0006](./0006-gold-menu-read-models.md) owner decision D5.3).
The owner accepted [ADR-0018](./0018-venue-filters-and-item-price-history.md)
Q9 on 2026-10-21, and this amendment records it:

- Current menu content is still read from Gold only. Nothing changes for
  `GET /v1/venues/{id}/menu` or `GET /v1/price-index`.
- Accepted price history (`GET /v1/items/{item_id}/price-history`) is read from
  Menu through the selector's history mode (`select_price` with a knowledge
  cutoff, ADR-0005 §9). The read is a pure function in
  `packages/helios_core/domains/menu/`, beside `enumeration.py`. It reuses the
  selector's correspondence helpers and re-implements no precedence. The route
  calls that function. It does not loop over `select_price` itself, and it runs
  no raw Menu SQL.
- The read path stays read-only, as Amendment 2 already requires.

## Amendment 4 (2026-10-22): `source_url` on each menu

**Status: Accepted 2026-10-22 by the owner (see
[Owner decision](#owner-decision-amendment-4)); built 2026-10-22, session P8-6, no migration (see
[Build notes](#build-notes-amendment-4)).** It is [ADR-0019](./0019-public-v1-site.md) §5 build
step 4, minus `rate_limited`, which ADR-0019's owner decision moved to step 7.

### The gap

ADR-0019's v1 is done when a reader can "read a venue's menu with section headings, prices,
observation dates and a link to the source page". `GET /v1/venues/{id}/menu` serves no link.
The URL exists only in Bronze: each `gold.current_menu` row carries `price_evidence_ids`, the
Bronze Evidence behind its selected price, and each Evidence reaches a Capture whose Source
Endpoint is the fetched page. Gold stores no URL, and the API never reads Bronze.

### Shape

- **Wire.** `MenuResponse` gains `source_url: str | None`: one URL per menu (per family:
  subject kind, subject, source record, root key). Not per price, and not a list. Additive:
  no other field changes.
- **Value.** The canonical URI of the Source Endpoint of the family's **most recent price
  Evidence**, resolved through the provenance contract's Evidence → Capture → endpoint rule
  (`source_endpoint_for_evidence`: a Version-targeted Evidence reaches its Version's Capture,
  a Capture-targeted one its own).
- **"Most recent", precisely.** Over every served row of the family and every id in its
  `price_evidence_ids` that reaches a Capture, the greatest key
  `(price_observed_at, Capture fetched_at, Evidence id)`. A null `price_observed_at` sorts
  lowest. Ties on the observation instant go to the later fetch, then to the greater Evidence
  id. That last step is arbitrary, but it is deterministic and stable across a `pg_dump`
  restore, which preserves ids.
- **Null cases.** `source_url` is null when no Evidence id of any of the family's rows reaches
  a Capture: the rows cite no price Evidence, or only ids that are unknown or belong to a legacy
  Version with no Capture. An unresolvable id is skipped rather than failing the request, so the
  next most recent Evidence wins.
- **Where it is read.** At request time, with no migration and no Gold column. The batched
  contract `source_endpoints_for_evidence` (`packages/helios_core/provenance/contracts.py`) is
  the single-id lookup's rule for many ids in one query. An id that does not resolve is left out
  of its result instead of raising. `menu_source_urls`
  (`packages/helios_core/gold/menu_read.py`) applies the "most recent" rule. The route calls
  the Gold read. So `apps/api` still reads through `identity` and `gold` only (Decision
  point 9); the Gold read module calls the published provenance contract, as
  `gold/price_index.py` already does.
- **One Evidence per page.** Every price Evidence of one Menu page cites that page's own
  Capture. So `menu_source_urls` groups a family's rows by `price_page_id` and resolves only
  each page's leader, its greatest `(price_observed_at, Evidence id)`. That is one or two ids
  per family instead of every price's Evidence. The result is the rule above exactly, as long as
  that invariant holds: within one Capture, the fetch time is the same for every Evidence. A page
  whose leader does not resolve has all its Evidence resolved in a second query, so the
  skip-unresolved rule still holds. A row with no `price_page_id` is resolved Evidence by
  Evidence.
- **Query count.** One more statement per menu request, whatever the number of families or
  prices: the current venue, its Organization's current peers, the Gold rows, then one
  provenance read. A second provenance read happens only when some page's leader does not
  resolve. A venue with no rows makes no provenance read.

### Tests and done-when

- *Tests* (`test/test_api_venue_menu.py`, `test/test_evidence_endpoints.py`, synthetic, no
  network): a multi-page family serves its most recent page's URL; the fetch-time and Evidence-id
  tie-breaks each decide a case; an unresolvable newest Evidence is skipped; a family with no
  resolvable Evidence serves null; an Organization-scope menu carries its own record's URL; the
  request makes four statements whether it serves one price or eighty over two families, and
  only the last reads `bronze.evidence`; the provenance read has an index path on every table it
  joins (planned with sequential scans priced out); the batched contract equals the single
  lookup for Version- and Capture-targeted Evidence and omits ids the single lookup rejects;
  with a fake lookup, two pages of 50 and 3 prices send exactly their two leaders, and a page
  whose leader does not resolve sends its other Evidence in a second call. The OpenAPI snapshot
  is regenerated (additive).
- *Done when,* through a local read-only API over `helios_laptop`: every `has_menu` venue's
  menus carry `source_url`, with each null counted and explained; five URLs are spot-checked
  against Bronze; and the menu endpoint's p50/p95 latency on those venues is reported before and
  after.

### Owner decision (Amendment 4)

Answered by the owner on 2026-10-22, at the end of session P8-5, before this amendment was
drafted:

> - Draft ADR-0008 Amendment 4 and build it in the same PR. Stop for review only if a real
>   design choice comes up (a migration, a Gold column, a new dependency, a change to Menu,
>   Identity or Provenance models).
> - Shape: `source_url: str | None` on each MenuResponse = the endpoint URL of the family's
>   most recent price Evidence, through the provenance contract (source_endpoint_for_evidence).
>   Null if nothing resolves. One URL per menu; not per price, not a list.
> - Read at request time, batched per menu request, no migration. If the menu endpoint's
>   EXPLAIN or latency on helios_laptop looks bad, stop and ask.
> - rate_limited stays deferred to step 7 (ADR-0019 Q5/Q4); do not add it.

None of the stop conditions arose. There is no migration, no Gold column, no new dependency,
and no model change: the batched lookup is a new contract function over the existing
provenance models. The tie-break order and the skip-unresolved rule are this amendment's own
precision of "most recent". They are not separate owner answers.

### Build notes (Amendment 4)

Built 2026-10-22, session P8-6, as above. Measured read-only on `helios_laptop` (Gold as
refreshed in P8-5), through two local APIs side by side: `main` before and this branch after,
each over a `default_transaction_read_only` session:

- **Coverage.** `has_menu=true` pages to 941 venues. They serve **946 menus**: five venues
  have two Establishment menus each. 18 menus are `establishment` scope and 928 are
  `organization`. **Every menu carries a `source_url`: 0 nulls.** Before the build, all 54,318
  Gold rows cited one or two price Evidence ids. Every one of those 108,593 citations resolves
  to a Capture, and no family cites more than one endpoint. The 946 families come from 1,015
  family pages, at most two per family. On every one of those pages, all price Evidence reaches
  a single Capture, and it is the page Version's own Capture: the one-Evidence-per-page
  invariant holds on all of this data. There are 613 distinct URLs: 136 URLs serve more than one
  menu (469 menus), for example a chain site shared by single-venue Organizations (47 menus on
  one URL). The URL is still right for each of those menus. Excluding those from the price index
  is ADR-0007's `shared_menu_url` rule, not this endpoint's concern.
- **Body.** Apart from `source_url` and the clock-driven `age_seconds`, every one of the 941
  bodies equals `main`'s.
- **Spot check against Bronze** (five venues, six menus: venue 1398's two delivery-platform
  menus, and the Organization menus of 474, 10710, 17523 and 20757). For each menu, three
  values agree: the served URL, the rule's winner recomputed independently in SQL, and the
  `menu_url` in the latest Version payload of the record. Each family cites exactly one
  endpoint, and every cited Capture is `succeeded`, has a bundle, and is the target of its
  Evidence.
- **Latency** (all 941 venues, interleaved before/after, two measured passes after one warm-up
  pass, n = 1,882 each):

  | Build | p50 | p95 | max |
  |---|---:|---:|---:|
  | First build: every Evidence resolved (runs 1 and 2: `main` → branch) | 10.2 → 13.3 ms | 24.9 → 32.5 ms | 58 → 75 ms |
  | One Evidence per page (run 3: `main` → branch) | 9.95 → 11.45 ms | 22.0 → 25.1 ms | 51 → 57 ms |

  In the first build, the largest family (687 rows, 873 distinct Evidence) spent about 18 ms in
  `menu_source_urls`, about 10 ms of it in SQL. At this table size (about 23k Versions and 26k
  Captures) the planner chose a hash join with a sequential scan of `source_record_version`
  over 873 index probes. `UNION ALL` and `LATERAL` rewrites ran in 9–15 ms, and selecting
  columns instead of ORM entities did not help. The owner chose the one-Evidence-per-page
  read (2026-10-23, option 1 of four: the others were resolving through the Menu page's
  Version, a Gold URL column, and an in-process cache). With it, the same family takes
  **1.4 ms** in `menu_source_urls` (median of 20). All 946 `source_url` values are identical to
  the first build's.

## Implementation notes (2026-09-28)

- Owner decision 4 and its disposition call `httpx2` bogus and `httpx` a dev dependency. `httpx` is a
  runtime dependency (`pyproject.toml`; used by `packages/helios_core/geo.py` and `apps/discovery/web_client.py`),
  and Starlette's `TestClient` now warns to install `httpx2` (review R47).
- Decision point 5 (2026-10-21): the response models are one module, `apps/api/schemas.py`, not an
  `apps/api/schemas/` package.

## References

- [ADR-0001](./0001-stack-choice.md) — stack; the deferred web-framework choice
  this ADR closes.
- [ADR-0004](./0004-modular-monolith-identity-and-lifecycle.md) — module/schema
  boundaries; `apps` reads published contracts from `identity`/`gold`.
- [ADR-0006](./0006-gold-menu-read-models.md) — `gold.current_menu`, the read
  model any menu-bearing endpoint serves; money/freshness conventions.
- [ADR-0007](./0007-gold-price-index-projection.md) — price index (deferred; the
  aggregate endpoints this API grows into in Phase 7).
- [ROADMAP §4.4](../../ROADMAP.md#44-api-layer) (API layer),
  [Phase 2](../../ROADMAP.md#phase-2--first-light-read-api--staging-deploy),
  [Phase 7](../../ROADMAP.md#phase-7--api-surface-full-including-the-price-index).
- [RFC-0001](../rfc/0001-menu-pricing-first.md) work-plan PR 4.
- `apps/api/main.py` — current `/healthz` + `/readyz`; the FastAPI app being
  ratified.
- `packages/helios_core/identity/models.py` — Establishment/Place/Organization,
  the venue resource's source grains.
- `packages/helios_core/config.py` — settings surface a `cors_allow_origins`
  addition extends.

## S13 venue lifecycle filtering (2026-09-28)

Accepted [ADR-0012 §3–§4](0012-venue-lifecycle.md) changes both venue routes:
`/v1/venues` and `/v1/venues/{id}` serve only current Establishments with current
Organization and Place parents, a status other than `closed`, and no expired
`valid_to`. A filtered detail request returns the existing 404 error contract.
Lifecycle re-homing records an Establishment merge and preserves its lineage;
the API does not add a redirect or historical-venue endpoint in S13.
