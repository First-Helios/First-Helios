# Menu extraction experiments, 2026-11-24

## Repeated cards

The checked-in smoke corpus is under `test/fixtures/menu-review/{pages,labels}`.
Run `python -m apps.menu_pipeline.card_shadow test/fixtures/menu-review` to compare
proposals to labeled item, variant and price triples and count residual requests by page.
The extractor only proposes repeated two-block cards with one explicit dollar price.
The validator must cite the name and price inside the same card.

On the existing P5-14 corpus (`var/menu-eval/corpus/p5-14`), the reader proposed 14
of 3,273 expected price combinations across 72 pages. All 14 matched. Both paths
required 607 chunks. Two pages had proposals. These are historical evaluation
pages. The small redistributable fixtures exercise behavior and do not estimate
field precision.

A paired llama-server run on the smaller of the two matching pages, `3117830345c5`,
used the local Qwen3-4B-Instruct-2507-Q4_0 model. The HTML SHA-256 was
`98e77f850668202c16ee39c340fe54931094c5375bce1e988a034e98b4ee9598`.
Each route ran serially on the same document. Baseline ran first, so timing includes
possible cache warmth on the second route. Neither route wrote a menu.

| Route | Model requests (chunks) | Model wall seconds | Accepted priced rows | Exact matches out of 32 | Duplicates removed |
| --- | ---: | ---: | ---: | ---: | ---: |
| Existing | 2 | 116.5 | 32 | 25 | 0 |
| Cards plus residual text | 2 | 63.8 | 30 | 23 | 0 |

Run `python -m apps.menu_pipeline.card_shadow PAGE.html --server http://localhost:8080`
against the configured model. The command prints both sets of accepted rows. Scores
above count overlapping triples with multiplicity, using case-folded names, empty
variants for base prices, and decimal amounts. The lower recall keeps the new route in
shadow mode.

## Discovery

A seeded draw of 10 of 22 distinct page IDs where v2 and v3 disagreed in the archived
P5-30 R1(b) crawl yielded three menus, two individual products, two empty captures,
two gambling-site pages and one insurance article. Two menu pages showed the same
venue's starters. The archived observations do not establish new venue yield or
browser-time savings. The page IDs, labels, URLs, input hashes and seed are in
[the draw](../../test/fixtures/menu-review/disagreements.json).

The static discovery experiment follows menu links from rejected original candidates
using remaining candidate slots and the existing verifier. A replayed hub fixture
reaches a verified child menu with zero renders. On the 19 reviewed held-out site
fixtures, both settings found 11 of 37 expected pages and covered 12 of 40 menu
states. Both collected four other-location pages before downstream place checks.
Neither rendered pages. Eleven archive misses in each run limit what this replay
can establish about new links. This result keeps hub following opt-in.

Run `python -m apps.menu_pipeline.coverage_replay FIXTURES HTTP_CACHE` with and without
`--follow-menu-hubs`. The runner reads the frozen cache and reports per-site URLs, misses,
coverage and location counts. This run used `var/menu-eval/coverage/real/held` and the
P8-21 coverage cache from the page-structure worktree. The same switch is available in
`apps.discovery.resolve_urls` for a measured crawl.

## PDF layout

On a generated one-page menu, Poppler text extraction and a rasterized Tesseract pass both
read the three lines and returned word boxes. The layout inspector emits single-price rows
and aligns multi-price rows to horizontally overlapping size headers. The column regression
also checks an ambiguous multi-price row without headers. Layout and OCR results remain
offline pending a representative PDF evaluation. For a real scan, the two-page M2
capture 07 yielded 12 and 4 words from its text layer. OCR returned 179 and 321
words and proposed 10 and 2 priced rows respectively. Some headers were garbled,
and these row counts do not establish item or price accuracy. The production text reader accepts short
text menus containing letters and a marked dollar price for the usual verification.
