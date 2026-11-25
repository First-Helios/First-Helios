# Course labeller evaluation: `set-1` (ADR-0016 §4, slice 1)

The recorded evaluation that picks the course labeller for `gold.price_index`. Session P8-30,
2026-11-24, under [ADR-0016](../adr/0016-course-labels-for-the-price-index.md)
Amendments 1–2.

**Result:**
- **Winner:** the lexicon (`course-lexicon-v1@63ed037341a4`).
- **Passing courses:** `drink`, `alcohol` and `breakfast`.
- **Coverage:** 876 of 3,254 test items (0.269).
- **Arm B** (embedding + LR) passes `drink` only and covers 317 items (0.097).
- **Not passing:** `entree` and `appetizer`, so "median entrée price" isn't served by this
  version.

## Label set

- **Set:** `set-1`, guide `course-guide-v1`.
- **Data:** a scratch copy of the swap-5 data: `helios_p830_test`, restored from
  `helios_work-2026-11-24-p8-23-swap5.dump`, sha256 `a9af1391…`.
- **Extraction streams:**
  - `llm=qwen3-4b-instruct-2507-q4_0@e0ba675d86ab;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v9;validator-v13;resolve-v6;classifier-v2+v3`
  - `jsonld=jsonld-v1;validator-v13;segment-v2;classifier-v2+v3`
- **Candidates** (`course_candidates`, Amendment 2 item 5):
  - 15,121 Gold-reaching named sections at 1,233 venues, 99,408 priced items;
  - 9,047 priced prices under `Unsectioned` on current pages, 8.3% of priced.
- **Draw:**
  - Seed `20261124`; venues 120 of 120 requested (test share 0.4, realized 46/120).
  - One venue per menu group (`menu-groups-v1`): 949 groups, 554 eligible.
- **Excluded:**
  - 634 venues of the ADR-0013 held-out sets (Amendment 2 item 4), exclusion sha256
    `96b74ee1…`;
  - another 128 candidate venues whose menu group holds an excluded venue.
- **Sections:** 645 train, 589 test.
  - Train: 74 venues, 4,263 priced items.
  - Test: 46 venues, 3,254 priced items.
  - Unsectioned share of the test venues: 0.028 (train 0.070); no labeller can reach these
    items.
- **Labelling:** 8 batches of Sonnet agents (`agent:p8-30-sonnet`), blind.
  - Each saw the section name, its items, its priced count and the venue's other rows,
    never an arm's output.
  - The training split came first. The guide was frozen (sha256 `1befd252…`) before the
    first test label.
  - Both splits were labelled before either arm existed, and the label file was frozen at
    sha256 `e8e7ff87…`.
