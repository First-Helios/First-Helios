# ADR-0027: Menu coverage: script-shell pages, PDF and image menus

**Status:** Proposed 2026-11-01 (session P8-21). **Accepted 2026-11-01 by the owner, all as recommended** (see [Decision](#decision-2026-11-01)). Nothing built yet. Measurement plan and owner
questions below; PDF and image menus need a new dependency, which is the owner's decision.
**Date:** 2026-11-01
**Phase:** 6 / 8 (menu coverage; ROADMAP §7 item 7)
**Extends:** [ADR-0013](./0013-phase5-menu-pipeline.md) §4 (the renderer) and Amendments 3–4
(`menu_pdf_only`), [ADR-0022](./0022-several-menu-pages-per-venue.md),
[ADR-0026](./0026-homepage-as-menu-page.md)
**Depends on:** one universal pipeline (no per-site or per-platform rules), no manual entries,
polite fetches, the coverage harness (`apps/menu_pipeline/coverage_eval.py`)
**Record:** [2026-10-28-p8-21-coverage-baseline.md](../reviews/2026-10-28-p8-21-coverage-baseline.md);
sizing script `var/p8-21/coverage2/covsize.py` (worktree `p8-21-d2prime`, untracked)

## Context

The owner set coverage as the next focus after ADR-0025 D2′ (ADR-0025, Owner answers, Q4).

### Where venues stand (`helios_laptop`, read-only, 2026-11-01)

| Venues with a resolved website | 8,085 |
|---|---|
| A resolved own-site menu record | 1,800 (22 %) |
| Platform records only | 122 |
| **No menu record** | **6,163 (76 %)** |

The latest discovery verdict on the website, for the 6,163:

| Verdict | Venues | What it means |
|---|---|---|
| `failed/no_menu_found` | 2,432 | the site answered; no page verified |
| `skipped/non_public_host` | 960 | **the host doesn't resolve** (see below) |
| `failed/http_403` | 864 | the site refuses the Helios User-Agent |
| `skipped/robots_unavailable` | 736 | robots.txt couldn't be read |
| `skipped/redirect_refused` | 262 | redirects to another host |
| `failed/http_404` | 255 | |
| `failed/menu_pdf_only` | 164 | no page verified, but a fetched page links a menu-named PDF |
| `skipped/robots_disallowed` | 161 | |
| other (social link, platform root, wrong place, not HTML, …) | 329 | |

### The three gaps in scope

1. **Script-shell pages.** A JavaScript-only candidate (`looks_js_only`) is rendered only when
   no static page verifies, and at most `MAX_RENDER_CANDIDATES` = 2 per site.
   - Of the 2,432 `no_menu_found` venues, **573** had JavaScript-only candidates in P8-20's
     discovery replay: **425 with 3 or more**, 148 with 1–2.
   - Rendering is on in production: 67 own-site and 395 platform pages were verified from a
     render.
   - The coverage set (29 sites) has script states at 0 coverage. Its two render-revealed menus
     sit on homepages (ADR-0026 measured 0 of 34 rendered homepages pass).
2. **PDF menus.** 164 venues end at `menu_pdf_only`, and the coverage set's PDF states are at 0.
   The pipeline never reads a PDF (ADR-0013 Amendment 3). Reading one needs a PDF text library
   (a new dependency); a scanned PDF needs OCR as well.
3. **Image menus.** No count yet: nothing detects them. The coverage set's image states are
   at 0. Reading them needs OCR or a vision model (a new dependency, and GPU or CPU time).

### A finding outside the three: dead domains are logged as `non_public_host`

`SiteFetcher._is_public_host` returns False when DNS resolution fails, so a dead domain is
recorded as `skipped/non_public_host`. Sampled hosts (`www.kickdrumburgers.com`,
`hemingwayrb.com`, `locations.arbys.com`) don't resolve, while a working domain does. So about
960 venues (12 % of those with a website) point at a dead domain. Nothing can be fetched; the
reason code is misleading, and the records will be retried on `RECRAWL_WINDOW` forever.

## Decision (proposed): measure each gap, then build in order of gain per cost

### M1. Script shells: render more candidates (no new dependency)

- **Sample:** 40 venues, seeded, from the 573 `no_menu_found` venues with JavaScript-only
  candidates (stratified: 30 from the 425 with ≥ 3 candidates, 10 from the 148).
- **Measure:** render every JavaScript-only candidate (up to `MAX_MENU_PAGES` = 6), production
  `BrowserRenderer`, scratch cache, the ADR-0023 Q5 policy (robots, same-site redirects,
  3 s per host). Record which candidate rank verifies, and its time.
- **Labels:** Sonnet first pass on the rendered pages, then this session's re-check
  (`menu` / `not_menu`, and the venue's own location).
- **Result decides:** raise `MAX_RENDER_CANDIDATES` (to 4 or 6) if pages beyond the second
  verify and are menus, with the render time per venue as the cost. The coverage harness is
  re-run with the change.

### M2. PDF menus: size the text layer before choosing a library

- **Sample:** 40 venues from the 164 `menu_pdf_only`, seeded. Download the linked PDF politely
  (`SiteFetcher` rules) into a scratch directory.
- **Measure without a dependency:** whether the PDF has a text layer (font and text-operator
  objects, versus page images only), its page count and size.
- **Then the owner chooses** (Q2): a text library (`pypdf`, pure Python, MIT; or `pdfminer.six`)
  for text-layer PDFs, and whether scanned PDFs are worth OCR.

### M3. Image menus: count them first

- **Measure offline** from the stored and cached pages of the 2,432 `no_menu_found` venues:
  pages with a large image whose `src`, `alt` or link names a menu, and pages whose menu
  candidate is only an image gallery.
- **The coverage set's image states** give the read rate needed (items per image).
- **Then the owner chooses** (Q3): OCR (Tesseract, a system package plus a binding) or a vision
  model on the laptop GPU, or neither.

### Not in this ADR

- `http_403` (864) and `robots_unavailable` (736): the User-Agent policy and robots handling
  are fetch policy, not menu reading. Sized here only.
- The dead-domain reason code: a small, separate fix (Q4).

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| **Measure M1–M3, then build by gain (proposed)** | Spends render time and dependencies only where they pay | Slower to first gain |
| Raise the render cap now | No measurement; no dependency | Render time grows on every site; ADR-0026's homepage sample found 0 of 34 |
| Add PDF and OCR together | One change | Two dependencies before knowing the text-layer share |
| Status quo | Nothing to run | 76 % of venues with a website keep no menu |

## Consequences

- M1 and M3 are read-only or scratch-only; M1 renders live pages politely (about 40 venues ×
  up to 6 pages, 15 s median per render on the laptop).
- M2 downloads about 40 PDFs into a scratch directory, no new dependency.
- Each build step that follows is its own amendment or PR, measured on the coverage harness.

## Owner questions

- **Q1. Order.** M1 (render), M2 (PDF), M3 (image) in that order? *Recommended:* M1 needs no
  dependency; M2's text-layer share decides whether a small library suffices.
- **Q2. PDF dependency.** If M2 shows most menu PDFs have a text layer, add `pypdf` (pure
  Python) as a runtime dependency for text-layer PDFs, and leave scanned PDFs unread?
  *Recommended*, pending M2.
- **Q3. Image menus.** Measure only (M3) for now, and decide OCR or a vision model after the
  count? *Recommended:* the count is unknown, and both options are heavy.
- **Q4. Dead domains.** Record a DNS failure as its own reason (`dns_unresolved`, a new Bronze
  failure reason, no migration) instead of `non_public_host`, and keep it out of the
  `RECRAWL_WINDOW` retry until the Overture website changes? *Recommended:* small and generic.
- **Q5. Render budget.** Is about 10 minutes of headed-browser time per 40 venues on the laptop
  acceptable for M1, and later for production runs if the cap is raised? *Recommended:* yes for
  M1; production cost is decided with M1's numbers.

## Built: `dns_unresolved` (Q4, 2026-11-01)

Built in session P8-21 as decided (no migration: the reason codes live in the capture contract,
ADR-0011; the DB checks only their shape).
- **Reason.** `SiteFetcher._host_refusal` replaces `_is_public_host` and says why a host isn't
  fetched. A name `getaddrinfo` answers with "no such name" (`EAI_NONAME`, `EAI_NODATA`) or with
  no address is `failed/dns_unresolved`. Any other resolver failure (`EAI_AGAIN`, a timeout) is a
  `network_error`, retried as before, so a network outage during a run can't mark live venues
  dead. A label IDNA can't encode and a private address stay `skipped/non_public_host`.
- **No retry.** Discovery skips a website whose latest menu-URL capture is `dns_unresolved`,
  whatever its age (`UrlDiscoveryReport.dns_unresolved_skipped`). Captures are keyed by the
  website URL, so a changed Overture website is a new URL and is tried on its first run.
- **Existing records.** Nothing is rewritten. The ~960 `skipped/non_public_host` dead domains
  are retried once when their `RECRAWL_WINDOW` cooldown ends, recorded as `dns_unresolved`
  then, and not retried after that.
- The renderer's sub-request policy (`render.py`, its own `non_public_host` for blocked
  sub-requests) is unchanged: it only runs on a host the static fetch already resolved.
