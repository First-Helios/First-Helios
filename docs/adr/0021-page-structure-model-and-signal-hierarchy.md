# ADR-0021: One page-structure model and a decision hierarchy for structural signals

**Status:** Accepted 2026-10-26 by the owner: Q1–Q7 and the brand-title sub-fork (Q8), all as
recommended (see [Owner decision](#owner-decision)). Proposed 2026-10-26 (session P8-17). Not built:
step 1 (D4) is the next ADR-0013 amendment.
**Date:** 2026-10-26
**Phase:** 8 (menu quality); a Phase 5 pipeline decision
**Extends:** [ADR-0013](./0013-phase5-menu-pipeline.md) (menu pipeline; Amendment 28 [5c]
sections from page structure, Amendment 29 [5d] page template, Amendments 30–31 validator-v9/v10)
**Depends on:** [ADR-0017](./0017-extraction-harness-generalization.md) items 1–2 (invariance,
DEV configurations); the owner's standing direction: LLM first, HTML derived from the LLM's
accepted output, one universal pipeline, no per-site or per-platform rules, no manual entries
**Record:** [2026-10-26-p8-17-html-structure.md](../reviews/2026-10-26-p8-17-html-structure.md)
(the code breakdown, the santopatio trace, the measurements and the subagent check)

## Context

The P8-x gap audit ranks [5d] F2 (RE-NAME) and F4 (ATTACH) as the next derived-HTML fixes. The
model's own losses are mostly the right price on a wrong name or layout. P8-17 read the
pipeline's use of HTML structure from code and measured which structural signals predict a
block's role. The motivating case is santopatio.com/food-menu's Nachos card: three choice lines
inside the card's description. Today "Nachos" is kept unpriced and the three lines become three
items.

What the record found (dev, 420 item-labelled pages; no §8 claim):

1. **Structure is read late, and piecemeal.**
   - Before [5d], no stage reads anything but the h1–h6 and chrome flags. `Block.tag`, `.path`
     and `.classes` are never read.
   - [5c] and [5d] re-parse the HTML for the element stack.
   - "The dish's record" is computed six ways (five block windows of 2–15 blocks, and [5d]'s
     DOM container). "Description line" is computed five ways, by five text rules.
2. **The class signature, used jointly with text shape, is the strongest signal.** Oracle
   per-page role accuracy:
   - class + shape **0.898** [0.872, 0.918];
   - tag path + shape 0.839;
   - class 0.823;
   - shape 0.747;
   - tag path 0.635.

   When a trusted class and a trusted path disagree, the class is right 159 times and the path
   0. A path deciding where the class is mixed is right 6 % of the time.
3. **Seed-learned structure is not precise enough to create items.** On blocks the model did
   not accept, a "title" learned from the accepted rows is a gold title 0.30–0.50 of the time.
   The errors are add-on lines, alt-text echoes and descriptions styled like titles.
4. **Records are mostly one dish.** A template record with an unpriced title holds exactly its
   dish in 0.871 [0.818, 0.914] of cases.
   - **Lost inside records today:** 1,490 gold title amounts.
     - F2 rename: 334;
     - F2/F4 move: 238;
     - F4 attach: 337;
     - model misses: 428;
     - other: 153.
   - **Anchoring the record's rows on its title** was judged right in 21 of 36 sampled loss
     records. It fails on section-heading titles, add-on lines and brand titles.
5. **The santopatio layout is rare.** Choice lines occur in 11 dev records on 5 pages, and in 12
   corpus records on 6 texts. Its look-alikes are often section cards whose lines are items.

## Decision

### D1. One page-structure model, computed once per page

A new stdlib module, `packages/helios_parsing/page_structure.py`, builds a `PageStructure` from
the re-parse that [5c] and [5d] already share (`dom_sections.placed_blocks`, once per page in
`page_template.llm_stream`). It holds:

- **Per block:**
  - node chain (block-level node ids);
  - class signature (`dom_sections.signature`, unchanged);
  - tag path;
  - text shape (one shared classifier: price-only, label + price, short title, description-like,
    add-on lead, symbols).
- **Per page, from the seeds** (D3):
  - the template, as [5d] learns it today;
  - the main title signature;
  - the record container depth;
  - the page's price slot (the class signature of the seeds' price blocks);
  - the gate statistics.
- **Records and membership:**
  - each block of the main title signature whose container holds no second title block is a
    record;
  - every block maps to its record, if any;
  - a box holding two or more title blocks (a flat list) is not a record, and its blocks fall
    back to positional regions.

The Version's blocks, `segment-v2`, `text_hash`, Bronze bundles and Evidence locators are
unchanged. When the re-parse differs from the Version's blocks, the structure is absent, and
every stage behaves exactly as it does today.

### D2. The decision hierarchy

When signals disagree about a block, the first trusted level decides:

| Level | Signal | Decides | Trusted when | Otherwise |
|---|---|---|---|---|
| 0 | **The model's accepted rows (seeds)** | Which items exist, their names and prices | Always: structure never overrides a seed's grounding; every row structure rewrites is judged again by the unchanged validator and [5b] | — |
| 1 | **Record membership** (DOM container of the seed template) | Which dish a line belongs to | The page passes [5d]'s gate, and the block sits in a record (exactly one title block in its container) | Positional region, as today (validator scan, stitch windows) |
| 2 | **Class signature × text shape** | A block's role inside a record: title, price slot, label line, description | ≥ 3 seed blocks with that value, and ≥ 0.8 agreeing on one role | Level 3 only if the block has no class tokens; else no structural role |
| 3 | **Tag path × text shape** | The same, for classless blocks | As level 2 | No structural role |
| 4 | **Position in the record** (depth, sibling order) | Ties between level-2 candidates (two title-like blocks in one record) | Inside a level-1 record only | No decision |
| — | **Text shape vetoes**, at every level | Never an item: an add-on lead ("+$2", "Add …", "Extra …"), an alt-text echo of a neighbour's name, a description-like line; never a label: a price-only line | Always | — |

Two rules follow from the measurements:
- **The tag path never backs off from a mixed class group.** Measured, it is right 6 % of the
  time there.
- **Structure decides relations, not existence.** No level creates an item from a block's class
  alone. [5d]'s ADD stays as narrow as Amendment 29 built it.

### D3. Learned per page, from the model's accepted output

Every structural fact comes from the page itself and is recomputed per page and per run:
- **seeds**: accepted rows with a name block and a price block;
- **roles**: their name blocks are titles and their price blocks the price slot; unpriced
  lettered blocks inside a seed's container are descriptions;
- **thresholds**: [5d]'s existing `MIN_SEEDS`, `MIN_SUPPORT`, `GATE_EXPLAINED` and
  `GATE_AGREE`.

Rules out of scope:
- a stored per-site template or a platform rule;
- a class-name vocabulary for items;
- a learned classifier (Amendment 19's constraint).

[5c]'s class words for headings stay as Amendment 28 built them.

### D4. Adoption order: each step its own ADR-0013 amendment, version bump and measurement

1. **[5d] record rewrite: F2 + F4 + choice lines** (proposed next as an ADR-0013 amendment,
   `resolve-v5`). One rule family: on a gated page, a kept row named or priced inside another
   block's record moves onto the record's title. It has three triggers:
   - **RE-NAME**: a row named by a description, option or alt-text line takes the title's name,
     not when the row's name is a short, non-description line in the card (a brand or
     category title over the dish's own name line; Q8);
   - **ATTACH**: a price block in the record printing labelled prices gives the title one row
     per price;
   - **choice lines**: a label line's row becomes the title's variant(s), one per choice
     (Q4).

   The section-heading guard of Q3 applies to all three. The same-block seed pattern formed by
   such lines no longer counts as an item pattern when its blocks sit in another title's
   record.
2. **[5c]** takes its records and title signature from the same model, so a record title is
   not offered as a section heading. This is a separate amendment, measured on [5c]'s bars.
3. **[5] and [5b]**: a record-bounded price region replaces the 15-block scan on gated pages.
   This comes only after the evaluation harness passes the structure:
   - `corruption_eval` calls `judge(blocks, rows)` without HTML today, and so does the
     invariance suite;
   - its bars are FR, catch and invariance.
4. **Shared text-shape rules.** The five description rules and two price-only rules are
   consolidated stage by stage inside steps 1–3, never as a stand-alone change, because each
   consolidation changes outputs.

Each step is measured against:
- Amendment 29's Q6 stage bars and the losing-pages bar;
- gold-row FR, catch and price accuracy;
- invariance.

Results are reported on the item-labelled dev pages (Q6) and on the corpus.

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| **A. Status quo: each stage keeps its own windows and text rules** | No work; no risk to tuned stages | The Nachos-type cases stay unreachable; six "record" notions keep drifting; every new rule re-derives structure |
| **B. Put the element stack into `Block` (segment-v3)** | One parse; every stage sees structure | A segmenter bump: Evidence locators cite the segmenter version, so a re-segmentation of Bronze; the data class grows for every stored Version |
| **C. The tag path first, then the class** | The tag path is present on every page | Measured worse: path-alone oracle 0.635, against 0.823 for class; path right 0 of 434 times where they disagree |
| **D. Structure mints items (a block-role classifier over class/path/shape)** | Reaches the 428 model-missed records | Measured title precision ≤ 0.50 on non-seed blocks; a learned classifier is outside Amendment 19's constraints; would invent items |
| **E. Per-platform parsers (Wix, Square, BentoBox, …)** | Precise where they apply | Rejected by the owner: one universal pipeline |
| **F. A dedicated choice-line rule only** | Small | Reaches about 9 gold amounts on dev; its look-alikes (section cards, add-on blocks) need the same guards as F2/F4 anyway |

D1 with D4's order is chosen over A: it reaches F2/F4's measured headroom (up to 909 gold
amounts on dev) with one notion of a record. It is chosen over B because it changes no stored
data.

## Consequences

**Easier:**
- One record notion for [5d] now, and for [5c], [5] and [5b] later.
- New derived-HTML rules state their level and threshold instead of a new window.
- The santopatio card, BOWL/CUP rows and description-named rows all become one rule family.

**Harder or riskier:**
- **[5d] rewrites more rows.** Section-heading titles (12 of 53 judged cases) and add-on lines
  are the failure modes, so the Q3 guard and the add-on veto must hold on the losing-pages bar.
- **Validator use of structure is the expensive step.** Before [5]/[5b] can read records, the
  harness (`corruption_eval`, invariance, `score_page`) has to carry the HTML. That is deferred
  to step 3.
- **Structure is per page and per run, not stored.** Re-interpretation from saved answers stays
  possible, but each step needs the usual laptop re-interpretation and Gold refresh.
- **Classless and hashed-class pages fall back to level 3 or to positional rules.** Name and
  price blocks can share one signature there; text shape separates them.
- **`method_version` length.** It is 127 of 128 characters after `validator-v10`. A
  `resolve-v5` that lengthens the name needs shorter names or a migration (P8-16 note).

## Owner questions

- **Q1. Architecture and order.** Adopt D1 (one `PageStructure`, from the existing re-parse,
  with no segmenter change) and D4's order: [5d] first, then [5c], then [5]/[5b] once the harness
  carries HTML. *Recommended.*
- **Q2. The hierarchy.** Accept D2 as stated:
  - membership, then class × shape, then path × shape for classless blocks only, then position as
    a tie-break;
  - text shape as a veto;
  - structure decides relations, not existence.

  *Recommended.*
- **Q3. Section-like titles: the design fork.** A record whose title is unpriced and holds two
  or more priced label lines is a dish with options (Nachos) or a heading over items ("Asian
  Can Drinks", "Sauces", "Add-Ons"). Choose one:
  - (a) **The page's price-slot test.** Anchor the lines on the title only when the page's dish
    records normally have a price slot and this record lacks it. Unmeasured; built and
    measured in step 1's amendment. *Recommended.*
  - (b) Anchor only lines whose label is a choice ("/", "or", ",") or a size word. Text-based,
    and it misses size lines such as "Short Stack (2)".
  - (c) Anchor all label lines. Measured as wrong on section cards: 1 of 6 label-line records,
    5 of 11 choice-line records.
- **Q4. Choice lines become one variant per choice.** "Chicken / Bistec / Pastor $14.99" is three
  variants at 14.99, as the owner's choice-list ruling says. Relabel santopatio's dev page
  (`e6942e6d1e2a`, labelled with whole-line variants) and the gold problems of the record's
  3.4 (cases 11, 28, 33/38) in the next labels pass. *Recommended: yes to both.*
- **Q5. Class signature tokens.** Keep `dom_sections.signature` (the first class token)
  unchanged, rather than all tokens. All tokens gain 0.013 oracle accuracy, inside the interval,
  and would change [5c]/[5d] outputs. *Recommended: keep.*
- **Q6. Harness page set.** From now on, report dev results primarily on the item-labelled
  pages (420 with saved answers). Keep the 793-page figures for continuity. The 373
  classifier-only labels add only to kept precision and accepted-unmatched. *Recommended.*
- **Q7. Form.** A new ADR-0021 for the cross-stage architecture, with each build step an
  ADR-0013 amendment (step 1 next), rather than one large ADR-0013 amendment. *Recommended.*

## Owner decision

2026-10-26, all as recommended:
- **Q1.** Adopt D1 and D4's order. One `PageStructure` from the existing re-parse, with no
  segmenter change. [5d] first, then [5c], then [5]/[5b] once the harness carries HTML.
- **Q2.** D2 as stated: membership, then class × shape, then path × shape for classless blocks
  only, then position as a tie-break, with text-shape vetoes. Structure decides relations, not
  existence; ADD stays as Amendment 29 built it.
- **Q3 (a).** The page's price-slot test decides section-like titles. A card's lines move onto
  its title only when the page's dish cards normally have a price slot and this card lacks it.
  It is built and measured in step 1.
- **Q4.** One variant per choice. Santopatio's dev label (`e6942e6d1e2a`) and the record's 3.4
  gold problems (cases 11, 28, 33/38) are relabelled in the next labels pass (labels-v10.2),
  before step 1 is measured.
- **Q5.** Keep `dom_sections.signature` (the first class token).
- **Q6.** Dev results are reported primarily on the item-labelled pages (420 with saved
  answers). The 793-page figures are kept for continuity.
- **Q7.** ADR-0021 is the architecture; each build step is its own ADR-0013 amendment (step 1:
  Amendment 33, `resolve-v5`).
- **Q8 (brand titles, a sub-fork from the record's 3.4).** RE-NAME does not move a row named by
  a short, non-description line in the card onto the title ("AUSTIN EASTCIDERS" /
  "Pineapple Cider" / "$7" keeps "Pineapple Cider"). Only description, option and alt-text
  names move. Labels name the dish line.

## References

- Record: [2026-10-26-p8-17-html-structure.md](../reviews/2026-10-26-p8-17-html-structure.md)
- Gap audit: [2026-10-26-p8-x-gap-audit.md](../reviews/2026-10-26-p8-x-gap-audit.md) (F2, F4)
- ADR-0013 Amendments 28 ([5c]), 29 ([5d]), 30–31 (validator-v9, v10)
- Code: `packages/helios_parsing/{segment,dom_sections,page_template,validator,stitch,output,resolve,menu_shape}.py` at 08bb684
