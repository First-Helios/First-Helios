# ADR-0014: Location overrides — durable, evidence-backed coordinate corrections

**Status:** Proposed (draft for owner review; not implemented)
**Date:** 2026-09-28
**Phase:** 4 (remediation of the 2026-09-22 review; Pi gate 1a)
**Decides for:** the "coordinate-override mechanism" criterion of Pi gate 1a
([remediation checklist](../reviews/2026-09-22-remediation-checklist.md), owner
decision G.a)
**Numbering:** ADR-0013 is reserved for the Phase 5 menu-pipeline ADR (owner
decision G.b), so this draft takes the next number after it.

## Context

The owner-delegated adjudication of the S6 precision audit
([precision review](https://github.com/First-Helios/First-Helios/blob/b2bba735d6de6259b675620fe652cb495b5d43d3/docs/reviews/2026-09-28-precision-review.md)) found **4 wrong
geocodes in the unchanged 100-row sample** (95% interval 1.1-9.9%), against the
ROADMAP Phase 4 bar of < 1%. Each is an Overture coordinate that disagrees with
the venue's corroborated address by 1.6-21 km (P. Terry's MLK, El Sol y La Luna,
La Parrilla, Lali Son). Two of them also have a second, correctly placed record
for the same outlet elsewhere in the export.

These points cannot simply be fixed in place:

- **The lifecycle pass undoes an in-place fix, destructively.**
  `apps/discovery/lifecycle.py` `project_observation` compares each new Overture
  Version's coordinate with the Identity Place (`RELOCATION_RADIUS_M = 50`,
  lines 287-298). If a human corrected P. Terry's Place by 1.6 km, the next
  release (still carrying the bad point) is a "relocation": the corrected
  Establishment is **closed** and a new Place is minted **at the bad point**.
  ADR-0012 anticipated this ("If humans ever edit features, §1 B becomes
  necessary before the next automated pass, or the pass overwrites their edit").
- **A rebuild reproduces the defect.** Minting copies the Overture coordinate
  (`pipeline._resolve_coordinates`, Nominatim only fills a missing point), so a
  fresh Pi rebuild from the same release recreates every bad point.
- **Dedupe uses the bad point.** `_dedupe_candidates` matches by fingerprint
  within 50 m of current Places, so the misplaced P. Terry's MLK record (9336) was
  minted as its own venue instead of deduping with its correctly placed twin
  (14829, 1.6 km away), and now sits 102.6 m from the Congress store.

The correction must therefore be (1) durable across releases and rebuilds,
(2) replayable from Bronze like every other Identity input (ADR-0003, ADR-0011),
(3) evidence-backed, and (4) self-invalidating when upstream changes, so a stale
override never pins a venue that genuinely moved.

Duplicate cleanup and non-venue records need **no** new mechanism: merges and
retirements already go through `record_subject_change` / `remap_source_record`
with Evidence (ADR-0004 §5, ADR-0012 §4), and a merged or retired venue is left
alone by later passes (`_owned` / currentness checks). Only coordinates (and
their address text) lack a durable human path. That is all this ADR covers.

## Decision (recommended: option A)

**A location override is a Bronze observation, keyed by GERS id, that the
discovery pipeline applies in place of the Overture coordinate wherever the
coordinate is consumed.**

1. **Source of truth: a reviewed file**, `config/location_overrides.yaml`, one
   entry per Overture record:

   ```yaml
   # Illustrative shape only: the point below is the Census match, which alone
   # would not qualify under rule (1); a real entry needs a qualifying basis.
   overrides:
     - gers_id: 63274178-3ab7-4bee-a1f8-26c3d27389ea   # P. Terry's MLK (9336)
       latitude: 30.28207
       longitude: -97.74332
       address: 517 W Martin Luther King Jr Blvd, Austin, TX, 78701   # optional
       corrects: {latitude: 30.267153, longitude: -97.743073}         # the Overture point being replaced
       evidence_url: https://pterrys.com/locations/mlk-517-w-mlk-jr-blvd-austin-texas-78701/
       basis: official_pin | parcel | two_geocoders   # how the new point was obtained
       reason: overture point 1.66 km from corroborated address
   ```

   Validated structurally like `config/sources.yaml` (`apps/discovery/registry.py`):
   required keys, finite WGS84 bounds inside the metro bbox, HTTP(S) evidence URL.
   A replacement point must come from an official business pin, a parcel/permit
   record, or two independent geocoders that agree within 50 m; a single
   interpolating geocoder is not enough (this packet measured Census 575 m off an
   official pin).
2. **Bronze first.** Each run persists every entry as a Version in a new
   `location-override` source namespace (`external_key = gers_id`), with the
   repo-relative endpoint and file hash exactly as the URL registry does
   (ADR-0011). Removing an entry appends a withdrawal Version, so history is never
   lost and replay knows the override ended.
3. **One effective-location function** used by minting, dedupe and the lifecycle
   projection: the override's point when an active override exists for the
   record **and** its `corrects` point still equals the Overture Version's point
   (to 6 decimals); otherwise the Overture point.
4. **Upstream drift disables, never silently applies.** If Overture's point no
   longer equals `corrects`, the override is ignored for that run and reported
   (`override_stale`) for a human to re-confirm or withdraw. That covers both
   "Overture fixed it" and "the venue really moved".
5. **Identity is unchanged.** Place columns keep being a projection of Bronze
   (ADR-0012 §1 A): the lifecycle pass sees the effective point, so an override
   first applied to an existing venue is an ordinary ≤ 50 m correction or, for a
   larger move, a relocation (close + new Place/Establishment) with the override's
   Evidence and `method = "location-override"`. No Identity migration. Whether the
   first application of a > 50 m override should instead update the Place in place
   (a correction, not a real-world relocation) is the one open question for the
   owner below.
6. **Report counters:** `overrides_applied`, `override_stale`, `override_invalid`.

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| **A. Bronze override file (recommended)** | Durable across releases and rebuilds; replayable; Evidence chain like the URL registry; no Identity migration; stale overrides self-disable | New Bronze namespace + one effective-location function touching minting, dedupe and lifecycle; a reviewed YAML file to maintain |
| B. Identity feature-change event table with a human "pinned" flag (ADR-0012 §1 B) | History of edits lives in Identity; generic for names/addresses too | Migration on an Identity table (⚠ path); lifecycle must learn to respect pins anyway; replay from Bronze alone no longer reproduces Identity |
| C. `place.coordinate_source = 'manual'` column; lifecycle skips manual Places | Smallest code change | Migration on an Identity model; in-place edit loses history; no drift detection, so a real move is never picked up |
| D. Correct upstream only (Overture/OSM) and wait | No local mechanism | Weeks to months; not all errors originate in editable sources; the gate stays closed meanwhile |

A is recommended because it reuses a pattern the project already accepted for
URLs (a reviewed registry that "always wins", persisted in Bronze), keeps
Identity a pure projection of Bronze, and fails safe on upstream change. D is
still worth doing in parallel as a courtesy, not as the fix.

## Consequences

- The four confirmed wrong points (and any found by the fresh-sample re-audit)
  can be fixed durably. Duplicates caused by a bad point (9336 vs 14829, 2109 vs
  7497, 27456 vs 27480) still need an explicit merge decision; the override only
  stops the bad point from hiding them.
- **Harder:** every coordinate consumer must call the effective-location
  function. A consumer that reads the Overture payload directly would reintroduce
  the bug; tests must cover minting, dedupe, relocation and rebuild.
- The override file becomes a CODEOWNERS-reviewed input. Entries need evidence of
  the stated `basis`; the adjudication's 150 m / 1,000 m rules
  ([README gate 1a label criteria](../../README.md#gates); source:
  [precision review](https://github.com/First-Helios/First-Helios/blob/b2bba735d6de6259b675620fe652cb495b5d43d3/docs/reviews/2026-09-28-precision-review.md)) are the review
  standard for adding one.
- Rebuilding the Pi from the same release after this lands produces corrected
  points without hand edits.

## Open questions for the owner

1. First application of a > 50 m override to an existing venue: **relocation**
   (close + new ids; consistent with ADR-0012, id churn for four venues) or an
   **in-place correction** (stable ids; needs an explicit exception in the
   lifecycle rules)? Recommendation: in-place correction, because the venue never
   moved; only our data did.
2. Should address-text overrides ship now (only Lali Son's partial address needs
   one) or wait for a second case?

## References

- [Precision review, adjudication section](https://github.com/First-Helios/First-Helios/blob/b2bba735d6de6259b675620fe652cb495b5d43d3/docs/reviews/2026-09-28-precision-review.md#adjudicated-results)
  (historical) and [`reviewed.json`](https://github.com/First-Helios/First-Helios/blob/b2bba735d6de6259b675620fe652cb495b5d43d3/docs/reviews/data/2026-09-28-precision-review/reviewed.json)
- [ADR-0012](./0012-venue-lifecycle.md) §1 (audit options), §2 (relocation rule)
- [ADR-0010](./0010-website-and-menu-url-resolution.md) §4 (registry precedence);
  [ADR-0011](./0011-provenance-endpoints-vs-identity-match-keys.md) (registry provenance)
- Code: `apps/discovery/lifecycle.py` (`project_observation`, `RELOCATION_RADIUS_M`),
  `apps/discovery/pipeline.py` (`_resolve_coordinates`, `_dedupe_candidates`),
  `apps/discovery/registry.py` (validation pattern)
