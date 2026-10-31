# ADR-0023: Render-state exploration — menu states behind tabs, accordions and script

**Status:** Proposed 2026-10-28 (session P8-21). Accepted in part 2026-10-30 by the owner: Q1–Q3 as
recommended (see [Owner decision](#owner-decision)); Q4 (the Pi budget) and Q5 (live fetching for
step 0) are open. D2 is not built: step 0 measures first.
**Date:** 2026-10-28
**Phase:** 6 / 8 (menu coverage; ROADMAP §7 item 7, "script-loaded menus")
**Extends:** [ADR-0013](./0013-phase5-menu-pipeline.md) §4 (headless render) and
[ADR-0022](./0022-several-menu-pages-per-venue.md) (several menu pages per venue)
**Depends on:** the owner's standing rules: one universal pipeline (no per-site or per-platform
readers), no learned classifier for decisions (Amendment 19), never lose Bronze or Menu data,
no network-response sources (per-platform risk) and no PDF/image extraction until decided
**Record:** [2026-10-28-p8-21-coverage-baseline.md](../reviews/2026-10-28-p8-21-coverage-baseline.md)
(the coverage baseline this ADR's measurements come from)

## Context

A static fetch sees a page's HTML. ADR-0013 §4 renders a page once, with no interaction, when
its static text fails the classifier. Neither reaches a menu state that appears only after a
click: a tab whose panel loads by script, an accordion filled on open, or a "load more" list.

What is measured so far:
- **Coverage baseline** (P8-21, 19 reviewed real sites, static only):
  - state coverage 0.280;
  - a tab panel present in the HTML is collected (tab states 0.667);
  - a script-loaded tab panel is not. 4 states on 4 sites: 5th Street's Drinks, Brix & Ale's
    Dinner and Dessert, Café Blue's Wine.
  - 13 of 34 drawn sites (38 %) could not be labelled at all from static HTML (script shells,
    `pending_render`).
- **Synthetic** (`test_menu_coverage_eval.py`): a hidden tab panel in the HTML is covered; a
  script-loaded one is not.
- **ADR-0022's record:**
  - 45 of 300 stratum-A venues (15 %) have JavaScript-only candidates (311 candidates);
  - 7 resolved own-site menu records are stored as static script shells.
- **S6f render measurement** (laptop): a render takes 13.9 s median (p90 48.5 s) and
  1.25–1.79 GB PSS. Of 23 JavaScript-only own-site pages, a plain render found 3 menus,
  13 not-menus and 7 empty pages. **The Pi was never timed.**

**What is not measured: how many menu states need an interaction once a page is rendered.**
That decides whether interaction is worth its cost at all.

## Decision (proposed)

### D1. Measure before building (step 0, no pipeline change)

After P8-20's re-collection frees the browser:
1. Render, without interaction, the 13 `pending_render` coverage sites' homepages and their
   menu-candidate pages. Finish their labels; the first pass, then this session, then the owner
   on disagreements, as for the static set.
2. Record per state whether the plain render already shows it, and which states need a click.
   This uses `coverage_eval` on the rendered HTML.
3. Run a scripted prototype of D2 on the same sites only, outside the pipeline, and record
   states gained, wrong content (other locations, carts, modals), time and memory. On the Pi,
   only speed.

Bars for going on to D2 (proposed): interaction raises state coverage on the rendered set by
≥ 0.10. It adds no other-location or non-menu page, and stays within a time budget the owner
sets for the Pi.

### D2. If D1 justifies it: bounded, generic interaction in the render

- **Which controls.** Inside the page's main content only (not `nav`, `header`, `footer`,
  `form` or dialogs). The same chrome rule as `segment`:
  - elements with `role="tab"`;
  - elements with `aria-expanded="false"`;
  - `summary` elements;
  - elements with `aria-controls` pointing to an empty element.
- **Not clicked:**
  - links that navigate (an `href` to another URL);
  - form submits;
  - anything inside a `form`;
  - controls whose text reads as a cart or account action.

  ARIA roles and attributes decide, never class names or per-platform selectors.
- **How.** At most N clicks per page (proposed 12), each followed by a short settle (network
  idle or a fixed cap). Never two levels deep. Same origin and robots rules as today's render.
  No login, no form, no CAPTCHA.
- **What is stored.** One serialized DOM per page, as today. Each opened panel's DOM is
  appended in page order, inside an element marked with its control's label, so `segment-v2`
  reads one document.
  - The Capture records `render = headless+explore` and the controls clicked.
  - Evidence locators keep pointing at blocks of that one document.
  - A Version is still one bundle, so there's no Bronze or segmenter change.

### D3. Out of scope here

- Network responses (an API's JSON behind a tab): the owner's per-platform concern.
- PDF and image menus: a new dependency, owner decision pending.
- Bot challenges and 403s (2 of 34 drawn sites): never defeated (ADR-0013 §4).

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| **A. Plain render only (today)** | No new behaviour; measured cost | Misses every click-revealed state; size unknown |
| **B. Generic ARIA-bounded interaction (D2)** | One universal rule; works on any site that marks its tabs and accordions | Cost per page multiplies; risk of opening carts, modals, other locations; sites without ARIA markup are missed |
| **C. Network-response capture** | Sees data before it is drawn | Per-platform schemas; the owner ruled it out for now |
| **D. Per-platform readers** | Precise where they apply | Rejected: one universal pipeline |
| **E. Separate Capture per state** | Clean provenance per state | A bundle/Version contract change (ADR-0005), and several Versions per page per run |

## Consequences

- **Step 0 is cheap.** It needs the browser for 13 sites (about 100 renders) and a labelling
  pass; it changes no stored data.
- **D2 changes stored Captures for interacted pages.** The Version's text hash changes, so
  those pages are re-extracted on the GPU. That is the owner's GPU/LLM call.
- **Pi time.** D2 multiplies render time per page. The Pi has never been timed for renders.

## Owner questions

- **Q1. Order.** Run step 0 (measure, no build) after P8-20's re-collection, before deciding
  on D2? *Recommended.*
- **Q2. Control set.** Only ARIA roles and attributes plus `summary` (no class names, no text
  vocabulary except a cart/account veto)? Or allow a short text vocabulary for buttons such as
  "Dinner" / "Drinks"? *Recommended: ARIA only.*
- **Q3. Storage.** One appended DOM per page (D2, no contract change), or a Capture per state
  (option E)? *Recommended: one DOM.*
- **Q4. Budget.** A click cap per page (12 proposed) and a Pi time budget per page. What
  should the Pi budget be?
- **Q5. Scope of step 0's prototype.** Laptop for quality, Pi for speed only (standing rule).
  Is the prototype allowed to fetch live, politely, into a scratch cache, as this session did?

## Owner decision

2026-10-30, "accept all recommendations":
- **Q1.** Run step 0 before deciding on D2. Step 0 renders the `pending_render` sites without
  interaction, labels them, then prototypes D2 outside the pipeline. P8-20's re-collection has
  freed the browser.
- **Q2.** If D2 is built, its controls are ARIA roles and attributes plus `summary` only, with a
  cart/account veto. No class names, no menu-word vocabulary.
- **Q3.** One appended DOM per page: no Capture-per-state contract change.
- **Open:**
  - Q4, the Pi time budget per page (no number was proposed);
  - Q5, whether step 0 may fetch live, politely, into a scratch cache (asked, not recommended).
