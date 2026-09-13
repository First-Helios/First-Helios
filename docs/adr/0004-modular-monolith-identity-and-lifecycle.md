# ADR-0004: Modular monolith, lifecycle layers, and shared identity

**Status:** Accepted
**Date:** 2026-09-12
**Accepted:** 2026-09-12 by project owner Fortune
**Supersedes:** [ADR-0003](./0003-three-layer-schema.md)

## Context

ADR-0003 established one Postgres database with `raw`, `canonical`, and
`mart` schemas. The first implementation PR has now made part of that design
real:

- `raw`, `canonical`, and `mart` exist;
- `canonical` contains `brand`, `venue`, `venue_alias`, `venue_source`,
  `site_identity`, and `venue_site`;
- `raw` and `mart` contain no application tables yet; and
- no menu model or ingest path exists.

That implementation exposed an identity problem that should be corrected
before the menu schema depends on it:

1. `venue` combines a physical place, an operating business at that place,
   and the thing to which future menu facts would attach.
2. `brand` is a useful chain label, but it is not a complete organization
   grain.
3. `venue_source.venue_id` is mandatory. A source record therefore cannot
   exist until Helios has resolved it, even though unresolved and ambiguous
   records are normal inputs to identity resolution.
4. `venue_source` is deleted with its venue. That makes provenance depend on
   the continued existence of a canonical interpretation.
5. A single `canonical` schema puts shared identity and food-specific facts
   in the same ownership boundary. A later vertical would either import food
   concepts or add more unrelated tables to the same namespace.
6. ADR-0003 says the whole canonical layer can be dropped and rebuilt from
   replay bundles. Human resolution decisions, remaps, merges, and splits are
   not reproducible from source bytes alone. Treating them as disposable
   would destroy learned identity.

The correction is still comparatively cheap. There are no menu FKs, no
public read API over these entities, and no tables in `raw` or `mart`.
The owner has explicitly classified the current database as pre-production
and authorized a clean reset of its application data. The implementation
must make that data loss explicit in a separately reviewed migration rather
than spend effort backfilling a short-lived scaffold.

Helios remains a solo, agent-built project. The architecture therefore needs
boundaries that can be checked mechanically without adding distributed
systems or operational services.

## Decision

Helios will be a **modular monolith**: one repository, one release unit, one
Postgres database, and one Alembic history, with multiple in-process
entrypoints where needed. Modules communicate through Python contracts and
database keys, never through an internal network API.

Two independent classifications govern data:

1. **Lifecycle:** Bronze, Silver, or Gold.
2. **Ownership:** shared provenance, shared identity, a named vertical
   domain, or a derived read product.

Lifecycle does not replace domain ownership. In particular, there will be no
single catch-all `silver` or `canonical` schema.

The context and logical data model are shown in:

- [Modular-monolith context diagram](../diagrams/0004-modular-monolith-context.md)
- [Identity and provenance logical ERD](../diagrams/0004-identity-provenance-erd.md)

### 1. Bronze, Silver, and Gold semantics

| Lifecycle | Meaning | Mutability and durability | Physical ownership |
|-----------|---------|---------------------------|--------------------|
| **Bronze** | Source-faithful claims: sources, collection endpoints, captures, durable external record keys, immutable record versions, and evidence locators | New versions append. Existing versions and evidence are not corrected in place. Bronze is a system of record and is backed up; it is not independently droppable while Silver references it. Raw payload bytes may remain in replay storage, with hashes and locators in Postgres. | `bronze` schema, owned by shared provenance |
| **Silver** | Validated, typed interpretations of source claims | Corrections preserve history. Shared identity decisions are durable because manual adjudication cannot be recreated by replay. Vertical observations follow their domain's append-only rules. | `identity` schema plus one schema per implemented vertical, beginning with `menu` |
| **Gold** | Consumer-oriented projections, aggregates, indexes, and API read models | Rebuildable from Bronze and Silver. Gold may be truncated or replaced by its owning refresh task and is never an authoritative write target. | `gold` schema, with explicitly named product tables |

