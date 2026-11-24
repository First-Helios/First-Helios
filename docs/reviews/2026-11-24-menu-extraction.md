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

## Freshness rollout on the merged revision

[PR #186](https://github.com/First-Helios/First-Helios/pull/186) merged at
08:50 UTC on November 24. All six head checks passed. There were no reviews,
inline comments or conversation comments. Merge commit `5fa7033` has the same
tree as the reviewed head `340edd6`. The measurements used that merge, a
private PostgreSQL 16 restore of `helios_work-2026-11-24-p8-23-swap5.dump`
(SHA-256 `a9af13914e6ee486b656e87a9590cc470640768e85b44adc13cd42c3418c1d74`)
and a disposable copy of the laptop replay directory.

### Additional versions on repeat captures

**868 additional page versions in 1,406 consecutive capture pairs** across
907 distinct menu URLs. The old payload changed in 414 pairs (29.4%). The
merged rule changed in 1,282 (91.2%). The difference is 61.7 percentage points.
Each pair here belongs to one record, so a changed URL contributes one version.
The archive contains 6,487 successful menu-page captures overall. To associate
unchanged captures with a record unambiguously, the comparison requires one
historically stable record and target per endpoint, matching the stored target
URL. It compares adjacent successful captures in fetch-time and capture-ID order,
breaking the sequence at any failed or skipped capture. Shared URLs and target
switches are outside this estimate. Counts pool multiple crawl intervals.

The comparison carries the actual old version payload forward through unchanged
captures and checks the stored blocks against its text hash. The new comparison
adds the merged writer's document identity (final endpoint after the scheme,
content type, and rendered document or static response digest) on **both** sides.
This measures steady-state behavior. A legacy version also lacks the new
document hash, so its first successful fetch after upgrade writes a version
even for identical bytes. PDF payloads also advance from reader v1 to v2.
That first-fetch effect is separate from replaying stored versions and from the
868 recurring additions. If all 2,863 currently eligible records refetch successfully
with identical inputs after the method replay, that first recrawl adds another
2,863 cached extractions, zero inference chunks and about 5.4 hours on the Pi.
Failures, withdrawals and changes to the URL set will alter that scenario.

A seeded draw (186) of **16 of the 868 additions** found **0 changed extracted
menus and 16 instances of incidental churn**. Both documents were interpreted
using the same saved answers. The shaped LLM sections, items, variants and prices
matched in all 16, as did parsed JSON-LD menu items and offers. In 15 pairs all
parsed JSON-LD matched. Spice Garden (capture 26947 → 40588) changed the schema
representation of the same five image URLs. Other inspected differences included
WordPress nonces at Twin Isle (27034 → 40964), a cache timestamp at Kobe
(27117 → 40479), and an analytics script at Yamas (40351 → 42296). A menu change
can still matter even with identical visible text, as the removal test below shows.

### Extraction cost

| Workload | Pages due or version-triggered | Pages fully covered by saved answers | Chunks needing inference | Estimated extraction wall time |
| --- | ---: | ---: | ---: | --- |
| One-time method upgrade on stored versions | 2,863 | 2,863 | 0 | 68 min laptop or 5.4 h Pi |
| All changed versions across the archived recrawls, using the archive-end cache | 1,282 | 1,282 | 0 | 30 min laptop or 2.4 h Pi |
| Same recrawls, assuming only the preceding capture's page and exact chunk answers survive | 1,282 | 931 | 2,324 | About 3.6 h with Pi writes and laptop GPU inference |
| Increment attributable to the document rule, included in both recrawl rows | 868 | 868 | 0 | 21 min laptop or 1.6 h Pi |

**Measured.** The production due query returned 2,863 reinterpretations.
Every one passed the page-answer identity and expected-chunk-count checks.
The first 40 in queue order ran through the production classifier, interpretation,
evidence and committed Menu writes with `extract --no-model` in **56.7 seconds**
on the laptop with fsync enabled. All 40 used page answers, with zero failures or
refused model calls. The recrawl counts use archived successful versions as
extraction triggers, conditional on the record still being eligible when extraction
runs. All 1,282 later texts were already present at archive end. Looking up a
future capture that way understates live inference for changed text.

