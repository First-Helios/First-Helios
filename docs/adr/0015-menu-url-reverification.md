# ADR-0015: Menu-URL precision before the first Pi run — re-verify saved menu URLs

**Status:** Proposed (draft for owner review; not implemented)
**Date:** 2026-09-28
**Phase:** 4/5 boundary (Pi gate 1b)
**Decides for:** the "page classifier or saved-menu re-verification path"
criterion of Pi gate 1b ([remediation checklist](../reviews/2026-09-22-remediation-checklist.md),
owner decision G.a)
**Numbering:** ADR-0013 is reserved for the Phase 5 menu-pipeline ADR (owner
decision G.b); ADR-0014 is the location-override draft.

## Context

The Pi URL gate was framed around location quality (duplicates, geocodes). The
code says that framing is wrong for `resolve_urls`:

- **URL records don't use coordinates.** Website and menu-URL records are keyed
  by GERS id (`<gers>`, `<gers>|<platform host>`; `apps/discovery/url_pipeline.py`
  module docstring and `_persist_menu`), and nothing in `resolve_urls.py`,
  `url_pipeline.py`, `menu_url.py`, `web_client.py` or `registry.py` reads a
  latitude or longitude. A duplicate venue yields a redundant but true per-POI
  record; a wrong coordinate changes nothing the resolver writes. A later merge or
  retirement leaves those records as history (`org_not_current` is counted and
  skipped).

The real risk to URL data is **menu-URL precision**, and it is permanent by
construction:

1. **The own-site verifier is imprecise.** The menu-model spike's stage C measured
   the S4 verifier (ADR-0010 Amendment 3) at **venue-level precision 0.605, recall
   0.676**; its false positives were press releases, blog posts, a Toast marketing
   signup, another city's IHOP, chain location/hub pages and `/menus` landings
   ([spike README](../spikes/menu-model/README.md), Results, stage C rows).
