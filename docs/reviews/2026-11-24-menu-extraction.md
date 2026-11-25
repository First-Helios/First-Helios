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

## Venue-to-API price benchmark

Each label names an establishment, source URL, visible menu state, item, variant
and USD price. The reader checks the saved discovery URL, Bronze version and
bundle, original chunk answers, repaired rows, validator verdicts, stored prices,
Gold and the response to an actual `GET /v1/venues/{id}/menu` request. It reports
one first loss per label and the change in correct prices per venue relative to
the frozen baseline. Prices are credited on the labelled page of the requested
venue. A known alternate location is counted separately even if it serves the
same dish at the same price. Names and variants ignore case and extra spaces.
A numeric diameter with or without the inch mark is an explicitly allowed alias
on the six Warpath labels.

### Checked-in controls

From a clean checkout with uv, PostgreSQL 16 and PostGIS installed, run
`test/fixtures/venue-prices/run.sh` as a regular user. The command makes a private
database, runs migrations and replays two authored sites through discovery,
Bronze, extraction, Gold and the API. It prints each expected price and its
outcome, then removes the temporary cluster. HTML, saved answers, labels and
expected outcomes are tracked. This is a fixed census of the fixtures.
The verifier and model answers are scripted.

Juniper Counter served 3 of 6 labelled prices. The interpreter recovered the
large tea from visible text even though the scripted answer omitted it. Two
pizza diameters disappeared during answer repair. The dinner button was present
but its menu state was absent. East Pier served 0 of 1 correct prices and
published one wrong-location menu. Its West Pier chowder had the exact same name
and amount as the East Pier label. The unweighted mean venue recall was 25%.

### Field baseline

The swap-5 snapshot supplied real bundles, saved model answers, Menu pages and
Gold. Exact bundle SHA-256 values and GERS IDs are in the [field manifest](../../test/fixtures/venue-prices/swap5.json).
The separately archived Café Blue kids page established its two expected prices
even though discovery had not saved the URL. Its HTTP body digest is in the same
manifest. Counts are a sample of labelled prices per venue. No field-wide
precision or monthly prevalence is inferred.

| Venue and template | Correct at the API | First loss among the sampled prices |
| --- | ---: | --- |
| Café Blue, separate WordPress daypart pages | 4 / 6 | Kids menu URL absent from resolved discovery records, losing Popcorn Shrimp and Chicken Fingers |
| Brix and Ale, breakfast and dinner tab panels | 4 / 4 | All four served |
| Warpath Pizza and Pub, size-labelled price runs | 0 / 6 | The model associated each amount with its diameter. Answer repair stripped the numeric labels from all six |
| Hippie Picnik, food-truck menu | 2 / 3 | The $8.00 answer named the bratwurst category instead of the labelled Plain Jane item |
| TenTen, two-column happy-hour PDF | 3 / 3 | All three served. The item/price associations were checked against the PDF layout |

**13 of 22** expected triples reached the API, with **66.7% mean venue recall**.
The two-digit size tokens survived in the raw Warpath answers. The persisted
rows retained all six amounts as base prices. Trying a larger model or earlier
card extraction would leave the observed repair rule in place.

Café Blue, Brix and Ale and Warpath were chosen to exercise separate pages,
tabbed states and variants. The last two venues were a separate draw, labelled
from the documents before inspecting saved answers or API results. On swap-5,
take the latest non-rendered menu-page version per base GERS key (no `|`), keep
HTTPS targets and take the lexicographically first URL and key per host.
Order by PostgreSQL `md5('186-holdout:' || url), url`. The first HTML document
and first PDF are ranks 1 and 12. The manifest freezes both source documents.
These two new domains contribute six labelled prices.

Against a disposable restore of the swap-5 dump with its matching replay
directory, run the following on the baseline and again after a candidate's
extraction and Gold refresh. The field reader uses a read-only transaction.
Each row carries its baseline outcome. `gained` and `lost` count changes in
correct published prices, preserving the venue denominator when there is no menu.

```bash
uv run python -m apps.menu_pipeline.venue_price_eval \
  test/fixtures/venue-prices/swap5.json --base-dir "$SCRATCH_DEPLOY" > venue-prices.json
jq '.venues[] | {venue, served, expected, gained, lost, counts}' venue-prices.json
```

