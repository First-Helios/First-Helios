# Two-verifier verification: the fresh due-page sample (ADR-0013 Amendment 26)

Session P5-32, 2026-10-21. This carries out the owner's Amendment 26 rulings on the P5-31 record
([2026-10-21-p5-31-training-mix-survey.md](2026-10-21-p5-31-training-mix-survey.md), Q2 (a) and
Q3 (a)): discovery is re-run on the venues whose last outcome was a failure, and the newly resolved
due pages are sampled for `classifier-v2` AND `classifier-v3` precision. It proposes Amendment 27.

Scope:
- measured and verified only. No verifier is shipped, R4 is not built, and the pipeline version is
  unchanged. `classifier-v2` stays the live verifier (`WEIGHTS_PATH` as on main);
- no schema, migration, ORM model, dependency or `infra/` change, and no Pi access;
- the only `helios_laptop` writes are the step 2 discovery re-run and menu-page fetch, through
  the normal write path (section 2). Every other read is `set transaction read only`;
- no manual, per-page, per-site or per-platform rule.

**Result: the fresh sample can't reach the size the plan needs. 2,650 re-run venues resolve 12
(7 sites), so the sample is 7 pages, against about 100.** As side evidence, v2 AND v3 keeps all 5
menus and removes both non-menus v2 accepted. The plan's stop applies, and this record proposes
how to close the stage without more sampling (section 6).

| Fresh due pages (7, one per site) | Kept | Menus | Precision [Wilson 95 %] | Menus lost against v2 |
|---|---|---|---|---|
| `classifier-v2` (live) | 7 | 5 | 0.714 [0.359, 0.918] | — |
| `classifier-v3` | 5 | 5 | 1.000 [0.566, 1.000] | 0 |
| **v2 AND v3** | **5** | **5** | **1.000** [0.566, 1.000] | **0** |
| S4 | 7 | 5 | 0.714 [0.359, 0.918] | 0 |

- **Why the yield is low.** The failures aren't transient. 2,466 of 2,650 venues fail again
  the same way. Dead domains are 97 % of `non_public_host` (39 of 40 sampled hosts don't resolve).
  `http_403` is bot blocking, and most `robots_unavailable` sites redirect robots.txt to
  another host or don't answer (section 3).
- **An ignore-robots run** (owner question during the session) could reach at most the ~28 sites
  whose robots.txt answers 5xx. Dropped by the owner (section 3).
- **Following cross-host redirects** (owner-chosen record-only measurement) gets a v2-accepted
  page on 56 of 434 origins, 39 outside the exclusions. Many land on another business entirely,
  for example WebMD, a McCormick product, a bowling chain's other location, or a new restaurant
  on a lapsed domain. That is a venue-identity problem, not a page problem, and still well short
  of 100 (section 4).

## 1. Step 1: the re-run venues

`var/menu-eval/p5-32/select_rerun.py` (read only) re-derives P5-31's frame:
- current venues with a website and no resolved menu URL;
- the latest `menu-url-discovery` Capture of the website is one of these failures:
  - `non_public_host`, `robots_unavailable`, `http_403`, `redirect_refused`, `http_404`;
  - any other `http_4xx` / `http_5xx`;
  - `network_error`;
- the GERS id, website site and every menu-URL record's site are outside
  `classifier-exclusions.json` (`ebca288b…`, checked).

It excludes `robots_disallowed`, `menu_pdf_only`, `social_link`, `platform_root`,
`no_menu_found`, `not_html` and `too_large`.

- **2,650 venues on 2,107 sites**, P5-31's count exactly:

  | `non_public_host` | `robots_unavailable` | `http_403` | `redirect_refused` | `http_404` | other 4xx/5xx | `network_error` |
  |---|---|---|---|---|---|---|
  | 899 | 676 | 592 | 224 | 207 | 42 | 10 |

- **`rerun-venues.jsonl`** (`bb857645…`, in `rerun-summary.json`). Resolved menu-URL records
  before the run: **1,635** records, 894 URLs, 1,634 venues.
- **Inputs verified first.** P5-31's `verify_inputs.py` on the copied artefacts: 0 mismatches over
  2,067 files. `helios_laptop` was dumped before any write
  (`var/laptop-run/helios_laptop-2026-10-21-pre-p5-32.dump`, `86163779…`).

## 2. Step 2: the re-run and the page fetch

### What was run and what it wrote

`discovery`'s CLI can't take a venue list, and a plain run would have re-crawled every failed
venue in `helios_laptop`, inside and outside the exclusions. So
`var/menu-eval/p5-32/rerun_discovery.py` is the CLI's own wiring with one change: the venue
iterator is limited to the step-1 GERS ids. The rest is unchanged:
- `resolve_urls` with a commit every 100 venues;
- `SiteFetcher` with the discovery User-Agent, robots.txt, and 1 s per host;
- `config/sources.yaml`;
- `load_page_classifier` (`classifier-v2`, `WEIGHTS_PATH`), with no render;
- the main checkout's `var/site-cache`.

It wrote the normal discovery rows in `helios_laptop`:
- `bronze.source_endpoint` and one `menu-url-discovery` `bronze.capture` per attempt;
- for each verified menu URL: `bronze.source_record`, `source_record_version`, `evidence`, and the
  Identity assignment to the venue's Organization (resolution event, current resolution,
  readiness refresh);