- **Owner review:** 104 test disagreements, 6 labels changed. Final label file sha256
  `1a5e350a…`.
  1. The owner approved the agent labels on the condition of an extra validation pass.
  2. An independent second agent (default model) relabelled all 104 blind: no agent label,
     no arm output.
  3. Reconciliation:
     - The second label matched the agent's on 95 rows: the label stands.
     - It matched an arm's prediction on 4 rows: the label changed (two votes against one).
     - All three differed on 5 rows. These were decided by the guide's item count, and when
       the count rested on unstated menu context, the test-split rule applied (`other`, or
       the agent's label where an arm agreed). Two changed.
  4. `course_eval confirm` wrote the 104 rows with `owner_confirmed`.

  The six changes:
  - skewers sold as sides: `entree` → `side`;
  - two sweet-kolache sections: `dessert` → `breakfast` (the guide lists kolaches under
    breakfast);
  - tzatziki: `side` → `other` (a sauce);
  - an "à la carte" list with no strict majority: `breakfast` → `other`;
  - falafel and hummus beside rice: `other` → `appetizer`.
- **Guide changes while labelling the training split** (PR #184, before any test label):
  sushi → `entree`; breakfast sides in a breakfast or brunch menu → `breakfast`; brunch
  dishes by what they are; cocktails by name → `alcohol`; nachos, wings and fries; catering
  trays; extraction misalignment.

## Arms

| Arm | Labeller version | Tuned on | Abstain threshold |
|---|---|---|---|
| A. Lexicon (baseline) | `course-lexicon-v1@63ed037341a4` | train split | none (rules; no match or a mixed heading abstains) |
| B. Embedding + LR | `course-labeller-v1@8e861ccdb519` | train split, 5-fold venue-grouped CV (C = 0.1) | 0.75 |

On the training split, the lexicon reached precision 1.000 for `alcohol` and `kids`, 0.92–0.94
for the food courses, 0.82 for `drink` and 0.80 for `side`. Arm B's out-of-fold pick passed
`appetizer`, `dessert` and `alcohol` (707 of 4,263 items). Neither result predicted the test.

## Results (test split, item-weighted)

### A. Lexicon

| Course | Predicted items | Correct | Precision | Sections | Venues | Readable | Passes |
|---|---|---|---|---|---|---|---|
| `appetizer` | 258 | 244 | 0.946 | 64 | 20 | yes | no |
| `entree` | 626 | 576 | 0.920 | 110 | 28 | yes | no |
| `side` | 204 | 124 | 0.608 | 50 | 15 | yes | no |
| `dessert` | 76 | 66 | 0.868 | 20 | 13 | yes | no |
| `drink` | 461 | 446 | 0.967 | 79 | 24 | yes | **yes** |
| `alcohol` | 238 | 237 | 0.996 | 36 | 14 | yes | **yes** |
| `breakfast` | 177 | 173 | 0.977 | 25 | 11 | yes | **yes** |
| `kids` | 49 | 48 | 0.980 | 14 | 6 | no | no |

- Passing: drink, alcohol, breakfast
- Coverage over passing courses: 0.269 (876 of 3,254 items)
- Section accuracy: 0.633
- Abstain: 0.310 of items, 0.292 of sections
- `other`: 0.048 of items, 0.032 of sections
- Unsectioned share: 0.028

Confusion (priced items; rows = final label, columns = prediction):

| | appetizer | entree | side | dessert | drink | alcohol | breakfast | kids | other | abstain |
|---|---|---|---|---|---|---|---|---|---|---|
| `appetizer` | 244 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 156 |
| `entree` | 8 | 576 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 328 |
| `side` | 0 | 10 | 124 | 0 | 0 | 0 | 0 | 0 | 0 | 21 |
| `dessert` | 1 | 0 | 0 | 66 | 0 | 0 | 0 | 0 | 0 | 72 |
| `drink` | 0 | 0 | 0 | 0 | 446 | 1 | 0 | 0 | 8 | 63 |
| `alcohol` | 0 | 0 | 0 | 7 | 9 | 237 | 0 | 0 | 0 | 122 |
| `breakfast` | 0 | 11 | 0 | 0 | 0 | 0 | 173 | 0 | 0 | 37 |
| `kids` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 48 | 0 | 8 |
| `other` | 5 | 29 | 80 | 3 | 6 | 0 | 4 | 1 | 149 | 201 |

### B. Embedding + LR

| Course | Predicted items | Correct | Precision | Sections | Venues | Readable | Passes |
|---|---|---|---|---|---|---|---|
| `appetizer` | 262 | 221 | 0.844 | 68 | 23 | yes | no |
| `entree` | 774 | 594 | 0.767 | 129 | 34 | yes | no |
| `side` | 69 | 21 | 0.304 | 4 | 4 | no | no |
| `dessert` | 52 | 45 | 0.865 | 16 | 9 | no | no |
| `drink` | 317 | 311 | 0.981 | 52 | 20 | yes | **yes** |
| `alcohol` | 283 | 264 | 0.933 | 37 | 15 | yes | no |
| `breakfast` | 111 | 109 | 0.982 | 14 | 9 | no | no |
| `kids` | 44 | 43 | 0.977 | 12 | 5 | no | no |

- Passing: drink
- Coverage over passing courses: 0.097 (317 of 3,254 items)
- Section accuracy: 0.492
- Abstain: 0.361 of items, 0.365 of sections
- `other`: 0.051 of items, 0.071 of sections
- Unsectioned share: 0.028

Confusion (priced items; rows = final label, columns = prediction):

| | appetizer | entree | side | dessert | drink | alcohol | breakfast | kids | other | abstain |
|---|---|---|---|---|---|---|---|---|---|---|
| `appetizer` | 221 | 27 | 0 | 0 | 0 | 10 | 0 | 0 | 16 | 126 |
| `entree` | 25 | 594 | 0 | 0 | 0 | 0 | 0 | 0 | 27 | 266 |
| `side` | 0 | 10 | 21 | 0 | 0 | 0 | 0 | 0 | 22 | 102 |
| `dessert` | 1 | 33 | 0 | 45 | 0 | 0 | 0 | 0 | 5 | 55 |
| `drink` | 2 | 13 | 0 | 0 | 311 | 9 | 0 | 0 | 8 | 175 |
| `alcohol` | 8 | 11 | 0 | 7 | 0 | 264 | 0 | 0 | 5 | 80 |
| `breakfast` | 0 | 30 | 16 | 0 | 0 | 0 | 109 | 0 | 0 | 66 |
| `kids` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 43 | 0 | 13 |
| `other` | 5 | 56 | 32 | 0 | 6 | 0 | 2 | 1 | 83 | 293 |

## Decision

- **Winner:** `course-lexicon-v1@63ed037341a4` (`compare`: covered 876 vs 317). The
  model-free baseline wins outright, so nothing model-shaped ships, and the labeller
  could run without the worker image's `fastembed`.
- **Passing courses (the pin):** `drink`, `alcohol`, `breakfast`.
- **Not indexed:**

  | Course | Why |
  |---|---|
  | `appetizer` | precision 0.946, just under the bar |
  | `entree` | precision 0.920 |
  | `side` | precision 0.608 |
  | `dessert` | precision 0.868 |
  | `kids` | precision 0.980 but not readable: 14 sections from 6 venues |

- **Findings for the owner:**
  - *Most errors are names that disagree with their items.* The lexicon's confusions
    between real courses are small, in priced items:

    | Final label | Predicted | Items |
    |---|---|---|
    | `entree` | `appetizer` | 8 |
    | `side` | `entree` | 10 |
    | `breakfast` | `entree` | 11 |
    | `alcohol` | `drink` | 9 |
    | `alcohol` | `dessert` | 7 |

    Most failures come from sections the confirmed labels call `other`:
    - 80 of `side`'s 204 predicted items are add-on, sauce or topping lists headed "Sides";
    - 29 of `entree`'s 50 wrong items are catering packs, build-your-own lists and mixed
      sections.

    A name-only rule can't see that. The item-level v2 that ADR-0016 §2 commits to is aimed
    at exactly these sections.
  - *Abstaining is the bigger coverage cost:* 31% of test items sit under generic headings
    ("Menu", "Featured Items", "Specials", "Lunch"). `entree` alone loses 328 items to
    abstention.
  - *Arm B is data-starved:* 645 training sections across 9 classes. It reads dessert and
    breakfast headings as `entree` and abstains more than the lexicon. More training
    sections (each later set's test split becomes training data, §5) may change this; v1
    has no reason to ship it.
  - *Kids is precise but rare:* 6 test venues. The next fresh sample may make it readable.
  - *Extraction errors seen while labelling:* roughly 23 sections with a heading/item
    misalignment, 23 whose "items" aren't dishes (bare prices, sizes, dietary tags, filler)
    and 9 that aren't menu content. These are keyword counts over the labellers' 277
    notes, so they are approximate. They are recorded as counts by kind only, never as
    page fixes (Amendment 2 item 4).
  - *Edge cases for the next guide version:* sweet kolaches against sweet pastries, bread
    loaves and retail packs, half-dozen boxes, breakfast sides when the menu isn't clearly a
    breakfast menu, and sauces filed under "Sides".
- **Next:** slices 2–3 for the three passing courses. The concrete migration and model plan
  is ADR-0016 Amendment 3 (proposed, awaiting the owner). Each later version is evaluated
  on a fresh sample, as §5 requires.