### Paired card experiment on the laptop GPU

Both card-positive pages in the 72-page P5-14 corpus were run on the RTX 3070
laptop GPU with the pinned Qwen3-4B-Instruct-2507-Q4_0 model. Each page ran
baseline first and cards plus residual text second. Timing includes prompt-cache
warmth and has one observation per route per page. Exact scores match the
multiplicity of labelled item, variant and decimal-amount triples in the usual
evaluation scope. Wine sections are excluded by the existing gold label reader.

| Page | Route | Inference chunks | Model seconds | Accepted | Exact / expected | Omissions | Unmatched accepted | Duplicates removed |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 3117830345c5 | Existing | 2 | 9.9 | 32 | 25 / 32 | 7 | 7 | 0 |
| 3117830345c5 | Cards and residual | 2 | 6.9 | 30 | 23 / 32 | 9 | 7 | 0 |
| 3c0cd41446bc | Existing | 20 | 77.7 | 169 | 121 / 173 | 52 | 48 | 0 |
| 3c0cd41446bc | Cards and residual | 20 | 78.8 | 168 | 121 / 173 | 52 | 47 | 0 |

Both routes required 22 chunks. The hybrid lost two exact prices in aggregate.
On the four captured HTML pages of the initial Café Blue, Brix and Ale and
Warpath price holdout (two Café Blue pages), the shadow reader proposed zero
cards. Keep this route experimental. The larger P5-14 HTML document has SHA-256
`2ad2536229715b4d89d0c21f0022a51d8b073498dc45e1e2825dccc0c37f3941`;
the smaller document's digest is in the repeated-cards experiment above.

```bash
data=var/menu-eval/corpus/p5-14
for page in 3117830345c5 3c0cd41446bc; do
  uv run python -m apps.menu_pipeline.card_shadow "$data/pages/$page.html" \
    --label "$data/labels/$page.json" --server http://127.0.0.1:8083
done
```

## Completed Pi staging replay

The Orange Pi 5 Plus ran merged revision `5fa7033` on November 24–25 UTC.
The Pi's existing worker image loaded that revision's apps, packages and config
from read-only mounts. A separate PostgreSQL 16 container on a private Docker
network held two copies of the verified swap-5 dump, `baseline` and
`measurement`. The worker used a scratch copy of the Pi's replay cache.
The public deployment and master database received no writes.

| Stage | Measured outcome | Measured time |
| --- | --- | ---: |
| Saved-answer upgrade replay | 2,863 due, 2,863 extracted from full page answers, 0 inferred or refused chunks, 0 failed pages | 8,950.5 s (2 h 29 min) |
| Immediate rerun | 0 due, 0 extracted, 0 model calls | 4.3 s |
| Gold refresh | 99,408 current menu rows, 421 price-index rows | 48 min 5 s, including worker startup |
| Rollout gate | Passed. Both snapshots had 1,233 venues with menus and a citywide median of $10.95. Zero venues gained or lost | 5 s, including worker startup |

The restore started at 22:42:03 UTC. The gate finished at 02:02:48 UTC.
The packet exported all 10 saved answer files from its 374-candidate historical
window on the Pi. The five-venue field benchmark produced byte-identical JSON
against both databases, including all 22 labelled outcomes. Local strict
`make ci` passed 2,044 tests and `alembic check` found no schema changes.

**Updated estimate.** The measured Pi throughput was 1,151.5 cached pages/hour.
At that rate the 868 incremental versions in the archive comparison would take
about **45 minutes** of extraction. A first successful refetch of all 2,863
eligible legacy records with identical inputs would take about **2 h 29 min**
of extraction. Neither recrawl was run live. Both estimates exclude fetch,
render and Gold refresh. The maintainer can schedule the saved-answer replay
and decide whether to accept that version volume before the first live recrawl.

To reproduce on an isolated Pi worker, use the restore and admission-fence
reset above, clone the restored database before replay, mount the merged source
and a copy of the matching replay cache, and point the worker at the clone.
Run these commands inside that worker. The gate's two names refer to the
disposable databases on the same isolated PostgreSQL server.

```bash
python -m apps.menu_pipeline.extract --no-model
python -m apps.menu_pipeline.extract --no-model
python -m apps.gold.refresh
python -m apps.menu_pipeline.swap_gate --public baseline --master measurement
```