- website records unchanged.

No schema, migration or infra change.

The 20-day retry cooldown (`RECRAWL_WINDOW`) is judged at the run's start, and 1,568 venues were
still inside it. **The owner ruled that dev mode may ignore timing windows.** Pass 2
(`rerun_discovery.py pass2`) set `RECRAWL_WINDOW` to 0 in its own process, for exactly the venues
pass 1 had skipped.

A parallel run wouldn't help. `resolve_urls` takes the exclusive lifecycle advisory lock and holds
it until each 100-venue commit (`url_pipeline.py:1191`, `:1208–1210`), so two processes take turns.

| Run (UTC) | Venues | Crawled | Wall time | `menu_urls_found` | Skipped (cooldown) |
|---|---|---|---|---|---|
| Pilot, seed 20261026 (50 of the 1,082 then outside the cooldown) | 50 | 47 | 19:07–19:13 | 0 | 3 (same site, earlier in the run) |
| Pass 1 (`rest`) | 2,600 | 858 | 19:13–20:48 | 4 | 1,742 (1,568 cooldown, the rest same site) |
| Pass 2 (cooldown 0) | 1,568 | 1,508 | 20:54–23:01 | 8 | 60 (same site) |

- **Pilot:** 6.6 s per venue mean, median 0.6 s. 0 of 50 resolved; 44 failed the same way again.
- **Whole re-run:** 3.8 h of per-venue time. Mean 5.1 s, median 0.2 s, p90 15.2 s.
- **Resolved: 12 venues on 7 sites**, with 12 records and 7 URLs. Resolved menu-URL records went
  from 1,635 to **1,647**, and URLs from 894 to 901. Resolved by prior reason:
  `robots_unavailable` 6, `http_404` 3, `http_403` 1, `http_500` 1, `network_error` 1.

  | New site | Menu URL | Venues |
  |---|---|---|
  | macaronigrill.com | `/menus/menu/dine-in/main` | 3 |
  | lemeals.net | `/category/a-la-carte` | 3 |
  | cover-3.com | `/dining-spirits/the-menu` | 2 |
  | hestiaaustin.com | `/menus/tasting-menu` | 1 |
  | theswitchdripping.com | `/austin-belterra-the-switch-bbq-food-menu` | 1 |
  | mezzeme.com | `/menu/` | 1 |
  | petfriendlyrestaurants.com | `/help/how-to-add-a-menu/` (a v2 false accept) | 1 |

