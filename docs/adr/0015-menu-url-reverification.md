# ADR-0015: Menu-URL precision before the first Pi run — re-verify saved menu URLs

**Status:** Accepted 2026-09-29 (owner, session S6d): option C, B first, as
amended by [Amendment 1](#amendment-1-2026-09-29-acceptance-decisions); the
verifier is ADR-0013's page classifier (`classifier-v1`; `classifier-v2` since S6f, see Amendment 1; `classifier-v2+v3`, v2 AND v3, since P5-33, ADR-0013 Amendment 27) from the first Pi run.
[Amendment 2](#amendment-2-2026-10-27-proposed-a-wrong-place-page-check) (a wrong-place
page check, `place-v1`) was accepted 2026-10-27, all questions as recommended, and built in
P8-18.
**Date:** 2026-09-28
**Phase:** 4/5 boundary (Pi gate 1b)
**Decides for:** the "page classifier or saved-menu re-verification path"
criterion of Pi gate 1b ([remediation checklist](https://github.com/First-Helios/First-Helios/blob/b11cf3d084eb9a3ea7c53dfe1fd35cbd32cf5978/docs/reviews/2026-09-22-remediation-checklist.md),
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
  watching. A record re-verification withdrew is retried automatically and
  re-assigned by a verified URL or a registry entry (Amendment 1); one a human
  disputed stays until a human acts.
- Phase 5 (not built) would read only `resolved` menu records, all of which
  passed the current verifier within the window.

## Open questions for the owner

Answered at acceptance (Amendment 1): 1. `REVERIFY_WINDOW` = **90 days**.
2. The chain-homepage guard resolves itself **automatically** (address match), with
no manual registry step.

## References

- [Spike README](../spikes/menu-model/README.md) (stage C baselines; classifier result)
- [ADR-0013](./0013-phase5-menu-pipeline.md) §7: the page classifier as
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

## Amendment 1 (2026-09-29): acceptance decisions

Owner decisions at the start of session S6d, with the code facts that shaped them:

1. **A passing re-check appends a Version.** Bronze has no command that records a
   successful fetch without a Version (ADR-0011 §4: `succeeded` always has one;
   `record_capture_attempt` takes only `failed`/`skipped`). The pass is persisted
   as a Version with the same payload (plus the current `verifier`); its Capture's
   `fetched_at` is the "last successful verification" the window is measured from.
   Cost: one row per saved URL per window.
2. **Only a verdict on the page withdraws a URL.** `WITHDRAW_REASONS` =
   `no_menu_found` (the page answered and failed the page check, or no longer sits
   on the site), `not_html`, `http_404`, `http_410`, `platform_root`,
   `social_link`. Any other failure (network error, 5xx, 403/429, robots, crawl
   delay, redirect refused, or a homepage that can't be read to compare against)
   records a failed/skipped Capture, keeps the URL, and is retried next run
   (counter `menu_urls_reverify_deferred`).
3. **Withdrawal Evidence** is a `rejected` observation of the record (new rejection
   reason `menu_not_verified`; the payload adds `verification_failure`), and the
   `unassign_source_record` decision uses method `menu-url-reverify`. Adding a
   reason code needs no migration (ADR-0011 §4).
4. **Rule-withdrawn records recover.** A record whose latest Identity decision is a
   `menu-url-reverify` unassignment is retried when the verifier changes or its
   last attempt is older than the window, whatever the 20-day site cooldown, and
   re-assigned when discovery verifies a URL for it or the registry names a menu.
   A record a human put in `needs_review` is still never retried. A failed re-check
   also re-discovers regardless of the cooldown; a re-discovered URL (new or the
   same one) is appended as a Version.
5. **`REVERIFY_WINDOW` = 90 days.** Registry menu URLs carry no `verifier` and are
   never re-verified (D3.2).
6. **Chain homepages resolve automatically.** When a homepage links several venue
   pages on one platform host, up to `MAX_CHAIN_CANDIDATES` (3) of them are
   fetched, the ones whose URL path names the venue's house number or street first,
   and the page is kept only if exactly one passes the page check **and** shows the
   venue's house number followed by its street name (`address_on_page`; the
   address is the Overture record's first `freeform` street line). Otherwise
   nothing is saved for that platform and `platform_ambiguous` counts it. Phone
   matching was also approved but is not built: Overture ingestion does not select
   `phones`, and adding it changes every POI's Bronze payload (a new Version per POI
   on the next release). It needs its own decision. An address override
   (ADR-0014) is not consulted yet; a wrong Overture address only causes a skip.
7. **Platform content check = the verifier.** Platform pages (a homepage link, or a
   website that is itself a platform page) pass the same `PageVerifier` as own-site
   candidates. The owner chose to pull ADR-0013's page classifier into S6d rather
   than ship an interim word check: `classifier-v1` is the verifier for the first
   Pi run (a separate ⚠ PR; ADR-0013 Amendment 1 accepts its classifier parts).
   The heuristic `s4-v1` remains the default in code and tests.
8. **Platform pages need a real browser.** A probe of the spike sample's 37
   platform links (2026-09-29, honest UA, robots obeyed;
   `var/spikes/menu-model/render-probe-2026-09-29/`) found no readable menu without
   JavaScript: Toast/DoorDash answer `403` to the fetcher, and every `200` was a
   JavaScript shell. Rendered, 19 of 37 were priced menus: Square, Clover and
   Grubhub render headless; Toast needs headed Chromium (4 gift-card links were
   robots-disallowed; 3 DoorDash pages stayed `403`; the rest were jobs,
   marketing-signup and gift-card pages, which the content check now rejects).
   Rendering is new session S6f (ADR-0013 Amendment 1). Until it lands, platform
   pages in practice fail the page check and are not saved.
   *S6f (2026-09-29): rendering built (`resolve_urls --render`, ADR-0013
   Amendment 2) and the verifier bumped to `classifier-v2`, which accepts rendered
   Toast menus; the bump makes the next run re-check every URL `classifier-v1`
   saved.*

## Amendment 2 (2026-10-27, proposed): a wrong-place page check

**Status: Proposed 2026-10-27 (session P8-18). Accepted 2026-10-27 by the owner, Q1–Q5 as
recommended, and built in P8-18 (see the [build note](#owner-decision-and-build-amendment-2)).**
Record:
[2026-10-27-p8-18-site-data-fixes.md](../reviews/2026-10-27-p8-18-site-data-fixes.md) §1
(measurements, the blind precision check and the full flagged list). Prototype:
`var/p8-18/places.py` and `check.py` (untracked).

**The gap.** The verifier decides whether a page is a menu, not whose menu it is. Jefes
(venue 21183) shows a Galloway, NJ takeout's menu. Discovery found it in its own website's
host's sitemap (smorefood), and `classifier-v2` accepted it, correctly, as a menu. Over the
1,682 stored menu pages, a generic check flags 59 records (39 URLs, 54 live). A blind judge
rated 52 of the 54 live records WRONG.

1. **The check, `place-v1`.** A pure function, `apps/discovery/place_check.py`. Its inputs
   are the page URL, its `segment-v2` blocks, the venue's Overture address (locality, region,
   postcode), the area (below), and whether the URL is a chain page. The page is
   **wrong-place** when it does not name the venue's metro and shows evidence of another
   place:
   - *Mentions:* "City, ST" and "City, ST 12345", ST a US state code. An all-caps city counts
     only with a ZIP. A mention followed by "!" or a lower-case word is a name, not a place.
   - *Foreign:* the ZIP is outside the area's postcodes; or the state is not the venue's;
     or the place is in the venue's state and contains no area locality.
   - *Metro named:* the venue's locality as a word on the page or in the URL path, an area
     locality written "City, <venue state>", or an area postcode.
   - *E1, URL place:* the URL path names a foreign place. That is a foreign ZIP closing a
     slug, or a run of up to four path tokens equal to a gazetteer city.
   - *E2, address:* a foreign "City, ST 12345", on a page naming at most two foreign places
     with a ZIP. Not on a chain page: one menu URL saved for at least two area venues whose
     names share their first word, where a lone out-of-town address is the head office.
   - *E3, dominant place:* one foreign place, outside chrome and wine sections
     (`output.wine_section`), named at least twice, on a page with at most two foreign places
     outside chrome.
   - *Verdict:* wrong-place when the metro is not named and E1, E2 or E3 holds. Also when E1
     holds and the URL path does not name the metro, even if the page does: that is another
     location's page of a chain whose location list includes the metro.

   Wine appellations, brewery towns and chain location lists are excluded by construction:
   they are many distinct places, or they sit in chrome, or they include the metro.
2. **The area, from data.** Per run, from the latest Overture Versions in the database:
   - the localities with at least 3 POIs (39 in `helios_laptop`, Austin to Dale);
   - every POI postcode (106).

   No hand-made place list. A second metro would come with its own Overture area.
3. **Where it runs: discovery's verification (this ADR).** The URL is what is wrong, and
   re-discovery is what can find the right one.
   - The `SiteFetcher` page check becomes the classifier AND `place-v1`, for:
     - every own-site and platform candidate in `discover_menu_attempt`;
     - every `verify_menu_attempt`.

     The venue's address reaches both through `VenueToResolve`, which gains locality,
     region and postcode, read from the same Overture payload.
   - A page the classifier accepts and `place-v1` rejects is
     `CaptureFailure("failed", "wrong_place")`.
   - `wrong_place` joins `WITHDRAW_REASONS`. As item 3 and Amendment 1 item 3 say, a failed
     re-check re-discovers. If nothing verifies, `_withdraw_menu` writes the rejected
     `menu_not_verified` observation (`verification_failure: wrong_place`) and the
     `menu-url-reverify` unassignment.
   - Downstream nothing new is needed:
     - the record in `needs_review` is out of `due_pages` (`menu_url_withdrawn`);
     - R4's `retract_rejected` withdraws its Menu streams at the next re-score or extraction
       (ADR-0013 Amendment 27);
     - the next Gold refresh drops its rows.

     It is reversible: a later verified URL re-assigns the record (Amendment 1 item 4), and
     R4 restores its pages.
   - Accepted saves record `place_check: "place-v1"` in the payload. The `verifier` string
     (`classifier-v2+v3`) and the extraction pipeline version are unchanged, so nothing is
     re-extracted and nothing is forced to refetch (Q3).
4. **Applying it to the saved URLs: a stored-bundle sweep.** `python -m
   apps.discovery.place_sweep [--dry-run]`:
   - for each resolved menu-URL record, read the latest stored `menu-page` bundle of its
     URL (same external key), with no fetch;
   - apply `place-v1`;
   - withdraw a flagged record through `_withdraw_menu`, with the bundle Capture's
     `fetched_at`.

   Then `python -m apps.menu_pipeline.rescore` (R4) and `python -m apps.gold.refresh`. On
   `helios_laptop` that is the 39 URLs and 59 records of the record's §1.5. 54 are live,
   carrying 2,503 of Gold's 60,119 rows.
5. **Known misses (not proposed).**
   - Location lists by neighbourhood only (Cane Rosso: "North Dallas"; 1 in the 60-URL
     unflagged sample).
   - Stale menus (`holiday-menu-2015`).
   - Phone area codes: Overture phones are not ingested (Amendment 1 item 6).
   - Non-US place names.
6. **No new dependency, no schema change, no migration.** No per-site, per-platform or
   per-venue rule.

**Measured (record §1.4).** Every v2 flag was judged blind by Sonnet subagents and the
disagreements were re-checked in the main session:
- **URLs:** 34 of 39 WRONG, precision 0.872;
- **live records:** 52 of 54, precision 0.963. The other two are Sarpino's
  `…/new-york-deli-pizza` dish page (RIGHT) and Fabaceae (UNSURE: a Houston footer, a 512
  phone).

The two refinements from v1 to v2 (name-shaped mentions, the chain-page exemption) were tuned
on these labels. So this is a census of the stored corpus, not an estimate for new pages.

### Owner questions (Amendment 2)

- **Q1. Where.** In discovery's verification, as item 3 (recommended: the URL is what is
  wrong, and re-discovery can replace it)? Or as a second extraction-time verifier, which
  withdraws the streams but keeps the URL saved and never looks for another?
- **Q2. Gazetteer for E1.** Foreign places named on any stored menu page, rebuilt from the
  bundles at the start of each run (recommended)? Mostly chains' chrome location lists:
  285 slugs, about 8 s. It adds 4 URLs, all judged WRONG: tiltedkilt `las-vegas`, firepitatl
  `atlanta`, thecheesybite `richmond-tx`, haywire `houston`. Or only the places the page
  itself names (35 URLs instead of 39)?
- **Q3. Applying it.** The stored-bundle sweep (item 4: no network, exactly the list judged;
  future verifications check new pages) (recommended)? Or bump the `verifier` string so the
  next `resolve_urls` re-verifies every saved URL against the live page? That took about 3
  hours on the laptop in P5-33, and re-judges every page with the classifier too: P8-1 Q3's
  real menu was lost that way.
- **Q4. Re-discovery for the withdrawn venues.** Leave it to the schedule (recommended):
  Amendment 1 item 4 retries a rule-withdrawn record when the verifier changes or after
  `REVERIFY_WINDOW`. Or add a `--venues` filter to `resolve_urls` and run it now for these
  venues?
- **Q5. Residuals.** Accept the two live non-WRONG flags (Sarpino's dish page, Fabaceae)
  being withdrawn with the rest? There is no per-venue exception, and withdrawal is
  reversible.

### Owner decision and build (Amendment 2)

**Answered by the owner on 2026-10-27, all as recommended:**
- Q1: discovery's verification;
- Q2: the corpus gazetteer;
- Q3: the stored-bundle sweep;
- Q4: re-discovery left to the schedule;
- Q5: the residuals are withdrawn with the rest.

**Built 2026-10-27 (P8-18).** No schema change, no migration, no new dependency; the
`verifier` string and the extraction pipeline version are unchanged.
- **`apps/discovery/place_check.py`.**
  - `place_verdict` is item 1's rule, as measured.
  - `load_place_area` builds the area for a run:
    - localities with at least 3 POIs, every postcode and the area's regions, from the latest
      Overture Versions;
    - the gazetteer, from every stored `menu-page` bundle;
    - the chain URLs, from the menu-URL records' latest payloads.

    On `helios_laptop`: 39 localities, 106 postcodes, `TX`, 239 gazetteer slugs and 186 chain
    URLs, in 3.1 s.
  - Over the stored pages the module reproduces the measured prototype exactly: 59 records,
    the same evidence on each.
- **`url_pipeline.py`.**
  - `VenueToResolve.place` holds the Overture address fields. `MenuUrlDiscovery.page_html`
    (filled by `SiteFetcher`, outside the result's equality) carries the verified page.
  - With a `place_area` (`resolve_urls` loads it at the start of a run; `--base-dir`):
    - a re-check of a wrong-place page is `failed/wrong_place`, now in `WITHDRAW_REASONS`.
      It re-discovers, then withdraws through `_withdraw_menu`;
    - discovery drops a wrong-place result. A site whose every verified page is another
      place's records `failed/wrong_place`;
    - a lifecycle transfer treats it as absent.
  - Accepted saves record `place_check: "place-v1"`. The report counts
    `menu_urls_wrong_place`. Bronze's `FAILURE_REASONS` gains `wrong_place`.
  - **One placement differs from item 3's wording.** The check runs where `url_pipeline`
    accepts a result, not inside `SiteFetcher`'s candidate loop. So a dropped page is not
    replaced by the next-ranked candidate. On a shared host's sitemap (Jefes's smorefood) that
    candidate is usually another restaurant, possibly an Austin one that would pass. The
    resolver protocol and its test fakes are unchanged.
- **`python -m apps.discovery.place_sweep [--dry-run] [--base-dir]`** is item 4. A record is
  checked when:
  - it is resolved;
  - it is not a registry record;
  - its latest `menu-page` Version holds a bundle of the saved URL.

  On `helios_laptop` the dry run checked 1,602 pages and skipped 80: 74 not resolved, and 6
  whose bundle is of an older URL. It flags **55**: the 54 live records of the record's §1.5,
  plus Sarpino's `/menu`, whose Menu stream was already withdrawn but whose URL record is
  resolved. The other 4 of the 59 (Twin Peaks ×2, Haywire, Woof Gang) are already withdrawn.
- **Tests.**
  - `test/test_place_check.py`: each evidence kind, the exclusions and the chain exemption,
    pure.
  - `test/test_menu_url_reverification.py`, with the database:
    - a wrong-place re-check withdraws;
    - discovery drops a wrong-place page (`failed/wrong_place`);
    - a right-place page is saved with `place_check`;
    - no area judges nothing;
    - the sweep: a dry run writes nothing, a live run withdraws only the wrong-place
      record.

**Applied 2026-10-27 (P8-18).**
- **`helios_laptop`:** the sweep withdrew the 55 records (menu-URL `needs_review` 74 → 129).
  R4 withdrew 54 records' streams. The Gold refresh dropped all 2,503 rows they carried.
- **Pi:** restored from that database.
- **Jefes (21183):** firsthelios.com now shows no menu.

The record's §3 has the figures.
