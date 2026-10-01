# Course labeller evaluation: `<set>` (ADR-0016 §4, slice 1)

<!--
Template for the recorded comparison of the two course labellers. Copy this file to
docs/reviews/<YYYY-MM-DD>-course-labeller-<set>.md and fill it in. The tables come
from `python -m apps.menu_pipeline.course_eval score` (it prints them) and `compare`.
Labels, predictions and reports stay in gitignored var/. Only counts and rates go here.
-->

The recorded evaluation that picks the course labeller for `gold.price_index`
(session <id>, <date>).

## Label set

- **Set:** `<set>`, guide `course-guide-v<n>`, drawn from extraction
  `<method_version>`.
- **Seed:** `<seed>`. Venues: <sampled> of <requested> (test share 0.4, realized
  <test venues>/<sampled>).
- **Excluded:** <n> venues (P5-5 held-out<, earlier sets>), exclusion sha256
  `<prefix>`.
- **Sections:** <train> train, <test> test. Test priced items: <n>. Unsectioned
  share of test venues: <share> (no labeller can reach these).
- **Labelling:** agent `<id>`, blind. Owner review: <confirmed> disagreements
  confirmed, <changed> changed.
- **Guide changes while labelling the training split:** <none / list>.

## Arms

| Arm | Labeller version | Tuned on | Abstain threshold |
|---|---|---|---|
| A. Lexicon (baseline) | `<version>` | train split | <t> |
| B. Embedding + LR | `<version>` | train split, venue-grouped CV (C = <c>) | <t> |

## Results (test split, item-weighted)

### A. Lexicon

<paste `score` output>

### B. Embedding + LR

<paste `score` output>

## Decision

- **Winner:** <labeller version | none> (`compare`: covered <a> vs <b>; an exact
  tie goes to the baseline).
- **Passing courses (the pin):** <list>.
- **Not indexed:** <failing courses and why: precision, or not readable (< 20
  sections or < 10 venues)>.
- **Findings for the owner:** <confusions that matter, e.g. alcohol read as drink;
  extraction errors seen while labelling; edge cases for the next guide version>.
- **Next:** <slice 2 (Silver table and labeller CLI), or what has to change first>.
