# Collection-coverage baseline (P8-21, Part 2)

Session P8-21, 2026-10-27/28. Measurement only: no pipeline change.

Scope:
- **Code.** `main` after #136 (`pages-v1`, `MAX_MENU_PAGES` 3, the meal-period lexicon), the
  production page check (`classifier-v2+v3`, `apps.menu_pipeline.classifier.load_verifier`).
  No render: P8-20's re-collection held the browser during this session.
- **Fetching.** Polite static fetches only: `SiteFetcher` (robots.txt, 2 s per host, the Helios
  User-Agent) into a scratch cache (`var/p8-21/coverage/cache`, 449 entries). Entries already in
  `var/site-cache` were copied in (read-only use). No PDF download, no render.
- **Database.** `helios_laptop` was read once, read-only: the place address of two venues
  (Roppolo's, Taco Food Group), 2026-10-28. No other reads, no writes.
- **No model calls, no GPU.**

The harness is new code: `apps/menu_pipeline/coverage_eval.py` (`site_fixture`, `collect_site`,
`coverage_site`, `coverage_metrics`) with `test/test_menu_coverage_eval.py`. The fixtures sit in
the main checkout's gitignored `var/menu-eval/coverage/{real,synthetic}`. The scratch scripts are
untracked, under `var/p8-21/coverage/` in this worktree.

## Result

- **Coverage is scored apart from extraction.** A page that is never collected is counted
  here, not as an extraction miss. The extraction harness (`evaluation.py`) still owns recall,
  wrong associations, false rejects and invented items.
- **Real sites, 19 reviewed** (static fetch, production verifier):

  | Measure | All 19 | dev (6) | held (13) |
  |---|---|---|---|
  | Venue coverage (≥ 1 expected page collected) | **0.688** (11 / 16) | 0.667 | 0.700 |
  | Complete coverage (every expected page) | **0.375** | 0.333 | 0.400 |
  | Page recall | **0.319** (15 / 47) | 0.333 | 0.314 |
  | Page recall without Chick-fil-A's 17 category pages | 0.467 (14 / 30) | | |
  | Page precision (collected pages that are expected) | 0.714 | 0.833 | 0.667 |
  | Collected pages that are another location's | 0.095 | 0 | 0.133 |
  | No-menu sites left empty | 3 / 3 | | |
  | State coverage | **0.280** | | |
  | — static / tab / script / image | 0.343 / 0.667 / 0 / 0 | | |
  | Requests (live, beyond the cache) | 89 | | |

- **13 more real sites are labelled but not scored** (`pending_render`): their homepage or menu
  page is a script shell, so the expected pages and states can't be checked without a render.
  **2 sites are `blocked`**: they answer 403 to the Helios User-Agent.
- **Synthetic sites, 10** (one per kind; the test's assertions record today's coverage):

  | Site kind | Collected | Note |
  |---|---|---|
  | Separate pages (lunch, dinner, drinks) | 2 / 3 | "Drinks" is no candidate term (ADR-0022 Q3) |
  | Tabs, hidden panel in the HTML | 1 page, 2 / 2 states | a hidden panel is in the static HTML |
  | Tabs, script-loaded panel | 1 page, 1 / 2 states | the script panel is never seen |
  | Accordion (`details`) | 1 / 1 | |
  | Table | 1 / 1 | |
  | Shared section price, choice lines | 1 / 1 | collected; extraction is another question |
  | PDF menu | 0 / 1 | linked and counted (`pdf_linked`), never read |
  | Multi-location (Austin venue, Dallas page too) | 1 / 1, plus 1 other-location page | both locations collected |
  | Menu printed on the homepage | 0 / 1 | the homepage is never a candidate |
  | No menu (comedy club) | clean | |

## 1. Fixtures

**Format.** One JSON file per whole website, read by `coverage_eval.site_fixture`:
- `menu_pages`: each page a person reads as the venue's menu, with `states` (`static`,
  `tab:<name>`, `accordion`, `script`, `pdf`, `image`, `platform:<host>`), 2–4
  `sample_items` per state, and `location`;
- `other_location_pages`: menu pages of another location;
- `kinds`: what the site exercises;
- `origin` (real / synthetic), `split` (dev / held), `template`, `status`
  (reviewed / pending_render / blocked), `review` (first pass, re-check, owner).

A page is found when a collected page has its identity (scheme, `www.`, fragment and trailing
slash ignored). A state is covered when half of its sample items are printed in the collected
page's blocks.

**Draw** (`var/p8-21/coverage/draw.py`, seed 20261028).
- **Frame:** P8-20's discovery replay (`var/p8-20/replay.jsonl`, sha256 `c4aa9c9f…`), venues
  with a readable homepage.