- **Final outcomes of the 2,650:**

  | Outcome | Venues |
  |---|---|
  | `non_public_host` | 888 |
  | `robots_unavailable` | 623 |
  | `http_403` | 536 |
  | `redirect_refused` | 234 |
  | `http_404` | 197 |
  | `no_menu_found` | 57 |
  | `not_html` | 49 |
  | other 4xx/5xx and network errors | 46 |
  | resolved | 12 |
  | `robots_disallowed` | 5 |
  | `menu_pdf_only` | 3 |

  2,466 venues kept their reason. The largest changes:
  - `http_403` → `not_html` 48;
  - `robots_unavailable` → `no_menu_found` 32;
  - `robots_unavailable` → `redirect_refused` 13.

### Menu-page fetch

`var/menu-eval/p5-32/fetch_pages.py` is the menu-page CLI's wiring with targets limited to
records of step-1 venues. The 894 earlier pages are all past the 20-day refetch window, and a
plain run would have refetched them.
- It fetched the **7 URLs** (all `succeeded`), wrote **12 new Versions** (Organization scope) and
  stored the bundles under the main checkout's `var/replay/menu-page/`.
- Under the live pipeline version (`…;resolve-v2;classifier-v2`), exactly these 12 records are
  due (`new`); all 1,632 earlier pages are up to date.

## 3. Why the failures don't recover

Read only, no new crawl:
- **`non_public_host` is dead domains.** The fetcher counts a DNS failure as non-public. Of a
  seeded 40 of the 855 hosts, 39 don't resolve today.
- **`robots_unavailable` is not mostly a robots question.** The fetcher already follows RFC 9309:
  a 4xx robots.txt counts as allow-all. In the cache (`robots_diag.py`), the 531 origins'
  robots.txt was:

  | Redirected to another host | Network error | 5xx | Now fine | Too large |
  |---|---|---|---|---|
  | 263 | 221 | 28 | 18 | 1 |

  An ignore-robots switch could reach only the 28 that answer 5xx. The owner dropped it.
- **`http_403` is the homepage refusing the crawler.** Getting past it would mean disguising
  the crawler, which is not on the table.
- **Overture has no second chance.** Only 11 of the 2,638 venues still unresolved list a second
  website.

## 4. The cross-host redirect measurement (owner's pick, record only)

`var/menu-eval/p5-32/record_redirects.py` has no database connection and writes nothing. It uses
its own cache, the discovery User-Agent, 1 s per host, public addresses only, and `classifier-v2`
as the page check. Robots.txt redirects are followed across hosts (at most 5 hops), as RFC 9309
§2.3.1.2 asks; the shipped fetcher refuses them.

- **Frame:** the step-1 venues whose final outcome is `redirect_refused`, or
  `robots_unavailable` whose robots.txt redirected. That is 434 origins and 570 venues.
- **L1:** robots.txt is followed, then discovery runs on the original website.
- **L2:** the homepage's redirects are followed across hosts (robots and public address checked
  on every hop), then discovery runs on the landing site.
- An L1 origin whose homepage also redirects goes on through L2 (**L1+L2**).

Crawl time 2.2 h; `redirects/records.jsonl` `83dd55f3…`; `redirects/summary.json`.

| Lever | Origins | v2 accepted a page | `no_menu_found` | Landing failed (403, robots, 404, loops…) | Other |
|---|---|---|---|---|---|
| L1 alone | 47 | **0** | 2 | 44 (41 robots still unavailable) | 1 |
| L2 | 188 | 27 | 101 | 45 | 15 (PDF only 8) |
| L1+L2 | 199 | 29 | 128 | 36 | 6 |
| **All** | **434** | **56** | 231 | 125 | 22 |

- **17 of the 56 land on a site already in the exclusions**, such as Starbucks, Pluckers,
  Sonic and Maggiano's. That leaves **39 candidate pages**, unlabelled.
- **Judging from URLs alone, the targets are often not the venue:**
  - a lapsed domain redirected to WebMD (`/food-recipes/`), McCormick (a food-colouring product),
    foodie.com or a marketing agency;
  - the brand's other city or location: Chicago, Atlanta, Denver, a Cedar Park venue for an Austin
    one, a bowling chain's other centre;
  - a different restaurant now on the address's domain.

  So adopting redirect targets as websites needs a venue-identity check (name, address, phone or
  host match), which is the venue-context input Amendment 26 item 5 set aside.
