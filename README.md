# Helios V2

A trustworthy, queryable price index of food in Austin: restaurant menus and
what they actually cost, across the Austin / Round Rock metro. V2 is a
from-scratch rebuild; the scope was set menus-first by
[RFC-0001](./docs/rfc/0001-menu-pricing-first.md). It is built by AI agents
with a human reviewer in the loop: see [CLAUDE.md](./CLAUDE.md) for agent
instructions and [CONTRIBUTING.md](./CONTRIBUTING.md) for the PR workflow.

## Status

This section is the single current-status page. Other docs link here.

**Built** (schemas are owned per module; see
[`packages/helios_core/db/base.py`](./packages/helios_core/db/base.py)):

- **Bronze provenance**: `packages/helios_core/provenance/`. Sources, endpoints,
  captures, source records and versions, and Evidence (`bronze` schema);
  replay-safe observation persistence.
- **Identity**: `packages/helios_core/identity/`. Subject, Place, Organization,
  Establishment; append-only resolution and Subject-change lineage;
  deterministic external-key/URL resolution and readiness (`identity` schema).
- **Menu**: `packages/helios_core/domains/menu/`. Immutable Menu snapshots and
  their writer, plus the pure current/history price selector
  (`menu` schema, ADR-0005). The menu pipeline's extraction writes them
  (below); not yet run on the Pi.