**Estimated.** In the preceding-capture scenario, exact chunk comparisons leave
351 pages with 2,324 missing chunks. This assumes a complete previous extraction
and ignores reusable answers from other pages and earlier crawls. All misses
belong to changes the old rule also detected. The laptop estimates scale the
40-page timing by page count. The Pi estimates use the earlier measured 532
cached pages/hour. The GPU scenario adds 931 / 532 hours to the 2,324 misses
at the historical mixed-run rate of 1,813 inferred chunks in 5,289 seconds.
Page size, DB speed and cache coverage affect these estimates. They exclude
fetching, rendering, Gold refresh and deployment. [Pi and GPU timings](2026-11-19-p8-23-pi-long-run.md)

### Rollout decision and correctness

The database regression first selected the structured $6.00 Queso price in Gold.
Removing only JSON-LD caused a new version with the same visible text. Extraction
reused the page answer with zero inference, wrote an empty structured successor,
and a fresh Gold projection selected zero prices from the former structured page.
The monthly packet regression used the production model and classifier identifiers
with a fixture model response. Its newly extracted page exported the saved chunk
answer under the merged method key. A separate run of the actual monthly packet
over November 23 drew 10 of 374 historical candidates and exported 10 answer files.

**Recommendation.** Stage the upgrade with the saved-answer replay. Budget about
5.4 hours of Pi extraction for that replay plus the first successful refetches of
legacy records. The maintainer should decide whether to accept the recurring
version and database-write volume (868 extra versions plus their downstream
extractions in this cohort), or require a narrower document fingerprint
before enabling a full production recrawl. Any narrower rule should retain the
structured-price removal and DOM interpretation regressions. Card extraction and
OCR remain experimental and hub following stays opt-in.

### Reproduction

From the follow-up checkout with the menu extra, local verified models and
swap-5 replay files, run the following in Bash. The helper prints the counts,
sampled capture IDs and interpretation comparisons. The JSONL contains the
before/after bundle paths for inspecting the original documents.

```bash
set -eu
export PATH="$PWD/.venv/bin:$(pg_config --bindir):$PATH"
scratch=$(mktemp -d)
export PGHOST="$scratch"
initdb -D "$scratch/db" -A trust >/dev/null
pg_ctl -D "$scratch/db" -o "-k $scratch -c listen_addresses=''" -l "$scratch/postgres.log" start
trap 'pg_ctl -D "$scratch/db" stop -m fast' EXIT
createdb measurement
pg_restore --no-owner --no-acl --exit-on-error -j4 -d measurement \
  var/laptop-run/helios_work-2026-11-24-p8-23-swap5.dump
psql -d measurement -c "select setval('menu.admission_fence', txid_current(), true)"
mkdir -p "$scratch/cache/var"
cp -a --reflink=auto var/replay "$scratch/cache/var/"
export DATABASE_URL="postgresql+psycopg:///measurement?host=$scratch"
PYTHONPATH=. python docs/reviews/measure_pr186.py "$scratch/cache" "$scratch/pairs.jsonl"
python -m apps.menu_pipeline.spot_check --run-id 20261123T000000Z \
  --until 2026-11-24T00:00:00Z --base-dir "$scratch/cache" --out-dir "$scratch/packet"
jq '[.pages[] | select(.answers)] | length' "$scratch/packet/manifest.json"
createdb -T measurement timing
DATABASE_URL="postgresql+psycopg:///timing?host=$scratch" \
  python -m apps.menu_pipeline.extract --no-model --limit 40 --base-dir "$scratch/cache"
createdb regression_test
DATABASE_URL="postgresql+psycopg:///regression_test?host=$scratch" HELIOS_STRICT_DB_TESTS=1 \
  pytest -q test/test_menu_extraction.py
```
