# Stage [5c] section assignment: build, dev check and §8 held-out result (ADR-0013 Amendment 28)

Session P8-12, 2026-10-24. This session builds
[ADR-0013 Amendment 28](../adr/0013-phase5-menu-pipeline.md#amendment-28-2026-10-24-proposed-stage-5c-section-assignment-from-page-structure)
as the owner ruled it (Q1–Q7). It reproduces the P8-11 dev numbers and runs the §8 held-out
check. Proposal and diagnosis: [2026-10-24-p8-11-menu-structure.md](2026-10-24-p8-11-menu-structure.md).

Scope:
- Build and evaluation only. Nothing was written to `helios_laptop` (alembic head
  `13081a087231`), Bronze, Menu, identity or Gold. Nothing was re-interpreted and Gold was not
  refreshed.
- Every page came from its stored bundle. Every answer came from the saved production answers
  (`var/replay/menu-extract/`, extractor
  `qwen3-4b-instruct-2507-q4_0@e0ba675d86ab;prompt-v2.4;chunk-v2.3;segment-v2`). There were no
  model calls, no Pi access and no fetches.
- No schema, migration, ORM, dependency, model, prompt, chunker, segmenter or `infra/` change.
  There is no per-site or per-platform rule.
- The DB-backed extraction tests ran on a disposable database, `helios_p812_test`.

**Result.** All Amendment 28 plan item 4 bars pass on the held-out set. On gated pages,
section accuracy (exact) rises from **0.461 to 0.961** [0.946, 0.976]. No gated page is worse
than today. Ungated pages are byte-identical, and invariance is clean on every dev, held-out and
production page text.

## 1. What was built

- **`packages/helios_parsing/dom_sections.py`** is stage [5c] (stdlib only). `assign(html,
  blocks, verdicts)`:
  - re-parses the page with `_PlacingSegmenter`, a subclass of segment-v2's parser that also
    records each block's open elements, node ids and h-level;
  - assigns nothing when the re-parse's blocks differ from the Version's blocks;
  - otherwise applies the Amendment 28 rules exactly: the candidates (r3 instance-id tokens
    ignored), the section style (r2: at least two enclosing headings), nearest-heading
    assignment and the page gate (≥ 90 % assigned AND (≥ 95 % wrapped OR one style), no
    corroboration gate);
  - returns `DomSections`: the assignment (empty on an ungated page) plus the gate facts.
- **`menu_shape.shape(blocks, verdicts, headings=None)`.** An assigned item is filed under its
  heading block. The section key is `<heading block>:<normalized heading text>`, the name is
  the printed heading text, and the Evidence is the heading block's span
  (`blocks:segment-v2:bNNNN[0:len]`). Leaf sections only.
  - **Merge guard (invariance).** When a move would merge two of today's items, i.e. the same
    printed item (name block and normalized name) that the model emitted under two different
    sections, both copies keep today's section. Without the guard, item counts and prices
    change on 124 of the 714 dev pages.
  - Corpus-wide the guard holds back 599 items on 151 of 863 page texts.
- **Version.** `RESOLVER_VERSION` `resolve-v2` → `resolve-v3` ([5b] + [5c]). `method_version`
  keeps its length (126 of 128 characters), so no migration is needed.
- **Wiring.** `apps/menu_pipeline/extraction._Run._write` runs [5c] on the `llm` stream after
  `judge`. The `jsonld` stream is unchanged.
- **Harness.** `evaluation.section_page`, `shaped_items` and `section_near`, plus
  `apps.menu_pipeline.evaluate sections TAG [--pages]`. The command prints exact and lenient
  accuracy without [5c] (*today*) and with it (*applied*), page-clustered intervals, gated
  pages, better/worse counts, `Unsectioned` and dish-named sections, the invariance and
  ungated-identity checks, and the proposed bars.
  - Section scoring loads every reviewed menu page, priced or not. Prices are not needed to
    score a section.
- **Tests** use synthetic fixtures only:
  - a Toast-like group `h3` over dish `h3`s;
  - wrapped `h2` sections with `h3` dishes, and a line inside an `h2`;
  - flat `h3` sections;
  - a Squarespace-like `div.menu-section-title`, and its `-description` line;
  - a Wix-like `section-<uuid>` id on a note div;
  - a lone page title;
  - a gate failure (byte-identical output) and a block mismatch;
  - invariance, the merge guard and an end-to-end extraction run;
  - harness counts and bars.

  A mutation check (each rule switched off in turn) fails at least one test for every rule.

## 2. Dev check (714 labelled pages; dev, not held out)

Built code, scored with the built harness (`var/p8-12/dev.txt`):

| | Pages | Items | Today exact | Applied exact | Today lenient | Applied lenient |
|---|---|---|---|---|---|---|
| All | 714 | 20,411 | 0.405 | 0.695 | 0.438 | **0.712** |
| Gated | 412 | 12,628 | 0.414 | **0.882** | 0.446 | **0.887** |
| Ungated | 302 | 7,783 | 0.391 | 0.391 | 0.427 | 0.427 |

- **Gated pages, better/worse:**
  - lenient: 166 better, 7 worse, items +5,662 / −84;
  - exact: 168 better, 6 worse, items +5,991 / −76.
- `Unsectioned` falls from 0.143 to 0.077 of scored items. Sections named after a dish fall
  from 1,299 to 702.
- Invariance broken on 0 pages; ungated pages changed: 0.

**Against the prototype** (applied lenient 0.704, gated 0.875, 165 better / 7 worse, +5,512 /
−84). The gap is fully explained. Scoring the built code with the prototype's two
simplifications reproduces the prototype exactly: 0.687 / 0.704, 0.869 / 0.875, 165 / 7,
+5,512 / −84.
- **Name-fallback lookup (+245 items).** A gold item matched by name rather than by name block
  now takes its stored [5c] section. The prototype kept today's.
- **Merge guard (−95 items).** The prototype moved every assigned item, including copies the
  guard keeps for invariance.

**Production corpus** (`var/p8-12/equiv.txt`; 863 page texts with saved answers):
- the re-parse matches the Version's blocks on all 863;
- the gate passes on 469, the same pages as the prototype;
- the assignment is identical to the prototype's on all 863;
- invariance holds on all 863;
- all 394 ungated pages are byte-identical.

**The owner's six cases** (`var/p8-12/cases.txt`). Every reported item gets the expected
section:

| Case | Item | Section with [5c] |
|---|---|---|
| Los Mayas | Street Taco | SIDES |
| Los Mayas | Mini Pollo | KIDS SPECIALS (Served with Rice & Beans) |
| Veracruz | Orange | Aguas Frescas (not "Pineapple") |
| Veracruz | Shrimp Taco | Tacos |
| Vivo | HH California Nachos | Happy Hour |
| Barstool Bites | Citrus Kale, Baja Chicken | Salads (not "Chicken Caesar") |
| Que Divino | Build Your Own Taco | Build Your Own Taco (not under "Picadillo Con Papa") |

- Bottega is ungated and unchanged (an image menu).
- Every per-item difference from the prototype is one of three kinds:
  - a 40-character truncation in the prototype's printout;
  - an unassigned item, where both keep today's section;
  - the merge guard. Examples: a second "El Furioso Taco" stays under the dish name
    "Cochinita Pibil Taco", and "Chicken Alfredo" stays a section on Barstool Bites.

## 3. §8 held-out check

**Pool and draw** (`var/p8-12/draw.py`, seed 20261024):
- **Pool:** the 863 published `llm` page texts with items, minus three exclusions:
  - the 1,287 labelled text hashes;
  - texts with an audited URL (93 URLs in `audit.txt` / `audit2.txt`);
  - the 7 page texts P8-11 traced: the six owner cases and uchi, on which the rules were
    tuned.
- The pool is **149 texts: 56 gated, 93 ungated**. The amendment said 57 gated. P8-11's
  ad-hoc count left one traced gated page (Veracruz or uchi) in the pool and dropped one
  ungated text it doesn't name. The stricter exclusion was kept.
- **Draw:** 25 gated and 10 ungated, stratified.
- **Frozen before labelling:**
  - `exclusions.json` sha256 `465eeda391d5a1eeef4e678de0394299fe05f47407fc5f311daedb333f727f37`;
  - `draw.json` sha256 `9d9eecfa4a1e1929bb5160caeab515765636005fc0d88b653b2253b5785a1660`.

**Labels:**
- **Labellers:** 13 Sonnet subagents. Each saw only its pages' `blocks/<id>.txt` (`bNNNN |
  text`) and the brief, in a folder that held nothing else. None saw HTML, saved answers,
  today's sections or [5c]'s.
- **Brief:** P5-26's LABELLING.md, with its rules unchanged (`section`: "the nearest section
  heading the page prints above the item, as printed"). sha256 `398ad71b…720f4f00f`.
- **Frozen before scoring:** `labels-blind.sha256` manifest sha256
  `6abfec74721174a7502b8cf70a47002f3f16d22bf6aab43b1e2caac00e6d3b79`.
- **Incident.** Two labellers ran another labeller's generator script from the shared `/tmp`,
  rewriting 9 label files (pages of batches 2, 5 and 7) with their owners' own scripts. In each
  file the page label, item, price, promo and section counts match the owner's report. Every
  rewrite happened before the freeze, and no labeller saw pipeline output. A later set should
  give each labeller a private scratch folder.

**Result** (`var/p8-12/heldout-sections.txt`). Three pages were labelled `not_menu` (amazon,
a Grubhub page, a menu hub) and score nothing. That leaves 32 menu pages: 23 gated, 9
ungated, 1,841 scored items.

| | Pages | Items | Today exact [95 %] | Applied exact [95 %] | Today lenient | Applied lenient |
|---|---|---|---|---|---|---|
| All | 32 | 1,841 | 0.468 [0.381, 0.558] | 0.941 [0.903, 0.966] | 0.493 | 0.941 |
| Gated | 23 | 1,742 | 0.461 [0.370, 0.554] | **0.961 [0.946, 0.976]** | 0.487 | 0.961 |
| Ungated | 9 | 99 | 0.586 | 0.586 | 0.586 | 0.586 |

| Bar (Amendment 28 plan item 4) | Value | Verdict |
|---|---|---|
| Gated pages section accuracy ≥ 0.85 (exact, point estimate) | 0.961 | pass |
| … and ≥ today + 0.20 | 0.961 ≥ 0.661 | pass |
| At most 1 gated page in 10 worse than today | 0 of 23 | pass |
| Ungated pages identical, checked | 0 changed | pass |
| Invariance clean on every dev and held-out page | 0 broken (714 dev, 32 held-out; also all 863 production texts) | pass |

- **Gated pages:** 21 better, 0 worse (exact), items +871 / −0.
- `Unsectioned` falls from 0.097 to 0.009 of scored items. Sections named after a dish fall
  from 154 of 367 to 32 of 327.
- Held-out accuracy is above dev (0.882). Two plausible reasons: a small sample (23 gated
  pages) and labellers who saw only block text. One page, `963c8de82bf3`, stays low (7 of 13):
  the labeller named a crust-choice line as its section.

## 4. Speed (laptop CPU, one process; `var/p8-12/timing.txt`)

All 863 page texts on the laptop (x86_64, 16 CPUs):

| | Median | p95 | Max | Total |
|---|---|---|---|---|
| [5c] `assign` | 14.4 ms | 53.3 ms | 304.8 ms | 17.5 s |
| segment-v2 parse alone, for scale | 8.0 ms | 30.5 ms | 197.2 ms | 9.9 s |
| `shape`'s extra cost | 0.1 ms | 0.8 ms | 13.6 ms | 0.2 s |

- A re-interpretation of every page therefore adds about 18 s of single-core CPU, or about 3 s
  on 8 cores.
- Pi timing was not run, because it needs the owner's go-ahead.

## 5. Owner questions (next step)

1. **Re-interpretation.** May every published `llm` page on `helios_laptop` be re-interpreted
   from its saved answers under `resolve-v3`? That is about 1,600 records, Menu `correction`
   writes and no model call (`apps.menu_pipeline.extract` against saved answers). Then a Gold
   refresh (about 8 min). Recommended after this PR merges.
2. **Merge guard.** Keep "both copies keep today's section" (recommended: simplest, and no item
   changes), or let the first copy move? The second option recovers about 95 dev items but
   leaves the duplicate under a dish-named section. The duplicates themselves belong to the
   queued pseudo-item / duplicate cleanup amendment (Q7).
3. **Pi speed test.** Run [5c] timing on the Pi (read-only, no writes), or skip it? Laptop cost
   is about 14 ms per page.
4. **Held-out pool count.** Accept 149 / 56 gated (traced pages excluded) in place of the
   amendment's 57?
5. **`helios_p812_test`.** Drop the disposable test database now, or after merge?

## 5a. Applied to `helios_laptop` (owner go-ahead, 2026-10-24)

- **Backup:** `var/laptop-run/helios_laptop-2026-10-24-pre-p8-12.dump` (29.4 MB, 36 tables).
- **Dry run** (read only, at alembic `13081a087231`): 1,597 pages due, all `reinterpret`. Every
  one had saved answers and a matching bundle.
- **Re-interpretation** (`var/p8-12/reinterp.py run`, this branch's code):
  - `run_extraction` ran with an extractor that refuses any model call;
  - 1,597 of 1,597 pages were written, with 0 failed and **0 model calls**;
  - 0 withdrawals: the verifier rejected nothing new;
  - 68,795 prices, unchanged from the previous run;
  - 31 min wall time.
- **Gold refresh:** 58,031 `current_menu` rows, up from 54,318: fewer items are
  `Unsectioned`, so more carry a native key. The price index has 351 rows and 947 families.
- **The six cases on the site.** Every reported item now sits under the expected section. One
  thing remains: the merge guard leaves single-dish "sections" wherever the model emitted the
  same printed dish twice. Case 2 is only partly fixed by [5c]:
  - Veracruz "Shrimp Taco" still holds 8 duplicated desserts (the real copies are under
    Desserts), and "Cochinita Pibil Taco" holds one;
  - Vivo: "Beef Enchiladas", "Chipotle Enchiladas", "Spinach & Mushroom Enchiladas";
  - Barstool Bites: "Chicken Alfredo";
  - Que Divino: "Queso Flamiado Con Chorizo";
  - Los Mayas: a second "MEXICAN SPECIALS".

  Removing these needs duplicate removal, which changes item counts. That falls outside
  Amendment 28's invariance rule, so it needs its own ruling (the queued pseudo-item cleanup).

## 6. Artefacts (untracked, `var/p8-12/` in the worktree)

- **Scripts:**
  - `equiv.py`: built vs prototype, invariance and timing over the corpus;
  - `dev.py`: the dev check; `gap.py` and `gap2.py` explain the prototype gap;
  - `cases.py`: the owner's cases;
  - `draw.py`, `freeze.py`, `labelcheck.py`, `timing.py`, `mut.py` (the mutation check);
  - `testdb.py` and `withdb.py`: the disposable DB.
- **Held-out set:** `heldout/`, holding `exclusions.json`, `draw.json` and their `.sha256`
  files, `pages/`, `blocks/`, `extract/prod/`, `labels-blind/` and `labels-blind.sha256`.
- **Labelling folder:** `label/` (brief, blocks, labels).
- **Outputs:** `equiv.txt`, `dev.txt`, `cases.txt`, `draw.txt`, `heldout-sections.txt`,
  `timing.txt`.
- **Held-out score:**
  `uv run python -m apps.menu_pipeline.evaluate sections prod --data var/p8-12/heldout
  --labels var/p8-12/heldout/labels-blind --pages`.
