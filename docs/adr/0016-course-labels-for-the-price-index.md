# ADR-0016: Course labels for the price index

**Status:** Accepted 2026-09-30 (owner, session G-3), as amended by
[Amendment 1](#amendment-1-2026-09-30-accepted-slice-1a-decisions) and
[Amendment 2](#amendment-2-2026-11-24-slice-1b-checked-against-the-real-data)
(decided under the owner's delegation, P8-30). The open
questions were answered in session G-2 before the text was written
([Owner decisions](#owner-decisions-session-g-2-2026-09-30)).
**Date:** 2026-09-30
**Phase:** 7 (the price index's `course` category)
**Extends:** [ADR-0006](./0006-gold-menu-read-models.md) (Silver classification
layer, kept distinct from source-asserted tags),
[ADR-0007](./0007-gold-price-index-projection.md) point 6 and
[Amendment 1](./0007-gold-price-index-projection.md#amendment-1-2026-09-30-first-slice-built-before-the-course-axis)
item 1 (this is the follow-up ADR it names)

## Context

`gold.price_index` is built with one category, `all`: every priced item and
variant in a 0.01° cell. RFC-0001 §D2 and ROADMAP Phase 7 want it by **course**
("median entrée price in this area"), the proxy V1 found adequate, while a
cross-venue item taxonomy stays a future RFC (RFC-0001 §D7). ADR-0007 Amendment 1
keyed the table so `course` arrives as another `category_kind` with no grain
change, and named this ADR: a comparison of a classifier against a section-name
baseline on labelled sections, then a course projection.

**What is already decided and not reopened here:**

- The category axis is `course`, not an item taxonomy (RFC-0001 §D2/§D7,
  ADR-0007 point 6).
- `course` is a new `category_kind` value of the same table and grain;
  `CATEGORY_KINDS` and `ck_gold_price_index_category_kind` widen
  (`packages/helios_core/gold/models.py`). Venue weighting, item/variant targets
  only, placement and `low_sample` at 5 venues stay as ADR-0007 Amendment 1
  defines them.
- Canonical labels are kept **distinct** from source-asserted ones; ADR-0006's
  deferral named "a Silver classification layer plus a Gold … column" as their
  home.
- Items under the structural `Unsectioned` grouping never reach Gold
  (ADR-0013 Amendment 7 item 5), so they are not labelled.
- Evaluation discipline from ADR-0013 §8: a version ships after one recorded
  evaluation on a set not used to tune it; a set scored and then used for tuning
  is no longer held out. Labelling procedure from ADR-0013 Amendment 3 item 4: an
  agent labels blind, the owner confirms disagreements, confirmed labels are
  final.
- A classifier ships as a checked-in weights file; scikit-learn is needed only to
  train (ADR-0013 §1; `apps/menu_pipeline/train_page_classifier.py`). One generic
  method, never per-platform or per-site rules.

**Facts in the code that shape the decision:**

1. **`menu.menu_section.course` is source payload.** It is a column of the
   immutable section node (`_node("menu_section", "section", ("name", "course"),
   …)` in `packages/helios_core/domains/menu/models.py`): a `replace` row needs
   direct Evidence (ADR-0005 §2), the structural `Unsectioned` row must leave it
   NULL (`ck_menu_section_shape`), and `ck_menu_section_text` bounds it. Nothing
   writes it today (ADR-0013 Amendment 7 item 6 reads no course).
2. **Sections are printed headings.** `packages/helios_parsing/menu_shape.py`
   keeps a section the extractor named only when its name is printed at or before
   its first item, with that span as Evidence; `apps/menu_pipeline/menu_writes.py`
   writes them flat, with version-local native keys `v<version id>:<block>:<normalized
   name>`. JSON-LD pages carry their own section names.
3. **Gold has no section name.** `gold.current_menu` stores the item's
   `content_name` and a `target_path` whose first element is the section's native
   key; the price-index refresh reads nothing else
   (`packages/helios_core/gold/price_index.py`).
4. **The embedding lives in the worker image.** `fastembed` is the `menu` extra,
   installed only in the Dockerfile's `worker` target (`infra/Dockerfile`); the
   Gold refresh (`python -m apps.gold.refresh`) needs no extra today. The page
   classifier is a binary logistic regression over the 256-dim `potion-base-8M`
   embedding plus 7 layout features, trained on 188 labelled pages
   (`apps/menu_pipeline/classifier.py`, `config/page_classifier_v2.json`).

**What cannot be measured yet.** No LLM-extracted sections exist: extraction runs
wait for the P5-5 held-out evaluation (ADR-0013 Amendment 7 item 8). Until the
first real extraction, nobody knows the distribution of section names, how many
are mixed or service-period headings ("Specials", "Lunch", "Happy Hour"), how
many priced items sit in `Unsectioned`, either method's precision or coverage,
how much the course rows move medians, or what labelling costs on the Pi. This
ADR therefore fixes the vocabulary, the storage, the comparison protocol and the
gate; the numbers come from the evaluation it defines, and the build of the
storage and projection waits for that evaluation (slices below).

## Decision

Label each Gold-reaching **section** with one course from a fixed 9-label
vocabulary, store the labels in a **Silver table** in the Menu domain (one row per
section and labeller version), choose the labeller by comparing a **section-name
lexicon baseline** with a **`potion-base-8M` embedding + multinomial logistic
regression** on a venue-split labelled set from the first real extraction, gate
each course on **item-weighted precision ≥ 0.95**, and project the pinned
labeller's labels into `gold.current_menu` and `category_kind = 'course'` rows of
`gold.price_index`.

### 1. Vocabulary

Nine labels. A section gets the label most of its items belong to; a labeller
that is not confident **abstains** (no course), which is not a label.

| Label | Covers | Examples |
|---|---|---|
| `appetizer` | starters, small plates, shareables, snacks, soups and salads served as starters | "Starters", "Small Plates", "Chips & Dips", "Soups & Salads" |
| `entree` | mains: plates, burgers, sandwiches, tacos, pizzas, bowls, pasta, entrée salads | "Entrées", "Burgers", "Tacos", "From the Grill" |
| `side` | dishes ordered beside a main | "Sides", "À la carte" |
| `dessert` | sweets | "Desserts", "Sweets", "Pastries" |
| `drink` | non-alcoholic drinks, including coffee, tea, juice, soda, shakes | "Beverages", "Coffee", "Drinks" |
| `alcohol` | beer, wine, cocktails, spirits | "Beer", "Wine by the Glass", "Cocktails", "Bar" |
| `breakfast` | breakfast and brunch dishes | "Breakfast", "Brunch", "Breakfast Tacos" |
| `kids` | children's menus | "Kids", "Little Ones" |
| `other` | not one course: catering, family packs and bulk orders, sauces/extras/toppings, merchandise, gift cards, mixed sections | "Catering", "Family Meals", "Extras", "Specials" (mixed) |

The full labelling guide (these rows plus edge cases found while labelling) is
written with slice 1 and frozen before the test split is labelled. Changing the
vocabulary later means relabelling every set and section.

### 2. Unit: sections now, items for abstained sections next

- **v1 labels sections.** Input: the section's name (its name path if a source
  nests sections). Every item, variant and modifier under a section takes its
  label. Only named sections that reach Gold are labelled; `Unsectioned` is
  never labelled.
- **Abstain and `other` don't enter course rows.** They stay in `all` and are
  counted in the refresh report.
- **v2 (committed next version):** items in sections that v1 abstained on or
  labelled `other` get an item-level label (dish name plus section name). Its
  label set, method and storage are decided in an amendment after v1's coverage
  is measured; if it needs a schema change, that stops for review as usual.

### 3. Storage: a Silver label table in the Menu domain

A new Menu-owned table (working name `menu.section_course`; final names at
slice 2):

| Column | Meaning |
|---|---|
| `section_id` | FK `menu.menu_section(id)`, `RESTRICT` |
| `labeller_version` | the labeller that wrote the row (§5) |
| `course` | one of the 9 labels, or NULL when the labeller abstained |
| `confidence` | the labeller's score, 0–1 (`NUMERIC(5,4)`, as Menu confidences) |
| `labelled_at` | when the row was written |

- One row per `(section_id, labeller_version)`, unique. Insert-only like the rest
  of `menu` (no UPDATE/DELETE). A row with `course` NULL means "labelled,
  abstained", which is different from "no row yet".
- Written by an owner-run batch CLI in the worker image (working name
  `python -m apps.menu_pipeline.label_courses`). It labels every named section of
  current Menu pages that has no row at the pinned version, and runs after
  extraction and before `apps.gold.refresh`.
- Gold reads it through a new read-only Menu contract (section label at a given
  labeller version), never the table directly (ADR-0004 §7). The Gold refresh
  stays model-free and runs in the plain runtime image.
- **`menu_section.course` stays source-asserted.** No labeller writes it, and Gold
  doesn't project it. If a source ever asserts a course, mapping it is a separate
  decision.

### 4. Methods and comparison

Two arms, both generic and name-only in v1:

- **A. Section-name lexicon (baseline).** A normalizer plus word rules per label
  (e.g. `dessert|sweets → dessert`), checked in as a versioned config file. Pure
  Python. Written from the vocabulary and the training split only.
- **B. Embedding + multinomial logistic regression.** The section name embedded
  with `potion-base-8M` (the manifest's checksum-verified files, via
  `load_embedding`), scored by a multinomial LR whose standardization,
  coefficients, classes and abstain threshold are a checked-in weights file, like
  the page classifier. Trained with an ephemeral scikit-learn (`uv run --extra
  menu --with scikit-learn==…`). No new runtime dependency.

**Label set.**

- Source: the first real extraction (the laptop first pass, after P5-5 merges).
- Sample: ~120 venues at random (seed recorded), with every Gold-reaching section
  of their current Menu pages: ~900 sections at ~8 a page.
- Excluded: the venues of the P5-5 held-out pages. Those pages are never opened
  or labelled here, so they stay blind.
- Split by venue into ~60% train and ~40% test; no venue is in both.
- An agent labels blind from the section name and its items, without seeing
  either arm's output. The owner reviews every section where the agent's label
  differs from either arm's, and confirmed labels are final.
- Labels live in gitignored `var/`, like the extraction gold labels. CI runs only
  the harness's unit tests on synthetic fixtures.

**Tuning.**

- The lexicon's rules, the LR's regularization and both abstain thresholds are
  chosen on the training split only (venue-grouped cross-validation for B).
- Each arm is scored once on the test split.

**Metrics** (on the test split, weighted by priced Gold items, not by section
count, because the index aggregates items):

- *Precision per indexed course*: among priced items in sections labelled *c*,
  the share whose confirmed label is *c*.
- *Coverage*: the share of priced items whose section gets an indexed course,
  counting only courses that pass. Recorded, not gated.
- *Also recorded*: section-count accuracy, a confusion table, abstain and `other`
  rates, and the extraction's `unsectioned_items` share, which bounds what any
  labeller can reach.

**Results.** Recorded in `docs/reviews/`, with the seed, the counts and the agent
and owner disagreement tally.

### 5. Gate, choice and versioning

- **Gate (per course).** A course is indexed by a labeller version only if its
  item-weighted test precision is ≥ 0.95. Courses that fail, or have too few
  test items to read, are not emitted as index rows. Their labels are still
  stored and counted, so the rows can be added when a later version passes.
- **Choice.** The arm with the higher coverage across passing courses wins. A tie
  goes to the baseline (simpler, no model). If neither arm passes any course,
  no course rows ship, and the finding goes to the owner.
- **Labeller version.** The version string names the method, the vocabulary
  version, the normalizer, and the model (`<manifest name>@<sha256 prefix>`) plus
  weights hash for B, or the lexicon file's hash for A. The weights or lexicon
  file carries it, together with the list of courses that passed. That file is
  the **pin**: Gold reads only its version string and passing list, never the
  model.
- **A model, rule or vocabulary bump.**
  - The new version must pass the gate on a test split it was not tuned on: a
    fresh sample from later extraction, excluding P5-5's held-out venues and
    venues already labelled.
  - A test split that was used for tuning becomes training data.
  - After passing, the labeller writes new rows for every current section at the
    new version, and the pin moves. Old rows stay, so a rollback is a pin change
    plus a Gold refresh.

### 6. Reaching `gold.price_index`

- **`gold.current_menu`:** two additive nullable columns, `course` (one of the 9
  labels) and `course_labeller` (the pinned version). Every row under a section
  with a row at the pinned version gets them; abstained or unlabelled rows stay
  NULL. The column holds the canonical label, kept distinct from the
  source-asserted `menu_section.course` (ADR-0006).
- **`gold.price_index`:**
  - `category_kind` widens to `('all', 'course')`.
  - The refresh adds `category_kind = 'course'` rows, with `category_key` = each
    passing course in the pin, using the same placement, venue medians,
    percentiles and `low_sample` rule as `all`.
  - Not indexed: `other`, abstained, unlabelled and failing courses. They stay in
    `all`.
  - The refresh report counts priced items by outcome: `course_unlabelled` (no
    row at the pinned version), `course_abstained`, `course_other` and
    `course_not_indexed`.
- **Migrations.**
  - One menu-schema migration creates the Silver table (slice 2).
  - One Gold migration adds the two `current_menu` columns and replaces
    `ck_gold_price_index_category_kind` (slice 3).
  - Both are hand-reviewed with synchronized upgrade/downgrade SQL. Neither drops
    or alters a column with data in it: Gold is rebuilt by its refresh.

### 7. Slices

1. **Label set, labelling guide, both arms, comparison** (docs, the harness and
   training script, a lexicon and a weights file; no schema). Waits for the first
   real extraction.
2. **Silver table and labeller CLI** ⚠ (models and migration path). After slice 1
   picks a labeller that passes at least one course.
3. **Gold projection and course rows** ⚠ (Gold model and migration). After
   slice 2.

The price-index API (ROADMAP Phase 7) is not part of this ADR.

### 8. Out of scope

- The item-level v2 (committed, decided in its own amendment).
- Cross-venue item taxonomy, cuisine and dietary tags (RFC-0001 §D7,
  ADR-0013 §9).
- Mapping source-asserted `menu_section.course`.
- Scoping own-site menu pages to their Establishment (a separate ADR-0013
  amendment after P5-5 merges).
- Using the `llama-server` model as a labeller.
- The API.

## Alternatives considered

| Option | Pros | Cons / why not chosen |
|---|---|---|
| **Write the label into `menu_section.course`** | No new table | It is immutable source payload that needs Evidence. Every relabel would be a Menu correction page per page, and the classifier would join the extraction `method_version`. It also erases ADR-0006's split between source-asserted and canonical labels. |
| **Gold-only label, computed at refresh** | No Silver table; a relabel is just a rebuild | With arm B, the Gold refresh needs `fastembed` and model files (the worker image). There is no persisted label to audit or roll back, and it departs from ADR-0006's stated Silver layer. |
| **Overwrite labels in place on a bump** | Smaller table | No audit trail or rollback, and Gold can't tell old labels from new mid-run. Menu tables are insert-only. |
| **Label items in v1** | Handles mixed sections | About 8× more to label and classify, and dish names alone are a weaker signal for a small LR. Deferred to v2, for the sections where it matters. |
| **7 labels** (no `breakfast`/`kids`) | Fewer classes, less labelling | Owner chose 9: kids menus and breakfast dishes would otherwise sit inside entrée medians. |
| **4 coarse labels** | Easiest to classify | A beer and a soda share a median; the index answers little. |
| **A `llama-server` zero-shot arm** | No training labels; sees item context | It competes with extraction for the Pi's server, and a prompt change is its own evaluation. Reconsider if both arms abstain too often. |
| **Classifier only, no baseline** | Less work | Nothing would show the model earns its runtime over word rules. |
| **Label set from bundle headings now** | Could start before extraction | Headings aren't the sections the shaper keeps (chrome, hours and promo banners), so it would measure the wrong population. |
| **One overall accuracy bar (≥ 0.90)** | One number | It can hide one bad course (alcohol read as drink) in exactly the rows people query. |
| **A coverage floor now** | Stricter | The floor would be a guess before any real section names are seen, and could block the course axis on an arbitrary number. |
| **Course only inside the index refresh** (no `current_menu` column) | The migration is only the check constraint | The per-venue menu endpoint couldn't show course without a second change. |
| **Index `other` too** | More rows | They would mix kids, catering packs and merchandise, so their medians can't be read as a price. |

## Consequences

**Easier**

- Course rows reuse every rule the `all` rows already have, with no grain change.
- Labels are auditable and versioned. A labeller bump never touches Menu, and a
  rollback is a pin change.
- The Gold refresh stays DB-only and model-free.
- The comparison says whether a model is worth running at all; if the lexicon
  ties, nothing model-shaped ships.

**Harder / accepted costs**

- A new Menu table, a contract, a CLI and two migrations, each on the
  stop-and-ask path.
- An extra step per run: label, then refresh. Sections with no label at the
  pinned version are counted, not silently dropped.
- Coverage is unknown until slice 1. Mixed and service-period sections abstain
  or go to `other`, and `Unsectioned` items never count; v2 recovers only the
  first two.
- Name-only labels miss what a section's items say. Agent labels see items, so
  the test measures that loss honestly.
- About 900 labelled sections is a few hours of agent labelling plus owner review
  of disagreements. Rare courses (`kids`) may lack test support in the first
  sample and wait for a later one.
- A section's label is only as good as the extractor's section name. A change
  that alters section shaping (prompt, segmenter, shaper) isn't re-scored
  automatically; the next labeller version's fresh test sample sees it.

## Owner decisions (session G-2, 2026-09-30)

Put to the owner before writing, with options and recommendations:

1. **Vocabulary:** 9 labels (`appetizer`, `entree`, `side`, `dessert`, `drink`,
   `alcohol`, `breakfast`, `kids`, `other`). The recommendation was 7 (no
   `breakfast`/`kids`).
2. **Unit:** sections now; an item-level fallback for abstained sections is
   committed as the next version.
3. **Storage:** a Silver table in the Menu domain (recommended).
4. **Methods:** lexicon baseline vs embedding + LR (recommended).
5. **Label set:** the first real extraction, ~120 venues, venue split, P5-5's
   held-out venues excluded (recommended).
6. **Gate:** item-weighted precision ≥ 0.95 per course; coverage recorded, not
   gated (recommended).
7. **Versioning:** append per version, Gold reads a pinned version (recommended).
8. **To the index:** `course` and `course_labeller` on `gold.current_menu` plus a
   widened `category_kind` (recommended).

Not asked; this text chose them, and they are open to change at review:

- the per-course gate (failing courses are simply not indexed);
- coverage counted over passing courses only;
- the refresh report's outcome counts;
- the slice order, with slices 2–3 waiting for slice 1's evaluation.

## References

- [ADR-0004](./0004-modular-monolith-identity-and-lifecycle.md) §1, §7: Silver
  and Gold semantics, published contracts.
- [ADR-0005](./0005-immutable-menu-snapshots-and-selection.md) §1–2: immutable
  nodes, support reflects what was asserted.
- [ADR-0006](./0006-gold-menu-read-models.md): the descriptor and aggregate-tag
  deferral (Silver classification layer, canonical vs source-asserted).
- [ADR-0007](./0007-gold-price-index-projection.md) point 6 and Amendment 1.
- [ADR-0013](./0013-phase5-menu-pipeline.md) §1, §8, §9, Amendments 3 (item 4),
  5 and 7 (items 5, 6, 8).
- [RFC-0001](../rfc/0001-menu-pricing-first.md) §D2, §D7.
- Code: `packages/helios_core/domains/menu/models.py` (`MenuSection`, `_node`,
  `ck_menu_section_*`); `packages/helios_parsing/menu_shape.py`;
  `apps/menu_pipeline/menu_writes.py`; `apps/menu_pipeline/classifier.py`;
  `apps/menu_pipeline/train_page_classifier.py`; `config/page_classifier_v2.json`;
  `config/models.yaml`; `packages/helios_core/gold/models.py`
  (`CurrentMenu`, `PriceIndex`, `CATEGORY_KINDS`);
  `packages/helios_core/gold/price_index.py`; `infra/Dockerfile`.

## Amendment 1 (2026-09-30): accepted; slice 1a decisions

Owner decisions in session G-3, before any code. All but item 2 were taken as
recommended.

1. **Accepted.** PR #64 merged with no review comments. The four points the
   text chose without asking are accepted as written:
   - the per-course gate: a course that fails or is too thin to read is not
     indexed, and the passing courses ship;
   - coverage is counted over passing courses only;
   - the refresh report's outcome counts (`course_unlabelled`,
     `course_abstained`, `course_other`, `course_not_indexed`);
   - the slice order: slices 2–3 wait for slice 1's evaluation.
2. **One label per item, by precedence (the owner asked; §1 refined).** The
   owner asked whether an item can belong to more than one course (a kids
   breakfast plate). It can't.
   - *Rule.* An item's course is the first that applies: `other` (catering,
     bulk, extras, merchandise) → `kids` → `breakfast` → the dish course.
   - *Why.* The 9 labels exist to keep kids and breakfast prices out of the
     other courses' medians, and a multi-label row would put them back.
   - *Mixed sections.* Labelling a mixed section with several courses would
     put each course's prices into the others' medians. v2's item-level labels
     are the fix there.
   - *No change to §3 or §6.* The Silver row and the Gold `course` column stay
     single-valued.
3. **Mixed sections: strict majority.** A section takes the course of more than
   half its priced items, else `other` (the ADR's "most of its items"). The
   labelling guide lists the edge cases: salads, shakes, drinks vs alcohol,
   service-period headings, "Specials".
4. **Label file** (gitignored `var/course-labels/<set>/`):
   - `manifest.json` records the seed, the requested and sampled venue counts,
     the test share, the exclusion list's sha256 and size, the guide version,
     the extraction's `method_version`, and the unsectioned priced items per
     sampled venue.
   - `sections.jsonl` has one row per Gold-reaching named section: venue (GERS
     id), Version id, section native key, name and name path, item names,
     priced-item count (priced Gold item and variant rows, the unit the index
     aggregates), split, the agent's blind label, the final label, the labeller
     and an owner-confirmed flag.
   - The agent's label is kept beside the final one, so the agent/owner tally
     can be counted.
5. **Sampling and split.**
   - *Venue* is the GERS id: the menu-page record key before `|`, the key P5-5's
     pages share.
   - *Sample.* A seeded random sample of venues with at least one candidate
     section. Excluded venues are never drawn.
   - *Split.* A venue is in the test split when `sha256("<seed>:<venue>")` falls
     in the lowest 40%. That doesn't depend on sample order or size; it is
     written into every row, and the loader refuses a row whose split moved.
   - *Exclusions.* The exclusion list is a text file of GERS ids (the P5-5
     held-out venues; later versions add venues already labelled). Every
     command that reads a set needs the exclusion list the set was drawn with,
     and refuses a set that contains an excluded venue.
6. **"Too few test items to read" (§5).** A course is readable when an arm
   predicted it on at least 20 test sections from at least 10 venues. Errors
   arrive by section, so an item count alone would overstate the evidence. Rare
   courses (likely `kids`) may wait for a later sample.
7. **Tie (§5).** Coverage is compared as integer counts of covered priced items
   on the same test split, and only an exact tie goes to the baseline.
8. **Owner review.** A *disagreement* is a test section where an arm predicted a
   course other than the agent's label. An abstention claims nothing, so it
   isn't one. Scoring refuses while any disagreement is unconfirmed, while any
   test section is unlabelled or unpredicted, or when the exclusion list
   differs.
9. **Harness output.** `score` writes a JSON report to
   `var/course-eval/<set>/<labeller>.json` and prints its tables as markdown.
   The report has:
   - per-course support (sections, venues, items), precision, readable and
     passes;
   - coverage over passing courses and section accuracy;
   - an item- and section-count confusion table;
   - abstain and `other` rates and the unsectioned share;
   - the owner-review tally and a digest of the test split.

   `compare` applies the winner rule, and refuses two reports scored on
   different test splits. The write-up template is
   `docs/reviews/templates/course-labeller-evaluation.md`.
10. **Slice 1 is split in two.**
    - *1a (this session, no data).* The pure harness is
      `packages/helios_parsing/course_eval.py`. The CLI is
      `apps/menu_pipeline/course_eval.py` (`sample`, `disagreements`, `score`,
      `compare`). The guide is `docs/course-labelling-guide.md`, version
      `course-guide-v1`. Unit tests on synthetic fixtures are in
      `test/test_course_eval.py`.
    - *1b (after the first real extraction).* The candidates exporter (current
      Menu pages → candidates JSONL; its Menu read path is decided then), the
      lexicon, the training script and weights, the labelling, the evaluation
      and its `docs/reviews/` write-up.

## Amendment 2 (2026-11-24): slice 1b checked against the real data

**Status: decided under the owner's delegation** (session P8-30; owner, 2026-11-24: "I
delegate the design within ADR-0016"). The owner may overturn any item before the slice-1b
PR merges.

This ADR was written before any extraction. The figures below were measured on a scratch
copy of the swap-5 data: `helios_work-2026-11-24-p8-23-swap5.dump`, sha256 `a9af1391…`,
the data that `helios`, `helios_work` and `helios_laptop` all hold.

| Measure (swap-5) | Value |
|---|---|
| `gold.current_menu` rows: priced items / priced variants | 91,909 / 7,499 |
| Venues with a Gold row; families (scope subject, record) | 1,233; 1,815 (479 Establishment-scoped, 1,336 Organization-scoped) |
| Gold-reaching named sections | 15,121 (median 8 per venue, p90 27, max 143) |
| Priced rows per section | median 5, p90 14, max 172 |
| Gold target paths | all `section/item` or `section/item/variant`: no nested section reaches Gold |
| Sections whose name and item set also occur at another venue | 7,006 (46%), in 2,085 groups |
| Current Menu page method versions | llm `…;validator-v13;resolve-v6;classifier-v2+v3` (1,774 pages), jsonld `jsonld-v1;validator-v13;…` (172) |

Each item below names the text it amends.

1. **The section unit (amends §2, Amendment 1 item 4).** A candidate section is one
   Gold section: the first element of a `gold.current_menu` row's target path. Its fields:
   - `section_key`: the native key, `v<Bronze record version id>:<block>:<normalized
     name>`. For llm pages the section comes from [5c] DOM assignment and [5d] page
     templates (ADR-0013 Amendments 28 and 29, resolve-v3 and later). For JSON-LD pages it
     is the source's own section.
   - `name`: the row's `section_name` (ADR-0006 Amendment 1). Every one of the 15,121 is
     non-null.
   - `name_path`: `[name]`. Nesting is still allowed, but nothing nested reaches Gold today.
   - `items`: the section's distinct `item_name`s, in item-key (page) order.
   - `priced_items`: the section's priced item and variant rows.

   Gold applies every rule that decides what is current before a row exists: `Unsectioned`
   never reaches it, a dish that a venue's JSON-LD head also prices is hidden from its llm
   head (ADR-0006 Amendment 2), and an earlier own-site page's same dish at the same
   prices hides later copies (ADR-0022 point 4). So the candidates are exactly the
   sections slice 3 would tag.

   Gold holds no unpriced item. The guide's "count unpriced items only when the section
   has no priced item" therefore never applies, and the agent sees priced items only.
   `priced_items` stays a row count, as Amendment 1 item 4 says. ADR-0007 Amendment 4's
   one-sample-per-Evidence rule applies to venue medians, not to this weighting.
2. **Venue and scope (amends Amendment 1 item 5).**
   - The venue is still the GERS id before `|` in the page record's key (`<gers>`,
     `<gers>|<path>`, `<gers>|<host>`). It applies to both scopes, and it covers
     ADR-0022's several own-site pages and platform pages alike.
   - A venue's several pages contribute their sections separately, and they share the
     venue's split.
   - Labels belong to sections, not to scopes. Slice 3 tags every `current_menu` row
     under a labelled section, whatever its scope, and the index's placement rule decides
     which rows are aggregated.
3. **Menu groups: one venue per group (new; amends Amendment 1 items 5 and 6).**
   - *The problem.* Identity gives each of the 1,233 venues its own Organization, so the
     locations of a chain are separate venues. 46% of sections are exact copies of a
     section at another venue. A plain venue split would put copies of one menu in both
     train and test, and ten locations of one chain would satisfy the "10 venues" rule
     with one menu's evidence.
   - *The rule (`menu-groups-v1`).* Two venues are linked when they share at least
     **3** sections with the same normalized name (lowercase, collapsed whitespace) and
     the same set of normalized item names, each with at least **2** items. A group is a
     connected component of these links, and a venue with no links is its own group.
     A shared name or item set seen at more than 60 venues is too generic to link
     anything ("Soft Drinks: Coke, Sprite"), so it doesn't count. On swap-5 this gives
     949 groups, 124 of them with more than one venue (408 venues; the largest have 47
     and 27).
   - *Draw.* A group with an excluded venue is excluded whole (item 4). Every other
     group contributes one representative venue, the member with the lowest
     `sha256("<seed>:rep:<venue>")`. The draw samples among the representatives.
   - *Effect.* The split never separates copies of a menu, and the readability rule's
     "10 venues" means 10 independent menus. The cost is that a chain counts once in
     the test, not once per location as it does in the index. The gate measures how well
     a labeller reads a menu, and a chain's error still shows, once.
   - *Harness.* `course_eval sample` computes the groups from the candidates and records
     the grouping version and its counts in the manifest.
4. **Exclusions (amends §4 "Excluded", §5's bump rule, Amendment 1 item 5).**
   - *What stays blind.* Every ADR-0013 §8 draw up to P5-26, and the later P8 held-out
     sets ([5c] P8-12, [5d] P8-14, resolve-v6 P8-21), has been scored once, and the
     earlier ones have since been tuned on. None of them is blind any more, so excluding
     them can't keep them blind. Only a drawn but unscored evaluation set must stay
     blind, and none exists. The reserved next §8 draw (seed 20261016, ADR-0013
     Amendment 22 item 5) hasn't been drawn, so there are no venues to hold back. P5-5,
     the one set §4 names, has been tuning data since v4.
   - *What is excluded anyway, and why.* The venues of every held-out set, each with its
     menu group:
     - the seven §8 draws: 450 venues,
       `var/menu-eval/p5-26/next-draw-exclusions-p5-27.json` `gers`, sha256 `3439a961…`;
     - P8-12 [5c]: 69 venues;
     - P8-14 [5d]: 127 venues;
     - P8-21 resolve-v6: 52 venues.

     Together that is 634 venues, 426 of which have Gold rows. After each score, the
     failures in these sets were traced page by page and the pages became tuning pages,
     so their sections are cleaner than the population's. A test containing them would
     overstate precision, and the gate is a precision floor.

     The list is `var/course-labels/exclusions-heldout-v1.txt`, sha256 `96b74ee1…` (the
     harness digest). On swap-5 it leaves 554 eligible menu groups, covering 679 venues.
   - *Not excluded: dev sets.* The [5c] dev set (714 pages, 633 venues) and the [5d] and
     labels-v10 dev sets tuned generic rules over a random half of the corpus, without
     page-level fixes. Excluding them as well would leave only 314 groups, mostly venues
     added after 2026-10-24 (later recrawls, PDFs, homepages). That pool is a worse sample
     of the index than the bias it would remove.
   - *Not excluded: page-classifier sets* (P5-27 to P5-32, P8-24, P8-27). They judged
     whether a page is a menu, never its sections.
   - *The other direction.* Labelling reads extracted sections, so it can see extraction
     errors. The write-up records them as counts by kind, never as page-level fixes, so
     no course set feeds extraction tuning, and later §8 draws need not exclude course
     venues.
   - *Later course sets* exclude every venue of earlier course sets, with its group (§5's
     bump rule).
5. **Read path (decides Amendment 1 item 10's open question).** The exporter
   (`apps/menu_pipeline/course_candidates.py`) reads through three published contracts,
   inside ADR-0004 §7's import directions:
   - **Gold** (`packages/helios_core/gold/menu_read.py`, a new `current_sections`):
     sections, names, items and priced rows, plus the refresh's `effective_instant`.
     This is the population defined in item 1.
   - **Provenance** (`get_record_version`): a Version's record key, and from it the
     venue.
   - **Menu** (`packages/helios_core/domains/menu/enumeration.py`, a new
     `current_page_summaries`): each current head page's record version, source kind,
     `method_version` and its priced item and variant prices under `Unsectioned`, using
     the selector's own heads and live-Identity gate at Gold's instant.

   No Gold module gains an import. The exporter is an app, and apps may read Gold, Menu
   and provenance contracts. Two alternatives were rejected:
   - reading sections from Menu would re-implement the precedence and dedupe rules that
     Gold already applies;
   - joining `bronze` tables directly would bypass the contracts.
6. **Label-set size (amends §4 "Sample").** The sample stays at **120 venues**, now one
   per menu group. Readability is counted in venues (Amendment 1 item 6), and at a 0.4
   test share 120 venues leave about 48 test venues. At swap-5's ~12 sections per venue
   that is about 1,450 sections, not ~900. The sections are labelled by agents, and the
   owner reviews only test disagreements.
7. **`method_version` (Amendment 1 item 4).** A set can come from two streams, so the
   manifest's `method_version` lists each `source_kind=method_version` carried by the
   current pages behind the candidates, sorted and joined with ` | `. The exporter's
   `meta.json` records the pages per stream.
8. **Unchanged.** The vocabulary, the guide (`course-guide-v1`), the split hash, the gate
   (0.95, 20 sections / 10 venues), the winner rule, the metrics and slices 2–3. The
   Unsectioned share is still recorded, from item 5's Menu read.

## Implementation notes (2026-10-21)

- Slice 1a is built (labelling guide, `apps/menu_pipeline/course_eval.py`,
  `packages/helios_parsing/course_eval.py`). Slice 1b and slices 2–3 (Silver label table,
  labeller, Gold `course`/`course_labeller` columns, the `course` category) are not:
  `CATEGORY_KINDS` is still `("all",)` in `packages/helios_core/gold/models.py` and no
  migration adds them.