The former equation `raw = disposable`, `canonical = replayable`, and
`mart = derived` is superseded. Replayability is not the same as
disposability: source versions, evidence, and human identity decisions are
durable even when some Silver domain observations can be regenerated.
Silver modules may own rebuildable **internal** projections needed to enforce
their invariants. Those projections remain implementation details of the
authoritative module; Gold is reserved for consumer-facing read models.

### 2. Module and schema ownership

The intended module boundaries are:

| Module | Package ownership | Schema ownership | Responsibility |
|--------|-------------------|------------------|----------------|
| Database foundation | `packages.helios_core.db` | `public.alembic_version` only | `Base`, sessions, URL handling, migration registration |
| Shared provenance | `packages.helios_core.provenance` | `bronze` | Sources, captures, source records and versions, immutable evidence |
| Shared identity | `packages.helios_core.identity` | `identity` | Subjects, typed identity grains, resolution history, identity lineage |
| Menu vertical | `packages.helios_core.domains.menu` | `menu` | Menu-specific facts and observations only |
| Gold read models | `packages.helios_core.gold` | `gold` | Rebuildable API and analytical projections |
| Pure extraction | `packages.helios_parsing` | none | Pure parsing DTOs; no ORM or database imports |
| Entrypoints | `apps/*` | none | Compose modules into API, scrape, backfill, and refresh workflows |

These paths define ownership, not a requirement to scaffold every directory
immediately. A package and schema are created only when their first real
behavior or table lands.

Shared provenance and identity are centralized. **Vertical facts are not.**
For example, menu prices belong to `menu`; a later domain must own its own
typed tables. There will be no shared `offering`, `fact`, or
`attribute/value` store.

### 3. Identity grains

`identity.subject` is a stable, opaque identity handle with a constrained
kind. It exists so resolution and lineage can refer uniformly to canonical
identities. It is not a bag of attributes and it does not replace typed
tables.

Every Subject has exactly one typed grain:

| Grain | Meaning | Examples and non-examples |
|-------|---------|---------------------------|
| **Place** | A physical or geospatial location that persists independently of who operates there | A street address or parcel. It is not "Torchy's" and does not close when a restaurant closes. |
| **Organization** | An enduring operating, ownership, or brand identity independent of any one location | A chain brand or an independent operating identity. A current `Brand` migrates conservatively as organization kind `brand`; that does not assert a legal corporate identity. |
| **Establishment** | An organization's operation at a Place for an effective interval | A restaurant location. Operator changes at one address produce a new Establishment while retaining the Place. |
| **Subject** | The common identity and lineage grain underlying one typed Place, Organization, or Establishment | Used by resolution and explicitly polymorphic domain roots. It carries no vertical attributes. |

An Establishment references one Place and one Organization. A newly inferred
Subject starts `provisional` when it lacks meaningful identity features;
vertical writers may use only eligible Subjects. Readiness is based on typed
evidence such as source keys, normalized address/coordinates, and names, not
on brand presence alone. Organization name fingerprints are non-unique match
inputs, never identity keys; duplicate Place and Organization candidates are
an expected conservative result until evidence supports a later merge.

The typed-grain invariant is relational, not only an application convention:
Subject exposes a unique `(id, kind)` key; each typed table carries a constant
kind, checks that constant, and has a composite FK to Subject. A deferred
constraint enforces exactly one typed row per Subject at transaction end.

Operational closure and identity retirement are different:

- closing a restaurant ends or changes the Establishment's operating state;
- retiring a Subject means Helios no longer treats that canonical identity
  as a current independent referent, usually because it was merged, split, or
  proven invalid; and
- a Place is not retired merely because one Establishment at it closes.

Vertical tables reference the most specific valid typed grain. A genuinely
polymorphic root may reference Subject only when it declares its allowed
Subject kinds. For the future menu schema, a menu scope may be an
Organization (chain-wide menu) or Establishment (location-specific menu),
never a Place. Menu items and prices remain typed menu facts under that
scope. Organization scope means shared menu content, not identical prices at
every location: Establishment-scoped facts may refine or override the shared
content. The menu schema PR must define deterministic precedence without
copying Organization prices blindly to every Establishment.