- Even if every one of the 39 were usable, this lever plus the re-run gives at most about 45 fresh
  pages, against about 100.

## 5. Step 3–5: the fresh due-page sample (side evidence)

### Sample

`var/menu-eval/p5-32/sample.py` follows the R1(a) pattern:
- every due page of a step-1 venue, outside the exclusions;
- sorted by key, shuffled with seed **20261027**, one page per website site;
- strata by the fixed cutoffs (small < 176 ≤ medium < 500 ≤ large).

| Due pages | Dropped as same site | **Sample** | Small | Medium | Large |
|---|---|---|---|---|---|
| 12 | 5 | **7 pages, 7 sites, 7 venues** | 5 | 2 | 0 |

Checks:
- still due, re-checked before export (same Version id and bundle): 7 of 7;
- the HTML segments exactly to the stored blocks: 7 of 7, utf-8;
- hidden key and scores are outside the labeller folder (`var/audits/p5-32-two-verifier/`):
  v2, v3, v2 AND v3, S4;
- the labeller folder holds pages, blocks, the R1(a) brief and a `draw.jsonl` with page id, URL
  and position only;
- manifest `var/menu-eval/p5-32/manifest.json` (`8d9ef6d4…`), with `sample-key.jsonl`
  `d6eb8958…` and `sample-scores.jsonl` `fae0b87b…`.

**7 pages is far below about 100.** Under the plan this stops before labelling. The owner ruled
the sample be labelled anyway, as side evidence and not a verdict.

### Labels

- **Labeller:** one Sonnet subagent, blind, under the R1(a) brief and the strict prompt
  (`labeller-prompt.md`). It read every line and every character, in chunks of at most 100 lines,
  and reported lines read against `wc -l`.
- **It read all 891 lines** (7 pages) and reported no shortcut.
- **Frozen** with P5-30's validator unchanged (`freeze_p5_32.py`):
  `label/labels-manifest.json` `8dfa46b0…`, before any label was joined to a score.

| Page | Label | Note |
|---|---|---|
| cover-3.com | menu, priced | |
| theswitchdripping.com | menu, priced | |
| lemeals.net | menu, priced | |
| macaronigrill.com | menu, unpriced | dishes listed; prices are per location |
| hestiaaustin.com | menu, unpriced, uncertain | 12-course tasting menu, $215 prix fixe only |
| mezzeme.com | not_menu (hub), uncertain | category tiles with teaser dishes and "View menu" links |
| petfriendlyrestaurants.com | not_menu (off-domain) | a directory's help article |

### Readings

`verdict.py` re-checks every manifest and writes `var/audits/p5-32-two-verifier/verdict.json`
(`b9467933…`, `side_evidence_only: true`).
- **v2 AND v3: 5 of 5 kept pages are menus**, against v2's 5 of 7. It rejects exactly the two
  non-menus:
  - the help article: v2 0.511 (threshold 0.508), v3 0.287;
  - the MezzeMe hub: v2 0.638, v3 0.132.
- It loses no menu, priced or unpriced.
- Per stratum: small 3/3 (v2 3/5), medium 2/2 (v2 2/2). No large page.
- There are no clusters: each venue and menu-URL site holds one page.
- v2 AND v3 admits nothing v2 rejects, so no admissions sample is needed, and the 1,259-site
  `no_menu_found` frame stays unused.

The direction agrees with R1(a) (0.959 [0.933, 0.976]; 5 menus lost of 336), but 7 pages settle
nothing: the lower Wilson bound is 0.566.

## 6. Verdict and proposal