The retained run directory on the Pi is
`/home/orangepi/pr186-replay.okRs3Z`. It holds the exact launch script, logs,
packet summary, gate and before/after benchmark reports. The scratch database
container was stopped after verification. The laptop has a copy of the run
evidence in `var/pr186-pi-replay/`.

## Printed pizza diameters in saved answers

Baseline `83c0b2f` reproduced six `answer_repair_loss` results at Warpath.
Cheese & Chong prints 12, 16 and 18 inches at $19, $23 and $25. Santa Rosa
prints the same diameters at $19, $24 and $26. The saved answers had all six
pairs. Preserving the number in repair also requires the validator to recognize
an inch mark in a slash suffix such as `$19.00/12"`.

The candidate uses the item's printed name and its contiguous price fields. Each
field must have one marked or decimal amount. A numeric size must occur with an
inch mark in the same field as the claimed amount. Two different amounts for
the claimed diameter make the claim ambiguous. The regressions include swapped
amounts, counts, neighboring dishes, and a size label mistaken for an item.

| Venue | Baseline served | Candidate served | Gained | Lost | New wrong diameter/price pairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| Café Blue | 4/6 | 4/6 | 0 | 0 | 0 |
| Brix and Ale | 4/4 | 4/4 | 0 | 0 | 0 |
| Warpath Pizza and Pub | 0/6 | 6/6 | 6 | 0 | 0 |
| Hippie Picnik | 2/3 | 2/3 | 0 | 0 | 0 |
| TenTen | 3/3 | 3/3 | 0 | 0 | 0 |
| The ABGB, independent domain | 0/17 | 7/17 | 7 | 0 | 0 |

The original five venues improved from 13/22 to 19/22 and from 66.7% to 86.7%
mean venue recall. The ABGB labels cover the seven consecutive dishes under
“Pizza,” including the five slice prices. We selected this domain for its mixed
layouts and recorded the 17 amounts from the document before reading its answers.
An initial candidate treated the word “Slice” in a price line as the owner of
the two whole-pie prices. The final repair excludes that case. The ABGB
therefore also served as a regression domain during development.
[Independent labels and capture digest](../../test/fixtures/venue-prices/abgb.json)

**Whole-menu audit.** We compared every distinct priced API triple by venue
and URL, including items outside the manifests. All 58 new Warpath diameter
triples and all seven new ABGB diameter triples matched their own item's
printed amount. At Warpath, 24 unqualified prices became diameter-specific.
The four other original venues had identical API triples. The benchmark's
`wrong_variant_prices` list checks additional amounts published for a labelled
item and variant. The separate whole-menu audit also checked new item names
and diameters outside those labels.

At The ABGB, three $5 slice prices appeared as unqualified prices for Calabrese,
Housemade Sausage and Wagyu Beef. Their $22 prices moved to the 14-inch variant.
Marinara's $16 moved to its 16-inch variant. **White Clam lost its unqualified
$24**, and the validator rejected its claimed 16-inch price. Its labelled
triple was missing on both revisions. The baseline's incorrect $18 base price
on an item named “Slice” also persists. These are limitations of the published
menu even though all seven newly published diameters are correct.

**Replay.** The benchmark used separate disposable swap-5 databases, saved
answers, production extraction with the due queue restricted to the six venues,
and a bounded refresh of their establishment and organization menu projections.
All 12 due records reused complete page answers in 46.1 seconds, with zero
failures and zero model calls. Both the repaired rows and price-label validation
can change stored results, so the method advances to `repairs-v10` and
`validator-v14`. The extractor key is identical. The unrestricted due query
returned 2,863 records. At the earlier measured Pi rate of 1,151.5 cached
pages/hour, budget about **2 h 29 min for extraction** and **48 min for a full
Gold refresh**, about **3 h 17 min** together on the same snapshot and hardware.
This is a candidate estimate based on the earlier full Pi run.

To reproduce with the disposable restore and replay directory described above,
run the venue benchmark on both manifests at the baseline, using the candidate's
ABGB manifest as input. On a clone run candidate extraction with `--no-model`
and the same `--base-dir`, refresh Gold, then run both manifests again. The
ordinary full extraction and Gold commands also cover all benchmark scopes.