- **Gold read models**: `packages/helios_core/gold/`. `gold.current_menu`, a
  rebuildable projection of the Menu selector, with bounded per-scope and
  full-catalog refresh (ADR-0006). `gold.price_index` (ADR-0007
  [Amendment 1](./docs/adr/0007-gold-price-index-projection.md#amendment-1-2026-09-30-first-slice-built-before-the-course-axis)):
  venue-weighted p25/median/p75 per 0.01° lat/lon cell and currency, rebuilt from
  `current_menu`, with venue counts and a `low_sample` flag below 5 venues. One
  category so far, `all`; `course` waits for a course label. Single-location
  Organizations' own-site prices are placed at their venue; shared menus are left
  out. `python -m apps.gold.refresh` rebuilds both tables at one instant. First
  run on real data on `helios_laptop` 2026-10-22 (ADR-0019 step 1,
  [record](./docs/reviews/2026-10-22-p8-1-gold-fill.md)). Re-refreshed at 15:30Z after
  the overnight extraction (record addendum): 54,318 `current_menu` rows, 941 venues
  with a menu, 472 placed in 267 cells, 97.0% of them `low_sample`. Section and item
  names (ADR-0006 Amendment 1, revision `c95d883737db`): `section_name` and `item_name` on
  every row, filled by the refresh; after the P8-3 refresh all 9,527 served sections and all
  52,396 items have a name. Latest refresh 2026-10-26 (23:40 UTC), after the `validator-v9`
  re-interpretation ([P8-16 record](./docs/reviews/2026-10-26-p8-16-validator-v10.md)): 59,894
  `current_menu` rows and 9,387 sections, also restored to the Pi that serves firsthelios.com. Served by `GET /v1/price-index` (Amendment 2). Area kinds
  (ADR-0007
  [Amendment 3](./docs/adr/0007-gold-price-index-projection.md#amendment-3-2026-10-22-area-kinds-and-the-cell-list),
  revision `d978bedc2523`, ADR-0019 step 3): each placed venue also counts in a 0.05° cell and
  a citywide `all` row (NULL coordinates), rebuilt in the same refresh. After the P8-5 refresh
  on `helios_laptop`: 267 cells at 0.01°, 83 at 0.05° (71.1% `low_sample`, 357 of 472 venues
  in cells with ≥ 5), and `all` over 472 venues, median 1100 (USD 11.00).
- **Read API**: `apps/api/`. FastAPI, conventions per ADR-0008:
  - `GET /healthz`: liveness, no database.
  - `GET /readyz`: readiness, checks the database.
  - `GET /v1/venues`: current venues, cursor-paginated (`limit`, `cursor`).
    Optional filters, ANDed: `has_menu` (the menu endpoint would return a
    menu), `organization` (an `organization_id`, now on every venue) and
    `area` (a price-index `area_key`, the 0.01° cell; with `area_kind` a 0.05°
    cell, or `area_kind=all&area=all` for every venue with a point). Each is
    index-backed (ADR-0018, ADR-0007 Amendment 3).
  - `GET /v1/venues/{venue_id}`: one current venue.
  - `GET /v1/venues/{venue_id}/menu`: the venue's current menu from
    `gold.current_menu`. Each price carries `observed_at`, its age at request
    time and its source kind. The menu nests sections → items →
    variants/modifiers. It also includes the Organization's menu when this
    venue is the Organization's only current venue. Every priced node carries
    an `id` for its price history. Each menu carries `source_url`, the page its
    most recent price was read from, resolved at request time through the
    provenance contract (ADR-0008 Amendment 4).
  - `GET /v1/items/{item_id}/price-history`: the accepted trail behind a menu
    node's prices, one trail per context and currency, read from committed
    Menu through the selector's history mode (ADR-0018, ADR-0008 Amendment 3).
    A trail covers one Bronze Version: accepted, corrected, then superseded
    (`absent`) or `withdrawn`.
  - `GET /v1/price-index?lat=&lon=`: the `gold.price_index` rows of the 0.01°
    cell containing the point, with venue counts, `low_sample`, the observed
    range and `as_of`. Optional `area_kind` (`latlon_grid_0p01` default or
    `latlon_grid_0p05`), `category_kind` and `currency` filters; a cell with no
    row is `200` with `items: []`.
  - `GET /v1/price-index/cells`: every `gold.price_index` row of one
    `area_kind` (`latlon_grid_0p01` default, `latlon_grid_0p05`, or `all`),
    cursor-paginated in key order on `uq_gold_price_index`, with
    `cell_size_degrees` and `as_of` (ADR-0007 Amendment 3).
- **Web client** (separate repo,
  [First-Helios_Frontend](https://github.com/4Fortune8/First-Helios_Frontend); ADR-0019 steps
  5–6, built 2026-10-23, PRs #1–#3 there awaiting merge): a no-build client (native ES modules,
  Leaflet 1.9.4 vendored, OSM tiles) with the citywide headline and 0.05° map, the venues in a
  cell, a venue's menu with dated prices and source links, a price's trail, and an About page.
  It runs locally only: `python3 dev_server.py --api http://127.0.0.1:8000` there serves it on
  `127.0.0.1:8080` and proxies `/v1`. Its `tools/contract_check.py` fails if this repo's
  `apps/api/openapi_snapshot.json` lacks a path or parameter it uses. V1 is on that repo's
  `V1-Graveyard` branch.
- **Overture discovery**: `apps/discovery/` (`__main__.py`, `overture.py`,
  `pipeline.py`). Seeds food venues from Overture Places into Bronze and
  Identity, with conservative dedupe and Nominatim gap-fill
  (`packages/helios_core/geo.py`) (ADR-0009).
- **Website and menu-URL resolution**: `apps/discovery/resolve_urls.py`,
  `url_pipeline.py`, `menu_url.py`, `web_client.py`, `registry.py`
  (+ `config/sources.yaml`). Bronze-first, robots-aware, rate-limited
  (ADR-0010, ADR-0011). Saved menu URLs record their page verifier and are
  re-verified when it changes or after 90 days; one that fails is re-discovered
  or withdrawn to `needs_review`. Platform pages pass the same page check, and a
  chain homepage's platform links are kept only for the location whose address
  the page shows (ADR-0015). The verifier is `classifier-v2+v3`, the ADR-0013 page
  classifiers `classifier-v2` AND `classifier-v3`, so a page must pass both
  (Amendment 27; `apps/menu_pipeline/classifier.py`, weights
  `config/page_classifier_v2.json` and `config/page_classifier_v3.json`, model files
  pinned in `config/models.yaml`;
  evaluations: [v1](./docs/reviews/2026-09-29-classifier-v1-evaluation.md),
  [v2 and rendering](./docs/reviews/2026-09-29-s6f-render-measurement.md)); it runs
  in the `worker` image target. `--render` renders platform pages the static fetch
  can't verify and JavaScript-only own-site pages with headed Chromium under Xvfb
  (`apps/menu_pipeline/render.py`; ADR-0013 Amendments 1–2); off for Pi runs until
  the Pi measurement is recorded.
- **Venue lifecycle**: `apps/discovery/lifecycle.py`, `apps/discovery/models.py`.
  Release completion evidence and completion-gated closure, run at the end of
  each discovery run (ADR-0012). Limits: closure needs a completed baseline plus
  two linked completed releases (none recorded yet; completion is never
  back-filled); completion trusts iterator exhaustion, not upstream
  completeness; not yet run on the Pi.
- **Location overrides**: `apps/discovery/location_overrides.py`,
  `config/location_overrides.yaml` (ADR-0014). Reviewed coordinate/address
  corrections keyed by GERS id, persisted to Bronze, applied in place by minting,
  dedupe and lifecycle projection while the Overture point is unchanged; stale
  entries are ignored and reported. One entry (Lali Son); not yet run on the Pi.
- **Identity corrections**: `apps/discovery/corrections.py`,
  `config/identity_corrections.yaml` (S6e). Reviewed duplicate merges and
  non-venue retirements keyed by GERS id, applied idempotently through the
  evented Identity commands with a human Adjudication per entry (`python -m
  apps.discovery.corrections --actor <reviewer>`). 23 detector-pair merges
  committed; the sampled merges and retirements need GERS ids from the Pi. Not
  yet run on the Pi.
- **Precision audit**: `apps/discovery/audit.py`. DB-free duplicate and geocode
  audit over a venue export, with a hand-labeled worksheet, plus a corpus-wide
  twin search (misplaced twins, location-label records).
- **Menu parsing stages** (ADR-0013 slice 2): `packages/helios_parsing/`.
  Pure functions, called by the page classifier, `menu-page` Bronze and extraction (below): the segmented-text hash
  and `SEGMENTER_VERSION` (`segment.py`, the §5 change signal), the schema.org
  JSON-LD menu reader (`jsonld.py`), and the validator (`validator.py`, now `validator-v10`, ADR-0013
  Amendments 30-31: a name grounds on the print nearest its claim and on words glued at a capital, and
  the price scan passes the dish's own headings; per-row
  accept / downgrade / reject, Capture-targeted `blocks:` locators with excerpt
  hashes, the `unlabeled_price_runs` page flag). The extractor's input and output:
  chunking (`chunking.py`), the prompt (now `prompt-v2.4`) with its GBNF grammar, token cap and
  sparse-chunk retry (`prompt.py`), output parsing with truncated-output recovery
  and the row repairs (`output.py`), and stitch v3 (`stitch.py`). After the validator, the
  post-validator component is `resolve-v4` (`resolve.py`):
  - [5b] price resolution;
  - [5c] section assignment from the page's DOM (`dom_sections.py`, ADR-0013 Amendment 28);
  - [5d] the page's own item template, and duplicate removal (`page_template.py`, Amendment
    29). `page_template.llm_stream` runs the whole `llm` interpretation.

  The evaluation
  harness is `evaluation.py` (gold-label format with the `promo` mark and promo entries, scores,
  loss buckets, corruption injection), with `apps/menu_pipeline/evaluate.py`
  reading the gitignored labels and outputs. At slice 2 (validator v3, prompt v2.3)
  chunks, rows, decisions and harness numbers matched the spike's on its saved Pi output
  and gold rows (#58); pipeline versions v4–v6 (below) changed them.
- **`menu-page` Bronze** (ADR-0013 slice 3, Amendment 4):
  `apps/menu_pipeline/page_bronze.py`, `bundle.py`, `run.py`. A resumable batch
  CLI fetches every saved menu URL of a current venue, segments and classifies it,
  and writes a Capture with a durable bundle (`var/replay/menu-page/`), plus a
  Version when the segmented text, URL or render changed; an unchanged re-read is a
  Capture without a Version. Non-menu, JavaScript-only, PDF and failed pages are
  Captures with a reason code. Platform pages take the venue's Establishment scope
  (Organization when several venues share the URL), own-site pages the
  Organization's. Discovery records `menu_pdf_only` for venues whose only menu
  looks like a PDF. No extraction yet; not yet run on the Pi.
- **`llama-server`** (ADR-0013 slice 1, Amendment 6): the extraction model's
  server, a Compose service behind the `menu` profile with no host port
  (`http://llama-server:8080` on the Compose network). Upstream llama.cpp image
  `server-b11176` pinned by digest, the spike's flags, an 8 GB memory limit. It
  serves Qwen3-4B-Instruct-2507 Q4_0 from `var/models/` (read-only), pinned in
  `config/models.yaml`; the one-shot `llama-model-check` service verifies the file
  first, and a mismatch keeps the server from starting.
  `infra/docker-compose.pi.yml` pins it to the Pi's A76 cores. The owner-run
  [Pi check](./docs/reviews/2026-09-29-llama-server-pi-check.md) against the
  spike's binary is pending.
- **LLM extraction and Menu writes** (ADR-0013 slice 5,
  [Amendment 7](./docs/adr/0013-phase5-menu-pipeline.md#amendment-7-2026-09-29-extraction-and-menu-writes)):
  `apps/menu_pipeline/llama_client.py`, `extraction.py`, `menu_writes.py`,
  `extract.py`, `packages/helios_parsing/menu_shape.py`. A resumable batch CLI
  reads each due `menu-page` Version from its bundle, sends its chunks to
  `llama-server` (2 in flight, one retry per request, sparse-chunk retry), keeps
  the raw answers under `var/replay/menu-extract/`, repairs and validates the
  rows (and the page's JSON-LD), and writes `llm` (and `jsonld`) Menu page
  aggregates through `persist_menu`, with Capture-targeted Evidence per field,
  version-local native keys and trust labels (price confidence 0.98, 0.90 on
  pages flagged `unlabeled_price_runs`; page confidence = classifier
  probability). `method_version` names every pipeline component; a bump
  re-interprets current Versions, from the saved answers unless the model,
  prompt, chunking or segmenter changed. The first held-out evaluation
  ([2026-09-30-p5-held-out-evaluation.md](./docs/reviews/2026-09-30-p5-held-out-evaluation.md),
  Amendment 8) **fails §8** (price accuracy 0.963, item recall 0.837, gold-row
  false reject 0.306; catch 0.988), so no extraction run (laptop or Pi) is cleared.
  Pipeline version v4 (`repairs-v4`, `validator-v4`; ADR-0013 Amendment 9) is tuned
  on those pages and the spike's
  ([record](./docs/reviews/2026-10-03-p5-pipeline-v4-tuning.md); P5-5 pages: price
  accuracy 0.990, item recall 0.887, gold-row false reject 0.112: tuning numbers,
  not a §8 evaluation). Its held-out evaluation on 35 fresh pages
  ([record](./docs/reviews/2026-10-09-p5-v4-held-out-evaluation.md), Amendment 10)
  **fails §8** too: price accuracy 0.983 and catch 0.995 pass; item recall 0.838
  and gold-row false reject 0.278 miss (price formats like "12.5 USD" the validator
  can't read, card prices far from the name, inline layouts).
  Pipeline version v5 (`prompt-v2.4`, `chunk-v2.2`, `repairs-v5`, `validator-v5`;
  ADR-0013 Amendment 11) is tuned on the spike, P5-5 and P5-8 pages
  ([record](./docs/reviews/2026-10-09-p5-pipeline-v5-tuning.md)): one shared price
  reader ("12.5 USD", "50¢", "$.40"), column headers, repeated card names, joined
  names, long blocks sent whole to the model with a token cap that fits them (P5-8
  pages: price accuracy 0.983, item recall 0.871, gold-row false reject 0.116, catch
  0.994; tuning numbers, not a §8 evaluation). Its held-out evaluation on 35 fresh
  pages ([record](./docs/reviews/2026-10-12-p5-v5-held-out-evaluation.md), Amendment 12)
  **fails §8**: price accuracy 0.997 and catch 0.994 pass; item recall 0.819 and
  gold-row false reject 0.168 miss (group prices printed once over a list,
  line-wrapped layouts, a card layout the model misreads, integers glued to a name).
  Pipeline version v6 (`chunk-v2.3`, `repairs-v6`, `validator-v6`; ADR-0013
  Amendment 13) is tuned on the spike, P5-5, P5-8 and P5-10 pages
  ([record](./docs/reviews/2026-10-12-p5-pipeline-v6-tuning.md)): group prices printed
  once for a list or a section, labels stacked over their prices, bare-price pages
  ("Cakes16", a wrapped line's last number), rows named by a whole list split per
  name, and short priced chrome runs (card buttons) sent to the model (P5-10 pages:
  price accuracy 0.997, item recall 0.864, gold-row false reject 0.093, catch 0.996;
  every tuning set clears the four bars; tuning numbers, not a §8 evaluation). Its
  held-out evaluation on 35 fresh pages
  ([record](./docs/reviews/2026-10-13-p5-v6-held-out-evaluation.md), Amendment 14)
  **fails §8**: price accuracy 0.991 and catch 0.995 pass; item recall 0.821 and
  gold-row false reject 0.126 miss (the model naming a dish by its description, heading
  or a wine's cuvée line; one page printing its prices in a separate column). A blinded
  adjudication upheld the blind labels (2 owner-confirmed label changes).
  Pipeline version v7 (`repairs-v7`, `validator-v7`; prompt and chunker unchanged;
  ADR-0013 [Amendment 15](./docs/adr/0013-phase5-menu-pipeline.md#amendment-15-2026-10-14-pipeline-version-v7-tuned-on-the-p5-12-pages-wine-lists-out-of-scope)) is tuned with
  P5-12's pages held out as a dev check ([record](./docs/reviews/2026-10-14-p5-pipeline-v7-tuning.md)): bare
  one-decimal prices on bare-price pages, rows named by their description renamed to the
  title line above, glued diet marks dropped. **Wine lists are out of scope** for now
  (not extracted, not scored; the record says what re-including them needs), and the
  harness ignores a leading menu number when matching names. Prompt naming rules,
  chunking pre-treatment and a stronger retry were tried and rejected. Every tuning set
  and the dev check clear the four bars (dev: item recall 0.865, gold-row false reject
  0.115; tuning numbers, not a §8 evaluation). Its held-out evaluation on 35 fresh pages
  ([record](./docs/reviews/2026-10-15-p5-v7-held-out-evaluation.md), Amendment 16; the
  model on the Pi, owner's choice) **fails §8 on the false-reject bar**: price accuracy
  0.990, item recall 0.883 (the first held-out pass of that bar) and catch 0.991 pass;
  gold-row false reject 0.153 misses (mostly variant labels printed once as a column
  header, which the validator can't ground). Adjudication was skipped: no label change
  could reach that verdict.
  Pipeline version v8 (`validator-v8`; ADR-0013
  [Amendment 17](./docs/adr/0013-phase5-menu-pipeline.md#amendment-17-2026-10-15-pipeline-version-v8-split-column-headers))
  reads a column header printed one label per block ("each" "doz." over each row's prices):
  P5-14's gold-row false reject 0.153 → 0.094, catch 0.993, no row changed on the older
  tuning sets ([record](./docs/reviews/2026-10-15-p5-pipeline-v8-tuning.md); tuning numbers,
  not a §8 evaluation). Its held-out evaluation on 35 fresh pages
  ([record](./docs/reviews/2026-10-15-p5-v8-held-out-evaluation.md), Amendment 18; the model
  on the laptop GPU, owner's choice) **fails §8 on the false-reject bar**: price accuracy
  0.990, item recall 0.905 and catch 0.992 pass; gold-row false reject 0.134 misses (a group
  price over a list, a unit after its price, a currency sign alone in its block). A blinded
  adjudication upheld the labels.
  A page-classifier audit
  ([record](./docs/reviews/2026-10-12-p5-classifier-gap-audit.md)) found no
  demonstrated gap against the §8 classifier bar (draw precision 0.932
  [0.883, 0.962]; recall over the laptop pass unmeasured) and two paths that keep a
  later-rejected page in the extraction queue.
  Menu-write commits check each page once per aggregate state
  (ADR-0005 Amendment 1, revision `db40e9424cba`): linear in page size, flat in the
  stored corpus.
- **Laptop first pass** (ADR-0013 Amendment 8): the first full pass runs on the
  owner's laptop against a persistent local database; the Pi hosts long-term.
  Done up to the fetch (2026-10-02): 9,996 venues seeded from Overture
  `2026-08-19.0`, 8,085 with a website, 1,635 menu-URL records on 894 distinct
  URLs, 1,632 `menu-page` Versions (static only). Extraction waits for a version
  that passes §8.
- **Migrations**: `alembic/`. `alembic upgrade head` builds the schema from
  scratch.

**Not built yet** (phases in [ROADMAP.md](./ROADMAP.md)):

- The first extraction pass (laptop) with v9, the version that passes ADR-0013 §8
  (P5-26, Amendment 22; the slice-5 version and v4 to v8 failed), and the rendered-page
  quality bars (slice 6).
- The price index's `course` category
  ([ADR-0016](./docs/adr/0016-course-labels-for-the-price-index.md), Accepted):
  slice 1a (labelling guide and comparison harness) is built; slice 1b (labels,
  the course projection, then its rows in `GET /v1/price-index`) waits for the
  first real extraction.
- Price history across captures: a trail ends `absent` at the next Bronze
  Version, because native keys are version-local (ADR-0013 N1). Cross-Version
  correspondence is a separate ADR-0005/ADR-0013 question
  ([ADR-0018](./docs/adr/0018-venue-filters-and-item-price-history.md) Q8).
- The staging deploy (ADR-0008 Unit B), production, and the deals layer.

## Gates

- **Phase 5 gate: passed 2026-09-28.** S7 #28, S11 #33, S12 #34 and S13 #45
  merged; main CI run
  [36508316467](https://github.com/First-Helios/First-Helios/actions/runs/36508316467)
  green with strict DB tests. ADR-0013 accepted 2026-09-29 (P5-0), so Phase 5
  implementation slices can start.
  Owner decision G.b: the spike's pipeline replaces the Scrapy-vs-Crawlee
  question.
- **Pi gate 1a, Phase 4 location quality: closed.** The 2026-09-28 adjudication
  of the 100-row precision sample found 4 wrong geocodes and 6 sampled venues
  with a confirmed duplicate, so both ROADMAP Phase 4 bars fail (< 1% wrong
  geocodes, < 2% duplicates). Does not gate `resolve_urls`. Opens when all hold:
  - [x] a correction plan is committed:
    [location correction plan](./docs/reviews/2026-09-28-location-correction-plan.md)
    (S6c), with the corpus-wide twin search and the `audit.street_key` fix;
  - [x] ADR-0014 is accepted and implemented (S6c; 3 override entries still need
    a qualifying basis);
  - [ ] corrections are applied on the Pi in an owner-authorized run (no raw
    SQL; overrides via a discovery re-run, merges and retirements via the S6e
    corrections applier; steps in the plan's runbook). Before it,
    `config/identity_corrections.yaml` needs its 11 pending entries (6 sampled
    merges, 5 retirements) filled with GERS ids that only the Pi database has
    (the plan's "Pending entries" table; `--show-gers`);
  - [ ] a fresh-sample re-audit passes: new seed, 100 hand-labeled rows plus a
    regression check of the corrected cohort; 0 confirmed wrong geocodes, at most
    1 sampled venue with a confirmed duplicate, at most 5 unresolved rows per
    measure, worst case reported, denominator never changed.

  Label criteria for the re-audit (from the 2026-09-28 adjudication; unresolved
  never counts as correct):
  - *Geocode ok:* address corroborated (business, municipal or marketplace
    evidence) and an official pin or independent geocoder match within 150 m.
  - *Geocode wrong:* address corroborated, no evidence of a move, saved point
    more than 1,000 m from an official pin or geocoder match.
  - *Duplicate:* another current record for the same outlet at the same time
    (legal, trading and location-label names count); proximity alone never
    decides.
  - *Twin search, every sampled row:* same house-number street line, or name
    similarity ≥ 0.6 within 300 m; same fingerprint within 1 km; same address at
    any distance.
  - *Unresolved:* 150–1,000 m on interpolating geocoders only, no geocode,
    uncorroborated venue, address conflict, rename-vs-succession pairs (a
    succession is a new business, ADR-0012), virtual-brand granularity.
  - Corrected-cohort input: `reviewed.json` in the
    [removed precision-review data](https://github.com/First-Helios/First-Helios/tree/b2bba735d6de6259b675620fe652cb495b5d43d3/docs/reviews/data/2026-09-28-precision-review)
    ([docs/HISTORY.md](./docs/HISTORY.md)).
- **Pi gate 1b, URL-resolution readiness: closed.** Gates the first Pi
  `resolve_urls` run; independent of 1a (URL records are keyed by GERS id and
  the URL path reads no coordinate, so location errors can't corrupt them).
  Opens when all hold:
  - [x] ADR-0015 accepted 2026-09-29 with the ADR-0013 page classifier as its
    verifier; re-verification, withdrawal, the platform content check and the
    chain guard implemented (S6d part 1, #51); `classifier-v1` implemented and
    merged with strict CI (S6d part 2, #52); platform-page rendering implemented
    (S6f, #54; `classifier-v2` accepts rendered platform menus);
  - [ ] the render's Pi time and memory recorded (the owner runs the
    [Pi measurement](./docs/reviews/2026-09-29-s6f-render-measurement.md#pi-measurement-owner-run);
    a laptop run is recorded there). Until then Pi runs leave `--render` off;
  - [ ] the owner authorizes the run. After it: record website/menu-URL
    coverage (the last Phase 4 "done when" item) and a hand-checked precision
    sample of saved menu URLs.
- **Phase 5 extraction gate (ADR-0013 §8): closed.** Extraction runs (the laptop
  first pass and any Pi run) need a pipeline version with a recorded passing
  held-out evaluation. The first one (slice-5 version, 2026-10-03,
  [record](./docs/reviews/2026-09-30-p5-held-out-evaluation.md)) fails price
  accuracy, item recall and the gold-row false-reject bar; its 10 pages are now
  tuning pages. Version v4 is tuned on them
  ([record](./docs/reviews/2026-10-03-p5-pipeline-v4-tuning.md), Amendment 9) and
  fails its held-out evaluation on 35 fresh pages (2026-10-09,
  [record](./docs/reviews/2026-10-09-p5-v4-held-out-evaluation.md), Amendment 10:
  item recall 0.838, gold-row false reject 0.278); those pages are now tuning pages too.
  Version v5 is tuned on them ([record](./docs/reviews/2026-10-09-p5-pipeline-v5-tuning.md),
  Amendment 11) and fails its held-out evaluation on 35 fresh pages (2026-10-12,
  [record](./docs/reviews/2026-10-12-p5-v5-held-out-evaluation.md), Amendment 12: item
  recall 0.819, gold-row false reject 0.168); those pages are now tuning pages too.
  Version v6 is tuned on them ([record](./docs/reviews/2026-10-12-p5-pipeline-v6-tuning.md),
  Amendment 13) and fails its held-out evaluation on 35 fresh pages (2026-10-13,
  [record](./docs/reviews/2026-10-13-p5-v6-held-out-evaluation.md), Amendment 14: item
  recall 0.821, gold-row false reject 0.126); those pages are now tuning pages too.
  Version v7 is tuned with them held out as a dev check ([record](./docs/reviews/2026-10-14-p5-pipeline-v7-tuning.md),
  Amendment 15, wine lists out of scope: dev item recall 0.865, gold-row false reject
  0.115) and fails its held-out evaluation on 35 fresh pages (2026-10-15,
  [record](./docs/reviews/2026-10-15-p5-v7-held-out-evaluation.md), Amendment 16: item
  recall 0.883 passes, gold-row false reject 0.153 misses); those pages are now tuning
  pages too. Version v8 is tuned on them ([record](./docs/reviews/2026-10-15-p5-pipeline-v8-tuning.md),
  Amendment 17: split column headers; P5-14 gold-row false reject 0.094) and fails its
  held-out evaluation on 35 fresh pages (2026-10-15,
  [record](./docs/reviews/2026-10-15-p5-v8-held-out-evaluation.md), Amendment 18: item recall
  0.905 passes, gold-row false reject 0.134 misses); those pages are now tuning pages too.
  P5-17 ([record](./docs/reviews/2026-10-15-p5-false-reject-structure.md), Amendment 19)
  decided the next version's structure (a deterministic [5b] price-resolution stage), new
  recorded and gated numbers, and when the next draw is spent.
  Opens when all hold:
  - [x] a new pipeline version passes §8 on a fresh held-out draw from the laptop pass:
    **v9 passes** (P5-26, 2026-10-20,
    [record](./docs/reviews/2026-10-20-p5-26-v9-held-out-evaluation.md), Amendment 22
    proposed). On 35 pages (seed 20261015; all 378 venues labelled in P5-5 to P5-16 and their
    sites excluded; the model on the laptop GPU):
    - price accuracy 0.993, item recall 0.874, catch 0.996;
    - gold-row false reject **0.097** (bar 0.12; page-clustered [0.050, 0.156]);
    - usable prices **0.755** (bar 0.74).

    A blinded adjudication upheld the labels. The owner drew at 35 pages with tuning FR 0.084,
    not near Amendment 19 item 7's 0.05
    ([P5-25 record](./docs/reviews/2026-10-20-p5-25-invariance-debt.md), Amendment 21).
    v9 is primary-only, with both `llama-server` slots at 6,144 tokens (`--ctx-size 12288`).
    It is unmerged (PR #93) until the owner merges;
  - [x] the Menu-write commit cost is fixed (Amendment 8 item 6): ADR-0005
    Amendment 1, revision `db40e9424cba` (a 100-item page commits in under 1 s,
    was 226 s); the owner-run laptop re-time
    ([RUN-A-01](./docs/reviews/2026-10-03-menu-write-commit-cost.md#owner-run-checklist-run-a-01-after-the-migration-merges))
    ran 2026-10-14 on a disposable clone: the page that took at least 1 h 25 min commits
    in 24.5 s ([record](./docs/reviews/2026-10-14-p5-pipeline-v7-tuning.md#run-a-01-q7a-the-menu-write-commit-re-timed)).
- **Classifier ship (ADR-0013 Amendment 27): shipped (#102) and applied to `helios_laptop`
  2026-10-22.** P5-33 built one pipeline-version bump. The live verifier becomes `classifier-v2+v3` (a page must pass
  both). R4 (Amendment 24 item 5) adds two things:
  - `due_pages` drops a record whose menu URL was withdrawn or whose latest page-reading
    fetch the classifier rejected;
  - its `llm` and `jsonld` streams get appended `withdrawal` tombstones. A page that is
    accepted again gets a `restoration`.

  The bump re-scores every stored bundle (`python -m apps.menu_pipeline.rescore`, or at the
  start of each extraction). Open items:
  - [x] the laptop step (owner-approved; results in the
    [#102 comment](https://github.com/First-Helios/First-Helios/pull/102#issuecomment-6333193087),
    dumps and logs in `var/laptop-run/`). It ran re-verification only, with `--render`, and no
    extraction:
    - 74 menu URLs withdrawn, 1,364 re-verified, 119 replaced, 46 new, 67 deferred;
    - the re-score then withdrew 149 records (73 for a withdrawn URL, 76 re-scored),
      retracting 2,664 items and 628 prices (0.93 % of the laptop pass), with no
      restorations;
    - the P5-32 false accept's URL is withdrawn and out of the due queue.

    The follow-up overnight run (2026-10-22, owner-approved) did two things, and nothing is
    due afterwards:
    - it fetched only the new and re-saved URLs: 70 fetched, 38 new and 73 changed Versions;
    - it extracted all 1,597 due pages on the laptop GPU (1,533 reused saved answers),
      writing 68,795 current prices and 65 restorations.

    All 65 restorations are on URLs that re-verification replaced. 3 of their 19 URLs are
    clear non-menus that the AND verifier accepted (a blog post, an equipment shop, an old
    menu). They wrote 8 prices, and they are evidence for the post-ship check below;
  - [ ] **post-ship check (Amendment 27 item 5).** The first ~100 new due pages from the
    next venue source (an Overture refresh or the discovery-coverage upgrade), outside the
    classifier exclusions (`var/menu-eval/p5-31/classifier-exclusions.json` plus every
    venue and site labelled since), get the R1(a) check:
    - blind page-level labels (strict full-read prompt), frozen before scoring;
    - one page per site, stratified by the fixed size cutoffs;
    - pass rule: stratified point estimate ≥ 0.95, Wilson interval recorded.

    Below 0.95, a replacement opens through the amendment path. Until it runs,
    `classifier-v2+v3`'s §8 precision rests on R1(a) (0.959 [0.933, 0.976]) and the P5-32
    side evidence.
- **Phase 5 model/harness findings (P5-19 to P5-21): tuning evidence only; no gate
  opened, nothing built.** Model screen
  ([record](./docs/reviews/2026-10-15-p5-model-screen.md)), harness-free bracket screen
  ([record](./docs/reviews/2026-10-16-p5-20-bracket-screen.md),
  [ADR-0017](./docs/adr/0017-extraction-harness-generalization.md), items 1–2 accepted), per-model
  prompts ([record](./docs/reviews/2026-10-16-p5-21-per-model-prompts.md)), the H4 harness
  repair and TEST3 ([record](./docs/reviews/2026-10-17-p5-21-harness-h-test3.md)) and the
  closeout with Pi cost ([record](./docs/reviews/2026-10-18-p5-21-closeout-pi-cost.md)).
  Qwen3-4B-Instruct-2507 Q4_0 on the Pi CPU stays the extractor (the NPU W8A8 probe was
  slower and lower on its 3 pages). Qwen3.5-9B Q4_K_M as a fallback (+131/+138 correct
  prices of 3,664 over the v8 baseline when run on every TEST3 tuning page) was accepted
  as ADR-0013 Amendment 20, but its registered label-free routing failed VAL
  ([record](./docs/reviews/2026-10-20-p5-23-fallback-routing.md)), so **no fallback
  ships** and v9 is primary-only. Integration of these findings:
  [P5-23 register](./docs/reviews/2026-10-20-p5-23-findings-integration.md).
- **Pi check, `llama-server` image: pending.** Before the first Pi extraction
  run, the owner runs the
  [image check](./docs/reviews/2026-09-29-llama-server-pi-check.md): the upstream
  image's prompt and generation tokens/s must each be ≥ 95% of the spike's own
  build on the A76 cores (ADR-0013 §3, Amendment 6). A fail means a source build
  of the spike's commit replaces it. Owner order for the Pi items (2026-10-20, in
  parallel with v9): this check first (run with `--ctx-size 12288`), then gate 1b,
  then gate 1a.
- **Code review remediation R01–R117: complete 2026-09-29 (S17).** Every
  finding was fixed or accepted/deferred by the owner; deferrals and their
  triggers are in [ROADMAP §7](./ROADMAP.md#7-open-questions). Close-out note at
  the top of the [review](./docs/reviews/2026-09-22-full-codebase-review.md); the
  retired trackers are listed in [docs/HISTORY.md](./docs/HISTORY.md).

## Quick start / How to run

### Local setup

Run Postgres/PostGIS, migrations and the API in Docker
([`infra/docker-compose.yml`](./infra/docker-compose.yml): `postgres`, a one-shot
`migrate`, then `api` on `127.0.0.1:8000`):

```bash
git clone https://github.com/First-Helios/First-Helios.git
cd First-Helios
cp .env.example .env
make dev                      # build + start postgres -> migrate -> api
curl localhost:8000/healthz   # {"status":"ok"}
curl localhost:8000/readyz    # {"status":"ok"} once Postgres is up
```

`make dev-logs` tails the stack, `make dev-down` stops it, `make migrate` re-runs
the one-shot migration. `.env` is read only by these Compose targets
(`--env-file .env`), and the containers take their database from
`HELIOS_COMPOSE_DATABASE_URL`. Everything else (the app, Alembic, pytest, the
CLIs) reads `DATABASE_URL` from the process environment only and never loads
`.env`. `DATABASE_URL` has no default: commands that need a database fail and
database tests skip when it is unset
([`packages/helios_core/config.py`](./packages/helios_core/config.py)).

### Develop

```bash
make install     # uv sync + pre-commit and commit-msg hooks
make lint        # pre-commit on all files (hygiene hooks, ruff, ruff-format, mypy)
make typecheck   # mypy .
make test        # pytest with coverage
make ci          # lockcheck + lint + typecheck + test (local subset of CI)
make build       # build the API image on its own
```

Run migrations or the API outside Docker by exporting `DATABASE_URL` first:

```bash
export DATABASE_URL=postgresql+psycopg://helios:helios@localhost:5432/helios
uv run alembic upgrade head
uv run uvicorn apps.api.main:app
uv run python -m apps.api.export_openapi   # after an intentional API change
```

### Discovery CLIs

Discovery and `resolve_urls` make network calls and write to the database
`DATABASE_URL` names; the audit reads a venue export and needs no database.
None of them run in CI. On the Pi they run inside the API container
(`docker compose -f infra/docker-compose.yml --env-file .env exec api ...`), except `resolve_urls`: its page verifier is the
ADR-0013 page classifier, which needs the `menu` extra and verified model files,
so it runs in the worker image
(`docker compose -f infra/docker-compose.yml --env-file .env --profile menu run --rm worker python -m ...`).

```bash
# Seed venues from an Overture release, then record completion and run lifecycle
uv run python -m apps.discovery [--release <overture-parquet-glob>] \
    [--expected-predecessor <prior-release-path>] [--no-geocode]

# Page-classifier model files into var/models/, checked against config/models.yaml
uv run python -m apps.menu_pipeline.models download potion-base-8M
# The extraction model (2.4 GB GGUF) for llama-server; `download` with no name fetches both
uv run python -m apps.menu_pipeline.models download Qwen3-4B-Instruct-2507-Q4_0

# Resolve website + menu URL (Pi gate 1b must be open before a Pi run)
uv run --extra menu python -m apps.discovery.resolve_urls --config config/sources.yaml [--limit N]

# Fetch saved menu URLs into menu-page Bronze (--render off on the Pi)
uv run --extra menu python -m apps.menu_pipeline.run [--limit N] [--render]

# Extract due menu-page Versions into Menu pages (needs llama-server; see below)
uv run --extra menu python -m apps.menu_pipeline.extract [--limit N] [--server URL]

# Precision audit over a venue export (no database)
uv run python -m apps.discovery.audit --export <venue-export.json> [--geocode-check]
```

Each takes `--help` for the full flag list. The audit's venue export:

```bash
psql -At -f - <<'SQL' > venues.json
SELECT json_agg(row_to_json(t)) FROM (
  SELECT e.subject_id, o.canonical_name AS name, o.name_fingerprint AS fingerprint,
         p.latitude::float8 AS lat, p.longitude::float8 AS lon, p.address
  FROM identity.establishment e
  JOIN identity.subject_currentness sc ON sc.subject_id = e.subject_id AND sc.is_current
  JOIN identity.organization o ON o.subject_id = e.organization_subject_id
  JOIN identity.place p ON p.subject_id = e.place_subject_id
) t;
SQL
```

### Extraction model server

`llama-server` (ADR-0013 Amendment 6) runs only when started. The model file
must be in `var/models/` first (download above); `llama-model-check` refuses a
missing or changed file, and then `llama-server` doesn't start. Extraction runs
in the worker on the same Compose network (`http://llama-server:8080`, the
default `--server`); it waits up to `--ready-timeout` seconds for `/health` and
refuses a server whose `/props` names another model file or slot count:

```bash
docker compose -f infra/docker-compose.yml --env-file .env --profile menu up -d --wait llama-server
docker compose -f infra/docker-compose.yml --env-file .env --profile menu run --rm worker \
    python -m apps.menu_pipeline.extract --limit 20
docker compose -f infra/docker-compose.yml --env-file .env --profile menu stop llama-server   # after a run
```

A run commits each page, so it can be stopped and restarted; it prints a JSON
report (pages due/extracted/failed/empty/flagged, rows by decision and reason,
chunks, retries, truncations, pages/hour, SoC temperature when readable) and
exits 1 if it stopped after 3 failed pages in a row.

On the Pi, add `-f infra/docker-compose.pi.yml` after the base file, so the
server gets the A76 cores (4-7) and Postgres and the API the A55s.

### Staging (Pi)

- An Orange Pi 5 Plus (ARM64) on the owner's LAN runs the `helios` Compose
  stack from `infra/docker-compose.yml` (`postgres`, one-shot `migrate`, `api`),
  bound to 127.0.0.1. Discovery CLIs run inside the API container:
  `docker compose -f infra/docker-compose.yml --env-file .env exec api python -m apps.discovery ...`.
- The deploy directory is a source snapshot of one merged commit (`git archive`),
  with a `DEPLOYED_COMMIT` file recording its SHA; `var/` is a host bind mount
  (caches, audit packets under `var/audits/`).
- Database volume `helios_postgres_data`. The pre-ADR-0011 volume
  `infra_postgres_data` is kept offline: never attach it to the current image.
  Backups are custom-format `pg_dump` files under `~/helios-backups/<run>/`; no
  restore has been rehearsed.
- Rebuild outline: stop runs and back up; deploy the commit; `down`; remove
  `helios_postgres_data` only after confirming it belongs to this stack;
  `up -d --build` (`migrate` exits 0 at head); check `alembic check`, `/healthz`,
  `/readyz`; run discovery (`--expected-predecessor` once a completed release
  exists); re-export and re-audit.
- Last rebuild: 2026-09-28 at `3faae15` (migration `c91a6f02de73`), before the
  S13 lifecycle migration; no completed discovery baseline yet.

### Database acceptance

A local `make ci` with skipped database tests is not database acceptance. Use a
separately provisioned, disposable PostgreSQL `*_test` database (never the
Compose dev database or application data):

```bash
HELIOS_STRICT_DB_TESTS=1 DATABASE_URL=postgresql+psycopg://helios:helios@localhost:5432/helios_test make ci
DATABASE_URL=postgresql+psycopg://helios:helios@localhost:5432/helios_test uv run alembic check
```

CI runs the same strict tests and `alembic check`. See
[CLAUDE.md](./CLAUDE.md#verification--run-before-calling-anything-done) for the
rules.

## Repository layout

```
alembic/                migrations (hand-reviewed)
apps/
  api/                  FastAPI read API and OpenAPI snapshot
  discovery/            Overture discovery, URL resolution, lifecycle, audit
  gold/                 Gold refresh CLI (current_menu + price_index)
  menu_pipeline/        page classifier, menu-page Bronze, llama-server client, extraction
                        and Menu writes, batch CLIs, model files, evaluation
config/sources.yaml     manual website / menu-URL registry
config/models.yaml      pinned model files (sha256, size, licence)
config/location_overrides.yaml    reviewed coordinate/address corrections (ADR-0014)
config/identity_corrections.yaml  reviewed duplicate merges and retirements (S6e)
config/page_classifier_v2.json  classifier-v2 weights (with v3, the menu-URL verifier classifier-v2+v3)
config/page_classifier_v3.json  classifier-v3 weights (with v2, the menu-URL verifier classifier-v2+v3)
config/page_classifier_v1.json  classifier-v1 weights (superseded, kept with its evaluation)
docs/
  adr/                  architecture decisions (index below)
  rfc/  plans/          proposals and build plans
  reviews/              review and evaluation records, migration SQL artifacts
  spikes/menu-model/    menu-model spike (ADR-0013 evidence)
  course-labelling-guide.md  course-label guide (ADR-0016)
  diagrams/             ERD and context diagrams
infra/                  Dockerfile, docker-compose.yml, docker-compose.pi.yml (Pi core pinning)
packages/helios_core/
  config.py             settings (DATABASE_URL, CORS)
  db/                   Base, schema ownership, model registry, sessions
  provenance/           Bronze
  identity/             Identity
  domains/menu/         Menu
  gold/                 Gold read models
  geo.py                Nominatim client
packages/helios_parsing/  pure page parsing: segmentation + text hash, price tokens,
                          classifier features, JSON-LD reader, chunking, prompt and
                          grammar, output parsing, repairs, validator, [5b] price
                          resolution, menu shape, invariance checks, evaluation,
                          course-label evaluation
test/                   pytest suite
```

## Decisions

The ADR index. Status is the short form of each ADR's Status line.

| ADR | Title | Status |
|---|---|---|
| [0001](./docs/adr/0001-stack-choice.md) | Language, framework, and data stack choices | Accepted (web-framework deferral closed by ADR-0008) |
| [0002](./docs/adr/0002-containerization.md) | Containerization, and pulling it forward from Phase 8 | Accepted |
| [0003](./docs/adr/0003-three-layer-schema.md) | Three-layer schema (raw / canonical / mart) | Superseded by ADR-0004 |
| [0004](./docs/adr/0004-modular-monolith-identity-and-lifecycle.md) | Modular monolith, lifecycle layers, and shared identity | Accepted |
| [0005](./docs/adr/0005-immutable-menu-snapshots-and-selection.md) | Immutable Menu snapshots and scoped selection | Accepted (commit check cost, Amendment 1) |
| [0006](./docs/adr/0006-gold-menu-read-models.md) | Gold menu read models: shape, materialization, and refresh | Accepted (Amendment 1 accepted and built 2026-10-22; Amendment 2, JSON-LD precedence per dish, proposed in P8-18) |
| [0007](./docs/adr/0007-gold-price-index-projection.md) | Gold price-index projection: grain, aggregation, and its blocking dependencies | Accepted (target shape; slice 1 built, Amendment 1; API, Amendment 2; area kinds and cell list built, Amendment 3) |
| [0008](./docs/adr/0008-read-api-conventions.md) | Read-API framework and conventions (First Light) | Accepted (Unit A; Unit B, the staging deploy, not built; history reads, Amendment 3) |
| [0009](./docs/adr/0009-venue-discovery-source-dedupe-and-schedule.md) | Venue discovery: source, ingestion, dedupe/minting, and schedule | Accepted |
| [0010](./docs/adr/0010-website-and-menu-url-resolution.md) | Website & menu-URL resolution | Accepted |
| [0011](./docs/adr/0011-provenance-endpoints-vs-identity-match-keys.md) | Provenance endpoints vs identity match keys | Accepted |
| [0012](./docs/adr/0012-venue-lifecycle.md) | Venue lifecycle: re-observation, closure, re-homing, and readiness | Accepted |
| [0013](./docs/adr/0013-phase5-menu-pipeline.md) | Phase 5 menu pipeline: page classifier, on-device LLM extraction, validator | Accepted; amendments through 30, each with its own status in the ADR (29 accepted and built, 30 proposed) |
| [0014](./docs/adr/0014-location-overrides.md) | Location overrides: durable, evidence-backed coordinate corrections | Accepted |
| [0015](./docs/adr/0015-menu-url-reverification.md) | Menu-URL precision before the first Pi run: re-verify saved menu URLs | Accepted (Amendment 1; Amendment 2, a wrong-place page check, proposed in P8-18) |
| [0016](./docs/adr/0016-course-labels-for-the-price-index.md) | Course labels for the price index | Accepted (Amendment 1) |
| [0017](./docs/adr/0017-extraction-harness-generalization.md) | Extraction harness generalization: invariance, multi-model acceptance, per-model configuration | Accepted (items 1–2; items 3–4 deferred) |
| [0018](./docs/adr/0018-venue-filters-and-item-price-history.md) | Venue filters and item price history (Phase 7 API remainder) | Accepted (built, P7-2) |
| [0019](./docs/adr/0019-public-v1-site.md) | The path to a public v1 site: frontend, page set, area UX, public deploy | Accepted in part (Q1–Q3, Q6c, Q7, Q9; public deploy deferred); steps 1–6 (local v1) built, the frontend PRs awaiting merge |
| [0020](./docs/adr/0020-drawn-areas-in-the-read-api.md) | Drawn areas in the read API: `boundary=` polygons, a Gold placement table, area price summary and items | Accepted (OQ1–OQ6, OQ8 as recommended; OQ7 changed: `boundary` on `/v1/venues` too); not built yet |
| [0021](./docs/adr/0021-page-structure-model-and-signal-hierarchy.md) | One page-structure model and a decision hierarchy for structural signals | Proposed (P8-17; owner Q1–Q7 open); not built |

Also: [RFC-0001](./docs/rfc/0001-menu-pricing-first.md) (menu-and-pricing-first
scope) and the
[Step 5 menu schema proposal](./docs/plans/0002-step-5-menu-schema-proposal.md)
(normative detail for ADR-0005). New ADRs start from the
[template](./docs/adr/0000-template.md).

## Docs

- [ROADMAP.md](./ROADMAP.md): phases, plans, and why.
- [CONTRIBUTING.md](./CONTRIBUTING.md): workflow, commits, CI checks.
- [CLAUDE.md](./CLAUDE.md): agent instructions and verification rules.
- [LEARNING_GUIDE.md](./LEARNING_GUIDE.md): module-by-module curriculum for
  reviewing the work.
- [docs/HISTORY.md](./docs/HISTORY.md): index of removed historical docs.
- [docs/spikes/menu-model/README.md](./docs/spikes/menu-model/README.md): the
  menu-model spike (ADR-0013 evidence).
- [Full codebase review](./docs/reviews/2026-09-22-full-codebase-review.md):
  the 2026-09-22 findings R01–R117 (remediation complete).

The V1 code lives on the
[`V1-Graveyard`](https://github.com/First-Helios/First-Helios/tree/V1-Graveyard)
branch: reference material, not a dependency of `main`.

## License

[Business Source License 1.1](./LICENSE): source-visible, non-commercial use
only until the Change Date, after which it converts to Apache License 2.0. See
the LICENSE file for the current parameters, or contact
abdullahhijazi3@gmail.com for a commercial license.