Identity matching and deduplication use typed feature clusters such as source
keys, names, addresses, coordinates, and websites. A name fingerprint is one
input, never sufficient proof of identity by itself.

### 4. Provenance and unresolved source records

A Source Endpoint is a retrievable location such as a first-party URL. A
Source Record is one source-local entity claim, such as an Overture place ID,
an OSM element ID, or one extracted entity within a web document. A single
endpoint may yield records about multiple Subjects; the URL itself is
therefore not forced through a one-record/one-Subject mapping. Record Versions
preserve what a source asserted at a particular observation.

The following are required:

- a Source Record and its versions can exist with **zero resolution events**;
- resolution is never a required FK on Bronze;
- Source namespace keys, Endpoint identities, and a Source Record's
  `(source_id, external_key)` identity are immutable after insert;
- repeated observations append Source Record Versions rather than replacing
  the earlier payload;
- Captures are immutable records of completed fetch attempts;
- source payload JSON is allowed in Bronze as source-faithful evidence, not
  as a query-serving domain model;
- Evidence is immutable and points to exactly one record version or capture
  using a reproducible locator, such as a field path, bounded excerpt, and
  content hash; and
- Silver identity and vertical decisions link to Evidence rather than
  copying an untraceable free-text claim.

An unresolved record is a valid state, not a dead letter. Rejected or
unparseable input is different: it remains Bronze data with an explicit
outcome or reason code. A Source Record may remain outside identity workflow
with zero resolution events. Admission to that workflow appends an `Open`
event and creates an explicit `identity.current_resolution` state of
`unresolved`; later states are `resolved` or `needs_review`. Unresolved work
is indexed and queryable rather than inferred from a missing row.

### 5. Append-only resolution and correction semantics

`identity.resolution_event` records the interpretation of one Source Record.
Its history is append-only: database writes may insert an event but may not
update or delete an existing one.

Resolution operations are:

| Operation | Preconditions | Result |
|-----------|---------------|--------|
| **Open** | The Source Record has no resolution history; `from_subject` and `to_subject` are null | Admits the record to identity workflow and creates explicit `unresolved` current state |
| **Assign** | The Source Record is `unresolved` or `needs_review`; `from_subject` is null and `to_subject` is non-null | Appends a target Subject; the current-resolution projection becomes `resolved` and points to it |
| **Remap** | `from_subject` is the current Subject; `to_subject` is non-null and different | Appends the correction; the previous assignment remains historical |
| **Unassign** | `from_subject` is the current Subject and `to_subject` is null | Sets the projection to `needs_review` without erasing why it had been assigned |

The current mapping is `identity.current_resolution`, a rebuildable Silver
projection of the event sequence, not a mutable truth row. Event insertion
locks the owning Source Record, validates the transition against the current
projection, appends the event, and updates the projection in the same
transaction. One state row per Source Record in the resolution workflow
serializes competing assignments and keeps unresolved work visible; Identity
correctness never depends on Gold.

Canonical Subject lineage is separate from source-record resolution:

| Operation | Semantics |
|-----------|-----------|
| **Merge** | Two or more same-kind Subjects become one current Subject. The output may be a designated survivor or a new Subject. Non-surviving inputs retire and redirect through lineage; existing source and vertical history is not rewritten. |
| **Split** | One Subject is found to represent multiple real referents. Two or more new Subjects are created, the predecessor retires as ambiguous, and source records are explicitly remapped. Existing vertical facts are not silently copied to every output. |
| **Retire** | A Subject ceases to be a valid current identity without a replacement. History and inbound evidence remain queryable. |

Merge, split, and retirement are append-only `subject_change` events with
typed input/output members. Membership is keyed by
`(subject_change_id, subject_id, role)`. A merge has at least two distinct
input Subjects and exactly one output; when an input survives, it appears
once as an input and once as the output. A split has exactly one input and at
least two new, distinct outputs; a retirement has one input and no output.
Cycles are invalid. The change transaction locks all member Subjects in
stable ID order, verifies that each input is current, appends the event, and
updates the rebuildable Identity lineage projection atomically.

