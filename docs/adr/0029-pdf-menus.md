# ADR-0029: Reading PDF menus with `pypdf`

**Status:** Proposed 2026-11-18 (session P8-22). The dependency PR (#164) adds the dependency
only (this ADR, `pyproject.toml`, `uv.lock`); the reader is built in a PR stacked on it
(2026-11-19, P8-23, see "Built").
**Date:** 2026-11-18
**Phase:** 6 / 8 (menu coverage; ROADMAP §7 item 7)
**Extends:** [ADR-0027](./0027-menu-coverage-script-pdf-image.md) (M2 and the decisions on it),
[ADR-0013](./0013-phase5-menu-pipeline.md) Amendments 3–4 (`menu_pdf_only`) and Amendment 35
(numeric tables), [ADR-0010](./0010-website-and-menu-url-resolution.md) D2.4 (the 3 MB cap)
**Depends on:** one universal pipeline (no per-site or per-platform readers), no manual entries,
polite fetches (robots, public addresses, the body cap)
**Record:** [2026-11-01-p8-21-coverage-m1-m3.md](../reviews/2026-11-01-p8-21-coverage-m1-m3.md)
(M2); this ADR's measurements below. Scripts untracked in the session scratchpad.

## Context

- **164 venues end at `failed/menu_pdf_only`** on `helios_laptop`: no HTML page verified, but a
  fetched page links a menu-named PDF. The pipeline never reads a PDF (ADR-0013 Amendment 3).
- **M2** (40 of the 164, seeded): 37 link a menu PDF. 15 were downloaded; 18 were refused
  because the link redirects to a site builder's file CDN on another host; 3 exceed the 3 MB cap;
  1 robots. 9 of the 10 distinct menu PDFs have a text layer (standard-library scan).
- **Decisions on M2** (ADR-0027, accepted under the owner's delegation, 2026-11-17): a PDF link
  may follow a cross-host redirect (PDF links only; robots on the final host, public address and
  the cap kept), built with the reader; the 3 MB cap stays; this dependency PR comes before any
  build; nutrition PDFs are noted here (D5).

### Measured with `pypdf` 6.21.4 (scratch environment, not the project's)

The 15 downloaded files (12 distinct): `PdfReader(...).pages[i].extract_text()`, plain mode.

| | Files | Detail |
|---|---|---|
| Clean text | **11 of 12 distinct** | Latin share ≥ 0.993, real words ≥ 0.985; no garbled custom encodings |
| Little text | 1 | the mostly-image PDF M2 found (60 characters) |
| Time | all | 0.02–0.6 s a file, 25 pages the largest |
| Errors | 0 | warnings only (CFF font encodings without `fontTools`; the text still read correctly) |

The production verifier (`classifier-v2+v3`, unchanged) on the text written as one `<p>` per
line, with the PDF's own URL:

| PDFs (distinct) | Verified as menu |
|---|---|
| Text-layer menus | **9 of 9** (probabilities 0.77–1.0 on both models) |
| Mostly-image menu | 0 of 1 (0.08 / 0.61) |
| Nutrition tables | 1 of 2: Olive Garden rejected (0.72 / 0.05); Pizza Twist accepted (0.93 / 0.98) |

Prices in the 9 verified menus: 5 print prices on most dishes (21–57 marked prices each); 3 print
one or none (one is a "sample menu"); Torchy's gluten-conscious menu prints calories only
("CAL 643"), which today's reader would read as bare prices (D5).

**Expected gain** (an estimate, to be measured on the coverage harness at build): with the
redirect rule, up to 33 of M2's 37 linked PDFs are fetchable; about 3 in 4 of the downloaded
files are menus the verifier accepts; 5 of the 9 verified print prices. Scaled to the 164,
roughly **80–110 venues gain a menu record and 45–65 gain prices**, against 1,800 own-site menu
records today.

## Decision (proposed)

### D1. The library: `pypdf`

`pypdf` (BSD-3-Clause, pure Python, no runtime dependencies on Python ≥ 3.11; the optional
`crypto`, `image` and `fonts` extras are not taken). Pinned `>=6.21.4,<7`: 6.21.4 is the newest
release over two weeks old; 7.0 (2026-11-06) is a new major, left for a later bump.

- **In the main dependency list, not the `menu` extra.** The reader is a pure parsing module
  (`packages/helios_parsing`), so CI's tests and `mypy --strict` see it (`pypdf` ships type
  hints); the `menu` extra is for the model runtime and the browser, which CI doesn't install.
  The API image grows by about 1 MB of pure Python and never imports it.
- **Not `pdfminer.six`:** larger, slower, and its layout analysis isn't needed (D3).
- **No OCR.** A PDF without a text layer is counted (`failed/pdf_no_text`) and left unread;
  image menus are ADR-0027's M3, a separate decision.

### D2. Where a PDF enters: discovery's `menu_pdf_only` branch

Discovery keeps its order: HTML candidates first, render, the homepage (ADR-0026). Only when
nothing verifies and `menu_pdf_links` found a link (today's `menu_pdf_only`) does it fetch the
first linked PDF:
- `SiteFetcher` rules, with **one change for PDF links only**: a redirect to another host is
  followed (the decision above). The final host's robots.txt is obeyed, its address must be
  public, and the 3 MB cap applies (`too_large` counted). An HTML link keeps the same-site rule.
- The response must be a PDF (`application/pdf`, or `%PDF-` magic under a generic type);
  anything else is `failed/not_pdf`.
- The verified PDF URL is the venue's menu URL, as an HTML page's would be (ADR-0010), and later
  fetches (`page_bronze`) read it the same way. One PDF per venue in this step; several menu PDFs
  per venue would follow ADR-0022's cap later, if the first step pays.

### D3. The reader: text lines as an HTML page, then the existing pipeline

`packages/helios_parsing/pdf.py`, segmenter name `pdf-v1`:
- `pypdf` plain extraction, page by page, under a page limit (40) and the body cap; an
  encrypted or unreadable file is `failed/pdf_unreadable`, one with under 200 characters of text
  `failed/pdf_no_text`.
- Each non-empty line becomes one `<p>` of a minimal HTML document (page breaks as `<hr>`), and
  the existing `segment` reads it. So the page check, the bundle (`body` = the PDF bytes,
  `content_type` `application/pdf`), chunking, extraction, the validator, [5b]–[5d], Gold and
  the Evidence locators (`blocks:pdf-v1:<block>[s:e]`) are unchanged.
- **Plain mode, not layout mode:** plain keeps a multi-column menu's reading order; layout mode
  sets the columns side by side on one line (measured on Torchy's two-column page).

### D4. The page check: the production verifier, measured on PDFs at build

The verifier runs on the derived HTML (9 of 9 text menus, D1's table). A false accept costs what
it costs on HTML: extraction time, and prices only where the reader finds them (D5).
The build re-measures it on every PDF the coverage harness and M2 hold.

### D5. Numbers that aren't prices: nutrition PDFs and calorie markers

- **Nutrition PDFs.** `pypdf` prints a nutrition table's row as one line ("670 380 42 3.5 0 300
  1600 48 2 3 24"), and the dish names apart from their rows. Amendment 35's `table_cells` needs a
  block per cell after a name block, so it never fires: today's reader takes each row's last
  number as a bare price (Olive Garden: 282 bare readings). Splitting rows into cell blocks makes
  it worse (3,007), because the names aren't adjacent. **The build adds a reader rule:** a block
  of 6 or more number-only tokens is a numeric table row and gives no bare reading. It is
  generic (an HTML table rendered one row per block meets it too), so it is a validator version
  bump, measured on every labelled set as Amendment 35 was.
- **Calorie markers** ("CAL 643", "calories: 610 – 920") are read as bare prices on HTML pages
  today: 143 Gold rows on 6 subjects (Pokeworks, Quiznos) on `helios_laptop`. That fix is
  separate and doesn't wait for this ADR (ADR-0013 Amendment 36).

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| **`pypdf`, text lines as HTML (proposed)** | Pure Python, no system packages; everything after the reader unchanged | Text-layer PDFs only |
| `pdfminer.six` | Layout analysis, more encodings | Larger and slower; layout not needed |
| `pymupdf` | Fast, renders pages for OCR later | AGPL; a compiled wheel |
| OCR (Tesseract) now | Reads scanned PDFs too | A system package; 1 of 10 menu PDFs needs it |
| Status quo | Nothing to add | 164 venues stay at `menu_pdf_only` |

## Consequences

- One new runtime dependency (`pypdf`), pure Python; `uv.lock` gains one package.
- No schema change: PDF pages use the existing Capture, bundle and Menu contracts. New Bronze
  failure reasons (`not_pdf`, `pdf_unreadable`, `pdf_no_text`) live in the capture contract
  (ADR-0011), as `dns_unresolved` did.
- A fetch-policy change for PDF links (cross-host redirects), limited to PDF links.
- The build, after this merges: the reader, the PDF fetch branch, D5's reader rule (a validator
  bump), tests, then a coverage-harness and M2 re-measure before any laptop run.

## Owner questions

- **Q1. The dependency.** Add `pypdf >=6.21.4,<7` to the main dependency list (this PR)?
  *Recommended:* yes; CI then tests the reader.
- **Q2. Placement.** Main list (recommended) or the `menu` extra (smaller API image, but CI
  wouldn't test or type-check the reader)?
- **Q3. Build order.** After this merges: reader + fetch branch + D5's rule in one PR, measured on
  the coverage harness and M2's PDFs, then a laptop discovery re-run of the 164 `menu_pdf_only`
  venues? *Recommended.*

## Built (2026-11-19, session P8-23; stacked on this ADR's dependency PR, not merged)

Built under the owner's delegation for the decisions within the P8-23 plan; the record is
[2026-11-19-p8-23-pdf-reader.md](../reviews/2026-11-19-p8-23-pdf-reader.md). The owner merges
the dependency (#164) and the build; no PDF data reaches the public database before that.

- **D3** `packages/helios_parsing/pdf.py` (`pdf-v1`), as decided: plain extraction, at most 40
  pages, one `<p>` per line, `<hr>` between pages, `pdf_unreadable` (encrypted or unopenable) and
  `pdf_no_text` (< 200 characters). **Change from the text above:** Evidence locators keep
  `segment-v2`, the segmenter that makes the blocks from pdf-v1's document (a bundle's locators
  must name its segmenter); `pdf-v1` is recorded in the menu-page Version payload (`reader`), and
  the bundle holds the PDF's bytes (`body`) and the document (`rendered_dom`).
- **D2** discovery reads the first linked menu PDF when nothing verifies; a PDF link may redirect
  to another host when it ends in a PDF there (robots.txt per hop, public addresses, the 3 MB
  cap). The link is the menu URL (signal `pdf`); a saved PDF menu is re-verified by a fresh read.
  Site Captures: `menu_pdf_only` (unfetched or rejected by the page check), `not_pdf`,
  `pdf_unreadable`, `pdf_no_text` (the last three also withdraw a saved PDF menu, as `not_html`
  does). Later fetches (`page_bronze`) read a PDF response the same way; a `.pdf` link that
  answers otherwise is `failed/not_pdf`.
- **D4** the production verifier on the derived HTML: 10 of M2's 11 distinct text PDFs accepted
  (every text menu, plus Pizza Twist's nutrition PDF); Olive Garden's nutrition PDF rejected.
- **D5** `validator-v13`: a block of at least 6 number-only tokens that are at least two thirds of
  its tokens is a numeric table's row (no bare reading, no `bare_page` vote; money still reads).
  Olive Garden 282 bare readings → 0; 0 of 2,504 labelled or published texts change; on
  `helios_laptop`'s stored texts 2 of 2,010 change (one accepted row becomes unpriced).