**No §8 verdict is possible from a fresh sample on the current sources.**
- The failed-venue re-run yields 7 pages.
- The redirect lever adds at most 39 unverified ones, many not the venue.
- Overture has no second website for 2,627 of 2,638.
- A sample of about 100 needs a new website source: Foursquare OS Places, OpenStreetMap, or a
  paid places API. That is the discovery-coverage upgrade the owner set for after the pipeline.

**Proposed (Amendment 27):** close the fresh-sample stage on the evidence in hand, and ship
v2 AND v3 with R4 under a post-ship check.
- **The evidence:**
  - R1(a), held out from v3's training: 0.959 [0.933, 0.976], small 0.944;
  - this record's 7 fresh pages: 5/5, both v2 false accepts removed, no menu lost;
  - P5-31's held-out readings for the v3 recipe: draws 0.962, R1(a) 0.959.
- **Why the residual risk is small:**
  - the AND only tightens: it admits nothing v2 rejects, and its recall loss is already accepted;
  - R4 writes tombstones, not deletions, and restores a page accepted again, so the ship is
    reversible by a later pipeline-version bump.
- **The post-ship check:** the first about 100 new due pages from the next venue source (an
  Overture refresh or the coverage upgrade), outside the exclusions, get the R1(a) blind check.
  If the stratified point estimate is below 0.95, the AND is replaced through the same amendment
  path.
- **The ship itself is not built here.** It is one pipeline-version bump: the AND verifier, R4
  (Amendment 24 item 5), and re-verification of every stored bundle. It waits for the owner
  (Q1).

**Not proposed:**
- adopting redirect targets as websites without a venue-identity check;
- an ignore-robots mode;
- getting past bot blocking;
- any per-site rule.

## 7. Artefacts

All are under this worktree's gitignored `var/`.

| Path | What |
|---|---|
| `var/menu-eval/p5-32/` | `select_rerun.py`, `rerun-venues.jsonl` (`bb857645…`), `rerun-summary.json`, `rerun_discovery.py`, `pilot-venues.jsonl` (`4adc6216…`), `pilot.log`, `rest-1.log`, `pass2.log`, `rerun_report.py`, `pilot-` / `pass1-` / `all-outcomes.jsonl` and `-report.json`, `fetch_pages.py`, `fetch.log`, `robots_diag.py`, `record_redirects.py`, `redirect_summary.py`, `redirects/` (frame, records, summary, cache), `sample.py`, `draw-summary.json`, `manifest.json`, `label/` (pages, blocks, brief, batches, labels, `labels-manifest.json`), `labeller-prompt.md`, `freeze_p5_32.py`, `verdict.py` |
| `var/audits/p5-32-two-verifier/` | hidden: `sample-key.jsonl`, `sample-scores.jsonl`, `manifest.json`, `verdict.json` |
| `var/laptop-run/helios_laptop-2026-10-21-pre-p5-32.dump` | `helios_laptop` before the re-run (`86163779…`) |
| `var/menu-eval/p5-29-r1a/`, `p5-29-r1b/`, `p5-30/`, `p5-31/`, `var/audits/p5-29…`, `p5-30…`, `p5-31…` | copies of earlier artefacts, checked with `verify_inputs.py` (0 mismatches) |

Reproduce (this worktree; `<env>` is the deploy `.env`, `<with_db>` the main checkout's
`var/menu-eval/p5-26/with_db.py`):

    python3 -I var/menu-eval/p5-31/verify_inputs.py
    uv run --extra menu --env-file <env> python <with_db> helios_laptop var/menu-eval/p5-32/select_rerun.py
    # writes helios_laptop:
    uv run --extra menu --env-file <env> python <with_db> helios_laptop var/menu-eval/p5-32/rerun_discovery.py pilot|rest|pass2 --log <log>
    uv run --extra menu --env-file <env> python <with_db> helios_laptop var/menu-eval/p5-32/fetch_pages.py --log var/menu-eval/p5-32/fetch.log
    # read only / no database:
    uv run --extra menu --env-file <env> python <with_db> helios_laptop var/menu-eval/p5-32/rerun_report.py all <logs…>
    PYTHONPATH=. uv run --extra menu python var/menu-eval/p5-32/record_redirects.py
    python3 -I var/menu-eval/p5-32/redirect_summary.py
    uv run --extra menu --env-file <env> python <with_db> helios_laptop var/menu-eval/p5-32/sample.py draw   # then still_due
    PYTHONPATH=. uv run --extra menu python var/menu-eval/p5-32/sample.py export
    python3 -I var/menu-eval/p5-32/freeze_p5_32.py && python3 -I var/menu-eval/p5-32/verdict.py