- **Exclusions** (`exclusions.json`, sha256 `a92f2ddc…`):
  - every host and venue of a labelled dev or held-out page (926 hosts, 683 venues);
  - P8-20's 500-venue verification sample, which tuned ADR-0022's lexicon and cap;
  - one site per host.
- **Strata:**

  | Stratum | Drawn | Pool |
  |---|---|---|
  | one own-site page verifies | 10 | 76 |
  | several verify | 1 | 1 |
  | JavaScript-only candidates | 8 | 296 |
  | none verifies | 8 | 1,090 |
  | deep link | 6 | 214 |
  | platform record | 1 | 1 |

  That is 34 sites.
- **Templates** (`template.py`, `splits.json`): each site's builder (generator meta tag, else a
  builder signature, else its own host). A whole group goes to one split. The split is
  lopsided, 11 dev and 23 held, because Wix and Square fell in dev; there is no template
  leakage.

**Labels.**
- **First pass:** a Sonnet subagent, from offline packets (`collect.py`: the homepage and up to
  19 same-site pages, 227 pages in all), per `LABELLING.md`. Its own check: every URL and
  sample item is printed in the packet.
- **Re-check:** this session (`recheck.py`, `disagreements.json`; 17 changes):

  | Change | Sites |
  |---|---|
  | `blocked` instead of "no menu": the page answers 403 | goalterman.com, marriott-hotels.marriott.com |
  | `pending_render`: script-shell homepage or menu page | 123noodles, austinchinatown, gotjiskitchen, grajmahalaustin, hastalalunatacos, mojosdailygrind, nlandsurfpark, pollosasadoselnorteno, shugabees, teddyvcookies |
  | `pending_render`: the menu is not in the static HTML | hanghartatx (heading + order button only), locations.chipotle.com (3 featured meals), sbarro.com (categories only) |
  | The Food Truck menu is another location (venue: 401 Colorado St) | tacofoodgroup.com |
  | **Owner to confirm:** the venue is at 10505B N Ranch Road 620, neither printed location; the first pass took 6th Street's `/menu` | roppolos.com |

  The re-check agreed with the first pass on Chick-fil-A's 17 category pages: its `/menu` hub
  shows featured items only.

## 2. Measurements, by gap

| Gap | Where it shows | Count in the reviewed set |
|---|---|---|
| A further page outside the lexicon or past the cap | Café Blue kids and drinks; Chick-fil-A's categories; vcafe's ordering page | 29 of 39 expected pages missed on 8 separate-pages sites (overlaps the image row) |
| Image menus | El Jacalito (6 pages), Cap City, Los Chilakillers `/menu`, La Señora's banners | 4 sites, 9 pages missed |
| Menu on the homepage | Tony C's | 1 site |
| A menu page with no menu word | Heart of Texas Bakery's flavor list | 1 site |
| A tab panel loaded by script | 5th Street's Drinks, Brix & Ale's Dinner and Dessert, Café Blue's Wine | 4 states uncovered |
| Another location's menu collected | Roppolo's West Campus, the taco food truck | 2 of 21 collected pages |
| Script-shell sites (not scored) | 13 `pending_render` | 13 of 34 sites (38 %) |
| Bot block | 2 `blocked` | 2 of 34 |

Cost: 89 live requests for the 19 scored sites (most pages were cached by the collector), no
render.

## 3. What this baseline does not measure

- **Rendered states.** The 13 `pending_render` sites and the `script` states need the renderer.
  After P8-20's re-collection, its `--render` results in `var/site-cache` can be read (read-only)
  to finish their labels, or a render pass can be scheduled.
- **Extraction on the collected pages.** Item-level labels per fixture page were not made. The
  extraction numbers stay the dev harness's.
- **Small n.** 19 scored sites; every rate here has a wide interval. This is a baseline to
  measure changes against, not a population estimate.

## 4. Reproduction

```bash
cd .claude/worktrees/p8-21-page-structure
.venv/bin/python var/p8-21/coverage/frame.py                       # exclusions
.venv/bin/python var/p8-21/coverage/draw.py                        # draw.json
PYTHONPATH=. .venv/bin/python var/p8-21/coverage/collect.py         # packets (polite, scratch cache)
PYTHONPATH=. .venv/bin/python var/p8-21/coverage/template.py        # splits.json
.venv/bin/python var/p8-21/coverage/recheck.py                     # reviewed fixtures
PYTHONPATH=. .venv/bin/python var/p8-21/coverage/run.py /home/fortune/CodeProjects/First-Helios/var/menu-eval/coverage/real
.venv/bin/python -m pytest test/test_menu_coverage_eval.py          # synthetic baseline
```

Frozen files (sha256, first 16 hex): `draw.json` ffd3ba15a43ca11f, `exclusions.json`
e603cf4949711c40 (content sha256 inside: `a92f2ddc…`), `splits.json` febbfd69679f527a.
