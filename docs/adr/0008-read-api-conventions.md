# ADR-0008: Read-API framework and conventions (First Light)

**Status:** Accepted — Unit A (venues read endpoints) reviewed and **accepted by
the owner on 2026-09-20**; all four open conventions confirmed as-implemented (see
[Owner decision](#owner-decision)). Unit B (staging deploy) not done — a separate
reviewed unit.
**Date:** 2026-09-20
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
</content>