## Verification

See the PR body for this session's `make ci` result. Database tests are skipped locally (no
PostgreSQL `*_test` database), so that is not database acceptance. The change is documents only;
the `var/` scripts are type-checked by `make ci`.

## For the owner

Each question carries the context needed to answer it here.

- **Q1. Close the fresh-sample stage and ship v2 AND v3 with R4 (Amendment 27)?**
  - **Context.**
    - The re-run of 2,650 failed venues resolves 12 (7 sites), so the fresh sample is 7 pages, not
      about 100.
    - As side evidence, v2 AND v3 keeps 5/5 menus and removes both v2 false accepts (a help
      article and a hub).
    - R1(a) reads 0.959 [0.933, 0.976].
    - The AND admits nothing new, its recall loss is accepted (Amendment 26 Q2), and R4's
      tombstones make it reversible.
    - A post-ship blind check of about 100 pages from the next venue source replaces the
      pre-ship sample.
  - **Options:**
    - **(a) accept and build the ship** (recommended): one pipeline-version bump with the AND
      verifier, R4 and re-verification of every stored bundle, then the post-ship check;
    - (b) hold the ship until a new website source (coverage upgrade) can give 100 fresh pages
      first;
    - (c) keep `classifier-v2` alone (Amendment 23 known gap) and stop.
- **Q2. The cross-host redirect lever: park it?**
  - **Context.** Following redirects reaches 56 v2-accepted pages on 434 origins, 39 outside the
    exclusions, unlabelled. Many land on another business (lapsed domains, other cities, a new
    restaurant at the address). Adopting a target safely needs a venue-identity check. That is
    an ADR-0010 change and part of discovery coverage.
  - **Options:** (a) park it for the coverage upgrade, with the measurement kept in `var/`
    (recommended); (b) label the 39 now to size the lever more precisely (one batch, about 20
    min).
- **Q3. Labels.** The 7 labels are Sonnet's, blind under the strict prompt (891 of 891 lines
  read), and 2 are marked uncertain (a tasting menu without item prices, a hub with teaser dishes).
  Do they stand without a hand check, as in P5-30 and P5-31?
- **Q4. The 12 new menu URLs stay in `helios_laptop`** (normal discovery writes, 1 false accept
  among them, as with any v2 run). They will be re-verified under the AND at the ship. Agreed?

## Owner decisions (2026-10-21)

- **Q1:** (a). The fresh-sample stage is closed on the evidence in hand, and Amendment 27 is
  accepted. Next, one pipeline-version bump ships `classifier-v2` AND `classifier-v3` with R4 and
  re-verification of every stored bundle and saved menu URL. The post-ship blind check of about 100
  new due pages from the next venue source replaces the pre-ship sample.
- **Q2:** (a). The cross-host redirect lever is parked for the discovery-coverage upgrade; adopting a
  redirect target needs a venue-identity check (an ADR-0010 change). The measurement stays in
  `var/`.
- **Q3:** the 7 labels stand, with no hand check.
- **Q4:** the 12 new menu URLs stay, **except the v2 false accept**
  (`petfriendlyrestaurants.com/help/how-to-add-a-menu/`), which is dropped. It is dropped by the
  ship's own path, not by hand: the verifier change makes ADR-0015 re-verify every saved URL, v3
  rejects this page (0.287 against 0.674), so it is withdrawn to `needs_review` and R4 takes it out
  of the due queue. It has no Menu rows. Until the ship, no extraction pass runs on
  `helios_laptop`, so it is never extracted.