2. **Platform pages have no content check.** S6b accepts an ordering-platform link
   from the homepage on `200` + HTML + a venue-page path alone
   (`web_client.py` 585-598; `menu_url.platform_links_from_html` needs no menu
   wording). A chain homepage that links one Toast page per location gives every
   venue on that site the first link (PR #46 open question).
3. **A saved menu URL is never re-checked.** A `resolved` menu record whose website
   is unchanged is reused without any fetch (`url_pipeline.py` 704-711,
   `menu_urls_reused`). Re-verification happens only on a lifecycle transition
   (`_transfer_menus`, ADR-0012 §2); the 20-day `RECRAWL_WINDOW` applies only to
   failures. D3.7 ("replace only when re-discovery succeeds") only fires when the
   website changes.

The Pi holds **no menu-URL records yet** (rebuilt 2026-09-28, `resolve_urls` not
run). If the spike's 150-venue sample is representative, the first run will write
roughly 40% wrong own-site menu URLs (1 − 0.605) plus unchecked platform pages, and the reuse rule freezes them: a
better verifier shipped later (the ADR-0013 page classifier: precision 0.976 in
the spike) would never look at them. Bronze keeps history either way, so nothing
is unrecoverable; the damage is silent, indefinite coverage loss, because a venue
with a wrong saved URL is never re-discovered.

## Decision (recommended: option C, B first)

**B — Re-verify saved menu URLs against the current verifier. C — then let the
ADR-0013 page classifier become that verifier.** Gate 1b opens on B plus the two
cheap fixes below; it does not wait for Phase 5's new runtime dependencies.

1. **Verifier version in the payload.** Every menu-URL observation records
   `verifier` (e.g. `s4-v1`, later `classifier-v1`) in its Bronze payload
   (JSON; no schema change; ADR-0011 content-hash semantics unchanged).
2. **Re-verify instead of reuse** when the saved record's `verifier` is older than
   the current one, or its last successful verification capture is older than
   `REVERIFY_WINDOW` (proposed 90 days, a named constant). Re-verification uses the
   existing `verify_menu_attempt` path (fresh fetch, same robots/rate-limit rules,
   `not_before` = the decision to re-verify).
3. **Outcomes, all through existing commands:**
   - still passes → record a succeeded Capture (resets the window); no new Version;
   - fails → run discovery; a different verified URL is persisted as a new Version
     (the D3.7 rule); if nothing verifies, `unassign_source_record`
     (`identity/commands.py` 478) moves the record to `needs_review` with the failed
     verification as Evidence, so downstream consumers (Phase 5 selection) never
     read a URL the current verifier rejects. Registry (`config/sources.yaml`)
     entries are never re-verified away: the registry still wins (D3.2).
4. **Platform content check.** A platform page must pass the same page check as an
   own-site candidate (today `page_menu_signal` with `trust_path=False`; later the
   classifier). A platform page that fails is not saved.
5. **Chain homepages.** Skip platform links from a homepage that links more than
   one distinct venue page on the same platform host (the guard proposed in
   PR #46), and count it (`platform_ambiguous`). A per-location registry entry is
   the escape hatch for single-venue sites that trip it.
6. **Report counters:** `menu_urls_reverified`, `menu_urls_withdrawn`,
   `platform_ambiguous`.

When ADR-0013's classifier lands, bumping `verifier` makes the next run re-check
every URL saved by the S4 heuristic, so the first Pi run's errors are corrected
automatically rather than frozen.

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| A. Wait for the ADR-0013 page classifier before the first Pi run | Best first-run precision (0.976 in the spike) | Blocks URL coverage measurement on Phase 5's new runtime deps (onnxruntime/fastembed, model files) and Q2-Q9; still freezes whatever the classifier gets wrong |
| **B. Re-verification path (recommended first)** | No new dependency; no schema change; every later verifier improvement becomes retroactive; unblocks the coverage measurement ROADMAP Phase 4 still owes | First-run URLs are only as precise as S4 until re-verified; one extra fetch per saved URL per window |
| **C. B, then A as the verifier (recommended end state)** | Combines both | Two steps |
| D. Run now, fix by hand later | Nothing to build | ~40% wrong own-site URLs frozen; manual correction of thousands of records |

## Consequences

- The first Pi run measures website/menu-URL coverage (the last unmet Phase 4
  "done when" item) without committing to its errors.
- **Harder:** each run re-fetches saved menu pages on the window, so monthly runs
  touch more hosts (bounded by the window and the existing per-host rate limit).
- `needs_review` becomes a routine outcome for menu URLs, so its count needs
  watching; a human clears it through the registry.
- Phase 5 (not built) would read only `resolved` menu records, all of which
  passed the current verifier within the window.

## Open questions for the owner

1. `REVERIFY_WINDOW`: 90 days, or tie it to the monthly discovery schedule?
2. Is the chain-homepage guard (item 5) acceptable given it drops some
   single-venue sites until a registry entry is added?

## References

- [Spike README](../spikes/menu-model/README.md) (stage C baselines; classifier result)
- [ADR-0013](./0013-phase5-menu-pipeline.md) (Proposed) §7: the page classifier as
  verifier `classifier-v1` (option C), with render-before-reject for JS-only pages
- [ADR-0010](./0010-website-and-menu-url-resolution.md) Amendment 3;
  [ADR-0011](./0011-provenance-endpoints-vs-identity-match-keys.md) §7;
  [ADR-0012](./0012-venue-lifecycle.md) §2 (derived URLs on transition)
- PR #46 (S6b) "Multi-location chain homepages" open question
- Code: `apps/discovery/url_pipeline.py` (`_resolve_venue`, `_transfer_menus`,
  `RECRAWL_WINDOW`), `apps/discovery/web_client.py` (`discover_menu_url`,
  `verify_menu_attempt`), `apps/discovery/menu_url.py` (`page_menu_signal`,
  `platform_links_from_html`), `packages/helios_core/identity/commands.py`
  (`unassign_source_record`)
