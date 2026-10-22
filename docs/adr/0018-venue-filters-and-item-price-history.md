# ADR-0018: Venue filters and item price history (Phase 7 API remainder)

**Status:** Accepted 2026-10-21 by the owner (Q1–Q9, all as recommended; see
[Owner decision](#owner-decision)). Proposed 2026-10-21 (session P7-1). Not implemented yet;
implementation is a separate session.
**Date:** 2026-10-21
**Phase:** 7 (API surface)
**Extends:** [ADR-0008](./0008-read-api-conventions.md) (read-API conventions; amends Decision point 9,
[ADR-0008 Amendment 3](./0008-read-api-conventions.md#amendment-3-2026-10-21-history-reads-through-the-menu-selector)), [ADR-0006](./0006-gold-menu-read-models.md) (Gold
current menu), [ADR-0007](./0007-gold-price-index-projection.md) (the grid cell as an area)
**Depends on:** [ADR-0005](./0005-immutable-menu-snapshots-and-selection.md) §9–§10 (history
mode, correspondence), [ADR-0013](./0013-phase5-menu-pipeline.md) N1 (version-local native
keys; read only, not changed here)

## Context

[ROADMAP Phase 7](../../ROADMAP.md#phase-7--api-surface-full-including-the-price-index) has
two API items left (README "Not built yet"):

- "Venue filters (area, organization, has-menu), cursor-paginated."
- "`GET /v1/items/{id}/price-history` — the observation trail behind a single price."

Neither item says what its parameters are keyed on, and the code shows that some of the
obvious answers don't work. What the code says today (`main@51a83a3`):

1. **The venue wire has no Organization id.** `VenueResponse` has nine fields (`id`, `name`,
   `organization_kind`, `address`, `latitude`, `longitude`, `operating_status`, `valid_from`,
   `valid_to`), and Organization is not an addressable resource (ADR-0008 §2). A client has no
   way to learn the value an `organization` filter would take.
2. **"Area" is defined only by the price index.** ADR-0007 keys an area as a 0.01° lat/lon grid
   cell: `area_kind = 'latlon_grid_0p01'`, `area_key = "<cell_lat>,<cell_lon>"` (south-west
   corner, `gold.price_index.grid_cell`). There is no ZIP, neighbourhood or district column,
   and RFC-0001 defers "78704"-style queries. The price index places a venue by its Place
   point (`identity.contracts.current_venue_locations`).
3. **Place coordinates have no index.** `identity.place` has only `uq_place_subject_kind`.
   Phase 7 requires every filter combination to be index-backed. Establishment already has
   `ix_establishment_organization_subject_id`, and Gold has `ix_gold_current_menu_scope`.
4. **A Gold row id is not an item id.** `gold.current_menu.id` is a surrogate that each full
   refresh replaces (ADR-0006 §3). A link built on it breaks at the next refresh. The stable
   identity is the grain `uq_gold_current_menu`: scope subject, source record, root key, target
   path, effective context, currency.
5. **A target exists in one Version only.** The production writer
   (`apps/menu_pipeline/menu_writes.py`, ADR-0013 N1) gives every node a version-local native
   key, `v<version id>:<block>:<normalized text>`. ADR-0005 §10 forbids matching by name. So
   one target path appears only on the pages written for one Bronze Version:
   - a re-interpretation of the same Version (a pipeline-version bump, `correction`) keeps the
     key when the block and text are unchanged;
   - a newer Version (the monthly re-capture, `observation`) never corresponds to it; the old
     target becomes `absent` once the newer page is accepted;
   - a withdrawal makes it `withdrawn`; a restoration brings it back only if the restored
     aggregate reuses the same native path, which means the same Version.

   "This dish went from $12 to $14" cannot be answered today, by design. The history of one
   target is at most: accepted, maybe corrected, then superseded or withdrawn.
6. **History lives in Menu, not Gold.** `gold.current_menu` holds current answers only; the
   refresh rejects knowledge or observation cutoffs (ADR-0006 owner decision D5.3). History is
   the selector's history mode: `select_price` with a knowledge cutoff `K` returns the accepted
   answer at `K` (ADR-0005 §9). In history mode the stream heads are picked over the whole
   family, not filtered by subject. Today ADR-0008 §9 says reads of current menu content use
   Gold and never the selector. It says nothing about history.
7. **"Has a menu" is already defined by the menu endpoint.** `GET /v1/venues/{id}/menu` serves
   only `priced`/`unknown`/`unavailable` rows (`gold.menu_read.SERVED_PRICE_STATES`) of the
   venue's Establishment scope, plus its Organization scope when the venue is that
   Organization's one current venue. The derived states (`absent`, `withdrawn`,
   `unresolved_*`, `not_operating`) are never served. Full-catalog enumeration skips
   withdrawal heads, so a venue whose streams are all tombstoned has no served row.

The task brief for this session (P7-1) says to write an ADR and stop if either endpoint's
shape or semantics is not settled. Facts 1–6 show they are not. CLAUDE.md also requires a stop
for the index migration that point 3 needs.

## Decision

### A. Venue filters on `GET /v1/venues`

Three optional query parameters, ANDed together. Pagination doesn't change: keyset on the
Establishment `subject_id`, default 50, cap 200. The cursor does not encode the filters; a
client sends the same filters with each page. A cursor reused with other filters only starts a
page at that id, which is harmless (`apps/api/pagination.py` already says so). A filter that
matches nothing is `200 items: []`, never 404 (ADR-0008 §4).

1. **`has_menu: bool`.** `true` means `GET /v1/venues/{id}/menu` would return at least one
   menu: a served-state Gold row exists for `(venue, establishment)`, or for
   `(organization, organization)` when the venue is that Organization's one current venue.
   `false` is the complement. `withdrawn`, `absent` and the other derived states count as no
   menu (fact 7). A semi-join on `ix_gold_current_menu_scope`. The filter reflects the last
   Gold refresh. The list response does not get an `as_of`, because it serves no price
   (question Q4).
2. **`organization: int`.** The Organization `subject_id`, compared for equality with
   `Establishment.organization_subject_id` (`ix_establishment_organization_subject_id`). To make
   it usable, `VenueResponse` gains **`organization_id`**. Adding a field doesn't break
   clients; the OpenAPI snapshot is regenerated. Names are not accepted: they are not unique,
   and matching them would be fuzzy.
3. **`area: str`.** A price-index `area_key` (`"30.26,-97.75"`). A venue matches when the
   0.01° cell containing its Place point is that key, the same rule
   `gold.price_index.grid_cell` applies. In SQL this is
   `cell_lat <= latitude < cell_lat + 0.01 AND cell_lon <= longitude < cell_lon + 0.01`, exact on
   `Numeric(9, 6)`. A venue with no point never matches. A key that is not canonical (does not
   round-trip through `grid_cell`) is `422 validation_error`. The list of venues behind a
   price-index row is then one call away from the index response, which returns `area_key`.
   **Index-backed requires a migration:** a btree on `identity.place (latitude, longitude)`.
   It adds an index only, with no column change or data rewrite, but it is an Identity
   migration, so it needs owner approval (question Q2).

Each filter combination gets an `EXPLAIN` test that fails on a sequential scan of
`gold.current_menu` (the existing Phase 7 rule) and of `identity.place` when `area` is set.

### B. `GET /v1/items/{item_id}/price-history`

4. **`item_id` is an opaque token for a Gold target, not a database id.** It is a base64url
   encoding of `(subject_kind, subject_id, source_record_id, root_key, target_path)`, the
   grain minus context and currency. It stays the same across refreshes and needs no lookup
   table and no Gold column. `GET /v1/venues/{id}/menu` gains an `id` on every node that
   carries prices (section, item, variant, modifier), so the menu links to its history. As
   with the cursor, the token is opaque but not secret: a forged token can only name a target
   that does or doesn't exist. A token that doesn't decode is `422 validation_error`. One that
   decodes but names no target ever claimed for that subject in that family is
   `404 not_found`. Paths with version-local keys make tokens about 150–300 characters, which
   is fine in a URL path.
5. **One trail per effective context and currency.** The response is
   `{item_id, as_of, trails: [{channel, service_period, valid_from, valid_to, currency_code,
   points: [...]}]}`. The contexts come from Menu: every price observation in the family
   whose canonical native path is the target's (the same correspondence rule enumeration
   uses). An item that has left Gold still has a history, so links survive the next capture.
   `as_of` is the request instant, because the trail is computed live from committed Menu
   and not from a Gold refresh. No pagination: one family has a bounded number of pages
   (roughly 12–24 a year per stream at a monthly cadence).
6. **Points come from the selector's history mode, one per change.** The candidate knowledge
   instants are the `accepted_at` of every page in the family `(source_record_id, root_key)`,
   since the answer can only change when a page is accepted. For each `K`, in ascending order,
   call `select_price(knowledge_cutoff=K, effective_instant=K, observation_cutoff=None)`. Emit a
   point when the local result differs from the previous point, comparing
   `(state, amount_minor, page_id)`. A point has `known_from` (`K`), `state` (one of
   `priced`, `unknown`, `unavailable`, `absent`, `withdrawn`, `unresolved_base`),
   `amount_minor`, `observed_at`, `source_kind` and `confidence`. So:
   - a withdrawal is a `withdrawn` point, and a restoration that reuses the native path is a
     later `priced` point;
   - a newer Version that supersedes the target is one `absent` point, which ends the trail
     honestly. No continuity across Versions is claimed (fact 5).
7. **Only the scope's own claims.** Some instants are known only through pages owned by
   another subject: the record was mapped to a predecessor before a remap, and history-mode
   heads are family-wide (fact 6). Those instants emit no point. They are that subject's
   history (ADR-0004 §5, ADR-0005 §9), not this venue's. Organization claims are not mixed
   into a local trail; an Organization-scoped target has its own `item_id`.
8. **Boundary: an amendment to ADR-0008 §9.** Current menu content is read from Gold, never
   the selector, as now. Accepted history is read from Menu through the selector's history
   mode, because Gold holds current answers only. The read is a new pure function in
   `packages/helios_core/domains/menu/` beside `enumeration.py`. It reuses the selector's
   correspondence helpers, re-implements no precedence, and doesn't change any model. The
   route calls it, the way the menu route calls `gold.menu_read`. The cost is one selector
   call per candidate `K` per context, which is not index-backed in the Gold sense because the
   function doesn't read Gold. Its Menu reads are keyed by `uq_menu_stream_revision` and the
   `page_id` indexes. A synthetic test bounds the query count.

### C. What the trail can and cannot show

9. **Ship the honest within-Version trail now. Treat cross-Version continuity as a separate
   decision.** Under N1 a trail usually has one to three points: accepted, perhaps corrected,
   then absent when the next capture lands. That is "the observation trail behind a single
   price", which ROADMAP asks for: when the price was first accepted, from which source kind,
   whether it was corrected, and when it stopped being current. It does not show a dish's
   price over time. That needs a cross-Version correspondence rule, which would amend
   ADR-0005 §10 and ADR-0013 N1. It is out of scope here, and ADR-0013 is reserved for the
   parallel P5-33 session.

## Alternatives considered

| Option | Pros | Why not proposed |
|---|---|---|
| `area` as `lat`/`lon` (the cell containing a point), as in `/v1/price-index` | Same parameters as the index endpoint | A client following an index row holds the `area_key`, not a point. Both forms could be accepted later without breaking anything. Question Q1. |
| `area` as a bounding box | General; works for map viewports | Not what the price index calls an area. Needs the same index. A second area concept with no consumer yet. |
| `area` as ZIP or neighbourhood | What people mean by "area" | No column or data. Parsing ZIPs out of `address` is a heuristic. RFC-0001 defers it. |
| Leave `area` unindexed | No migration | Breaks Phase 7's index-backed rule. The cost is small at ~10k Places but grows with coverage. |
| `organization` by name | No wire change | Names are not unique; equality on names is fuzzy matching by another name. |
| `item_id` = Gold row id | Short, trivial | Replaced by every refresh; links break. |
| `item_id` = a stored hash column in Gold | Short ids; an indexed lookup | A Gold migration and a new column for a value the token already carries. Possible later if token length bites. |
| `item_id` per price (context and currency included) | Matches "a single price" literally | Clients get one id per menu node instead of one per price row. Contexts are few (the writer emits `unspecified` only). Question Q6. |
| Defer price history until cross-Version correspondence exists | The endpoint would show price over time | Blocks a useful provenance view on an unscheduled decision, which belongs to ADR-0005 and ADR-0013 owners. |
| Read history from raw Menu SQL | Faster; one query | A second definition of precedence and lifecycle (ADR-0006 §5); the brief rules it out. |
| Store history in Gold | Index-backed reads | A Gold change; reopens ADR-0006 D5.3 (current answers only). |

## Consequences

**Easier**

- Each filter maps to one existing or proposed index, and to one existing definition (the
  menu endpoint for `has_menu`, the price index for `area`).
- Menu nodes link to their history through ids that survive Gold refreshes and new captures.
- History reuses the accepted selector, so withdrawal and restoration show up exactly as
  selection already resolves them.

**Harder / accepted costs**

- One Identity migration (the Place index) and two additive wire fields (`organization_id`,
  menu node `id`), so the OpenAPI snapshot changes.
- Price history is computed on request, not served from a table. Its cost grows with a
  family's page count, not with the catalog.
- Under N1 most trails are short and end in `absent`. Users can see when a price stopped being
  current, but not what replaced it. That limit is stated in the response docs, not hidden.
- The opaque token puts version-local keys in URLs. If N1 changes, old tokens still decode;
  they keep naming the old targets.

## Owner questions (answered 2026-10-21)

- **Q1. `area` form.** The price-index `area_key` (recommended), a `lat`/`lon` point, or both?
- **Q2. Place index migration.** Approve a btree on `identity.place (latitude, longitude)`
  (index only, no data rewrite)? Or accept an unindexed `area` filter for now?
- **Q3. `organization_id` on `VenueResponse`.** Approve the additive field?
- **Q4. `has_menu` definition.** "The menu endpoint would return a menu", including the
  Organization's menu for a single-venue Organization (point 1). No `as_of` on the list?
- **Q5. `item_id` encoding.** The opaque grain token (recommended), or a stored Gold key
  column (a migration)?
- **Q6. `item_id` granularity.** One id per target with a trail per context (recommended), or
  one id per price row?
- **Q7. History semantics.** `K` = each family page's `accepted_at`, `E = K`, one point per
  change, only the scope's own claims (points 6–7). Should points also carry the Bronze
  Version id or Evidence ids? Neither has an endpoint yet, so they would be ids a client
  cannot follow.
- **Q8. Scope of the trail.** Ship the within-Version trail now (recommended) and open
  cross-Version correspondence as its own ADR-0005/ADR-0013 question? Or defer the endpoint?
- **Q9. ADR-0008 §9 amendment.** The API reads history through a Menu-domain function over
  the selector's history mode (point 8)?

## Owner decision

**Accepted by the owner on 2026-10-21**, answering Q1–Q9 in session P7-1. Every answer took
the recommended option, so the Decision section above stands as written:

1. **Q1 `area` form:** the price-index `area_key`. No `lat`/`lon` form.
2. **Q2 Place index:** approved. One hand-reviewed Alembic revision adds a btree on
   `identity.place (latitude, longitude)`. It adds an index only; no column changes and no
   data is rewritten. The `area` filter gets a no-seq-scan test.
3. **Q3 `organization_id`:** approved as an additive field on `VenueResponse`.
4. **Q4 `has_menu`:** defined as "the menu endpoint would return a menu", including a
   single-venue Organization's menu. The venue list gets no `as_of`.
5. **Q5 `item_id` encoding:** the opaque base64url token over the Gold target grain. No Gold
   column.
6. **Q6 granularity:** one id per target, with one trail per context and currency.
7. **Q7 history semantics:** as points 6–7 propose. Points carry no Bronze Version or
   Evidence ids until an endpoint can resolve them.
8. **Q8 trail scope:** ship the within-Version trail now. Cross-Version correspondence is a
   separate ADR-0005/ADR-0013 question, not opened here.
9. **Q9 boundary:** ADR-0008 §9 is amended (Amendment 3). History is read through a pure
   Menu-domain function over the selector's history mode.

This acceptance covers the design. It does not cover unseen code: the Place-index migration
SQL stays a CLAUDE.md read-twice path, and the owner reviews it in the implementation PR.

## References

- `apps/api/routes/venues.py`, `apps/api/schemas.py`, `apps/api/pagination.py`
- `packages/helios_core/gold/models.py` (`uq_gold_current_menu`), `gold/menu_read.py`,
  `gold/price_index.py` (`grid_cell`)
- `packages/helios_core/domains/menu/selection.py` (`select_price`, `_stream_heads`),
  `domains/menu/enumeration.py`
- `packages/helios_core/identity/models.py` (Place, Establishment indexes)
- `apps/menu_pipeline/menu_writes.py` (N1 version-local native keys)
