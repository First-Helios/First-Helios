# Menu browsing integration — proposed contract and ownership

Status: first cache/loading slice approved by owner 2026-10-27; no new metadata
contract agreed with extraction yet. Backend branch `feat/menu-cache-validation`
and frontend `feat/menu-cache`, in `var/menu-browsing/{backend,frontend}`.
Extraction session identified from Claude records: `db8b4026-4c7c-4c22-b2a8-07f114e74560`,
worktree `.claude/worktrees/p8-21-page-structure`.

The extraction session's current task explicitly owns discovery, rendering,
capture, extraction, validation, interpretation and collection-quality data;
it leaves frontend/API routes/caching to this session and will document contracts.
Reading that boundary is not agreement on new field semantics.

## File boundary

This session proposes changes only to frontend `js/api.js`, `js/main.js`,
`js/dom.js`, `js/price.js`, `js/pages/{venue,item,venues,map}.js`, `css/site.css`,
`dev_server.py`, tests/tools/docs; backend `apps/api/` and API tests/docs.
First slice is limited to API fetch/cache helpers, restaurant/history UI, price
presentation, proxy conditional-header forwarding, HTTP validation and their tests.

Do not touch discovery, capture, extraction, parsing, validation, source identities,
ORM models, migrations, Gold refresh logic, persisted quality metadata, `infra/`,
deploy configuration, or the Pi. No new dependencies/services. Extraction owns
the meaning and persistence of future collection status. Any overlap, publication
token or source-identity exposure requires written agreement first.

## Available today — no body changes needed for first slice

| Surface | Existing fields/semantics |
|---|---|
| Browsing | Cursor pages of venue summaries; ANDed has_menu/organization/area/area_kind/boundary filters; no menus in list |
| Venue | id, organization_id/kind, name/address, location, operating_status, validity; no official URL |
| Menu document | venue_id, menus[], as_of (oldest Gold refresh among returned rows, null if empty) |
| Source page | scope, nullable source_url, sections[]; no stable public menu ID or page label |
| Nodes | key within parent, opaque id when priceable, separate variants/modifiers; descriptions on items |
| Price | state priced/unknown/unavailable, integer amount_minor/null, currency, channel, service_period, validity, observed_at, age_seconds, source_kind, confidence |
| History | Opaque node ID; separate context/currency trails, accepted corrections, absent/withdrawn; as_of is request computation time |

`menus: []` means no currently published Gold menu. It does not distinguish not
collected, blocked, failed, withdrawn, empty source or unavailable. Do not infer
coverage from it, from page/item counts, or from confidence. Display coverage
unknown until the backend supplies an agreed field. A request failure is a client
transport state, never an empty published menu.

## Proposed follow-ups — not implemented or consumed

Names below are review proposals, not promises or fields clients may start using.

1. `official_url: string | null` on venue: reviewed official website identity,
   returned by the API from the existing identity/provenance contract. Never derive
   it from a menu source host. Identity owner must identify the allowed reader.
2. Opaque `menu_id` on each source-page entry; stable for a backend source identity,
   unique across scope and restaurant context. Optional source-asserted display
   label/context, if available. No labels inferred from URL paths, dish names or
   frontend keyword rules. Keep ADR-0022's joined menu with explicit page boundaries.
3. Collection coverage object: `status` in `unknown | partial | complete | unavailable`,
   an explicit scope (which expected pages/states were checked), a collection attempt
   time, and an optional plain-language reason code. `complete` only means the
   defined expected scope was assessed successfully; it never guarantees all items
   on the entire website. `partial` means the collector positively knows some
   expected scope is missing. `unavailable` requires a known reason, not an empty
   item array. Absent metadata maps to unknown. No percentages or confidence proxy.
4. Separate last-attempt outcome/time from published coverage. Failed collection
   refresh with a retained older publication must preserve that publication's
   coverage/date and say the later attempt failed. A browser HTTP failure must not
   change persisted collection status. Review exact outcome values with extraction.
5. Opaque `publication_revision` with equality semantics that changes for every
   published correction, withdrawal (including last item → empty), restoration,
   context/option change, source-link correction, and displayed quality change.
   `as_of`, newest observed_at, row count, and max node ID are insufficient. Specify
   how partial Gold refresh and live source/identity/quality reads join one revision
   before using it as a pre-query cache invalidation token.

Current per-price context and node identities are enough to render current data;
they are not enough to invent a lunch/dinner page selector if pages have no label.
Keep duplicate-looking dishes in separate backend nodes/pages. Render modifiers
as additional charges and variants as the backend-supplied complete prices; do
not sum or resolve conflicting source prices in the browser.

## Invalidation proposal requiring acknowledgment

First slice does not require a new publication token: API HTTP validators are
computed from fresh response data. The semantic hash includes every stable body
field, including deletions, source URLs and contexts; only request-relative age
and the history response's request-time as_of are excluded. Price observation
dates always participate. A weak ETag denotes semantic equivalence, not byte identity.

An application-memory hit may serve for up to 30 seconds without a network check;
after that, revalidate on access, focus/online return while visible, and at most
30-second intervals while a menu/history view stays active. Manual refresh forces
revalidation. Previously loaded data may remain with an explicit refresh-failed
warning for at most 10 minutes since validation; after that, show an error/retry,
not old prices. No guarantee of immediate push invalidation is claimed. Once an
empty publication is successfully validated, replace the old menu immediately.

The extraction owner should acknowledge coverage/attempt separation and identify
any forthcoming revision/source fields before those follow-ups are built. A
server resident response cache is deferred until a safe token and measured need
exist; HTTP validation still performs the underlying read, so a correction or
withdrawal does not wait for a process-cache TTL to expire.