No operation physically deletes provenance, decisions, or observations.
Domain-specific reassignment after a split is performed by that domain under
its own typed correction semantics. Gold excludes facts scoped only to a
retired ambiguous predecessor from current views until they are explicitly
reclassified, while historical queries retain them.

### 6. Confidence and evidence

Every automated or manual resolution and Subject change records:

- a bounded confidence in `[0, 1]`;
- a decision method and version;
- the actor class (`rule`, `model`, `migration`, or `human`);
- the decision time and, when different, effective time; and
- at least one immutable Evidence link or an immutable
  `identity.adjudication` record.

Confidence measures the decision procedure's certainty; it is not a claim
that the underlying source is true. Evidence and confidence are therefore
separate. A high-confidence match to a stale source remains stale, and two
independent pieces of evidence are not collapsed into a longer prose string.

Thresholds are policy owned by the resolver and may change without rewriting
history. The method version makes old scores interpretable after calibration
changes.

`identity.adjudication` is an append-only record of a human actor, bounded
rationale, and decision time. It is not fabricated source evidence. A
transaction may commit a resolution or Subject change only when it has at
least one Bronze Evidence link or one adjudication record.

The append-only decision aggregate includes the event, adjudication, Evidence
links, and Subject-change members. None can be updated or deleted in
isolation to rewrite an old decision.

Evidence retains the Source Endpoint chain needed to recover the original
public source URL. A later API may expose that link to an end user without
making the URL an Organization attribute.

### 7. Allowed dependency directions

Data flows from source-faithful to interpreted to derived:

```text
Bronze -> Identity Silver -> Vertical Silver -> Gold
       \------------------> Vertical Silver
       \-------------------------------------> Gold
Identity Silver --------------------------------> Gold
```

An FK points from the dependent consumer row to the provider row, so its
arrow is the reverse of the data-flow notation above. The allowed FK matrix
is:

| Dependent schema | May reference |
|------------------|---------------|
| `bronze` | `bronze` only |
| `identity` | `identity`, `bronze` |
| `menu` | `menu`, `identity`, `bronze` |
| `gold` | `gold`, `menu`, `identity`, `bronze` |
| `public` | No application table; `alembic_version` only |

Additional rules:

- Identity never has an FK to a vertical or Gold.
- Bronze never has an FK to Identity, a vertical, or Gold.
- A vertical never has an FK to another vertical.
- No authoritative table has an FK to Gold.
- FKs from observations or history use `RESTRICT`/`NO ACTION`, not a cascade
  that erases evidence when an interpretation changes.
- Gold may use FKs for integrity, but no source transaction depends on a
  Gold row existing.

Python imports follow the same ownership direction:

```text
apps
  -> gold
  -> domains.menu -> identity contracts -> provenance contracts -> db foundation
                  \-> provenance contracts
  -> identity
  -> provenance
```

- Lower modules never import entrypoints or higher modules.
- Identity imports no vertical package.
- Vertical packages import contracts from shared identity/provenance, not
  another vertical's ORM or services.
- Gold may read published contracts from the modules it projects.
- `helios_parsing` remains independent and has no ORM import; an application
  entrypoint adapts parser output into menu commands.
- `packages.helios_core.db.model_registry` may import all model modules solely
  to populate `Base.metadata`; it is the single allowlisted import-direction
  exception and is not a domain API.

### 8. Consistency and execution

Cross-module workflows run in process and may share one database transaction.
For example, ingest can append a Bronze version, append an identity
resolution, and insert a typed menu observation atomically after validation.
There is no message broker, distributed transaction, internal HTTP call, or
eventual-consistency requirement in this decision.

Modules expose commands, queries, and typed data contracts. Application code
does not reach through one module to mutate another module's ORM objects.

### 9. Relationship to RFC-0001

This ADR supersedes only these architecture details in
RFC-0001 Section D2:

- the five-table venue identity shape;
- nullable `menu_page.venue_id` as the representation of unresolved input;
  unresolved input now remains in Bronze; and
- a free-text `price_observation.evidence` field as sufficient provenance;
  typed menu observations instead link to immutable Bronze Evidence.

RFC-0001's menus-first product, source policy, typed menu graph, append-only
prices, and milestones remain in force.

### 10. Explicit non-decisions and prohibitions

This ADR does **not**:

- define the menu table set beyond its identity/provenance dependency seam;
- implement a second vertical;
- define a generic offering or cross-vertical price-observation model;
- introduce EAV tables or arbitrary Silver `attributes` JSON;
- introduce a graph database;
- split Helios into microservices or separate databases;
- choose automated match thresholds, a review UI, or an LLM; or
- require dbt, a queue, cache, or search service.

Those are either deferred until measured requirements exist or rejected as
contrary to the modular-monolith decision.

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| Keep ADR-0003 unchanged and put identity plus menus in `canonical` | Least migration work; already partially implemented | Keeps Place, operator, and establishment conflated; cannot retain unresolved source records cleanly; no enforceable vertical boundary; falsely treats human resolution as disposable |
| One generic Subject plus EAV attributes and generic observations | New entity and vertical types need few migrations | Moves type checking into application code, weakens constraints, makes money/units/validity ambiguous, and centralizes the vertical facts this ADR deliberately isolates |
| Shared generic offering and price tables | Appears to reuse price-history machinery across domains | "Offering" semantics, units, applicability, and corrections differ by domain; designing the abstraction before a second real vertical would be speculative scaffolding |
| Separate service and database per provenance, identity, and vertical | Strong deployment isolation and independent scaling | Network failure modes, duplicated operations, no simple transactions or FKs, and disproportionate complexity for one maintainer |
| Graph database for identity and lineage | Natural traversal for merge/split graphs | Adds a second datastore and synchronization problem; Postgres adjacency tables and recursive queries are adequate for the known workload |
| Duplicate identity and provenance inside each vertical | Maximum vertical autonomy | Conflicting identities, repeated match logic, and no shared evidence trail; cross-domain questions become reconciliation projects |

## Consequences

**Easier**

- Source data can be captured before Helios knows what it represents.
- A correction is inspectable as a decision sequence rather than inferred
  from overwritten foreign keys.
- Place reuse, operator changes, chain-wide facts, and location-specific
  facts have distinct grains.
- A vertical can evolve its own typed schema without importing another
  vertical's concepts.
- Package, schema, import, and FK rules can be encoded as architecture
  fitness tests.
- Gold remains cheaply rebuildable without pretending manual identity work is
  equally disposable.

**Harder / accepted costs**

- Identity queries require joins through Subject and typed identity tables.
- The current six-table identity scaffold is removed by an explicitly
  destructive clean-reset migration before menu tables land.
- Merge and split correctness requires transactional invariants and lineage
  checks, not only simple FKs.
- Bronze and identity require backup as durable systems of record.
- Alembic's managed-schema allowlist and its tests must represent bounded
  contexts rather than exactly three physical schemas.

**Acceptance effects**

- ADR-0003 is `Superseded by ADR-0004`.
- [Plan 0002](../plans/0002-identity-foundation-before-menu.md) becomes the
  implementation sequence for the affected portions of Plan 0001.
- No schema implementation begins until the owner separately authorizes the
  migration PRs required by CLAUDE.md.

## References

- [ADR-0003](./0003-three-layer-schema.md)
- [RFC-0001](../rfc/0001-menu-pricing-first.md)
- [Plan 0001](../plans/0001-map-and-menu-collection.md)
- [Plan 0002](../plans/0002-identity-foundation-before-menu.md)
- [Human review guide](../reviews/0004-architecture-review-guide.md)
- `packages/helios_core/db/models/venue.py`
- `alembic/versions/a466cf4bc4e0_venue_identity_schema_and_three_layer_.py`
- `test/test_schema_layout.py`
- `test/test_venue_identity_schema.py`
