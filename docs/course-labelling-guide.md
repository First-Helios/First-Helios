# Course labelling guide (`course-guide-v1`)

How a menu section gets its course label for the price index:
[ADR-0016](./adr/0016-course-labels-for-the-price-index.md) §1 and its
[Amendment 1](./adr/0016-course-labels-for-the-price-index.md#amendment-1-2026-09-30-accepted-slice-1a-decisions).
Agents labelling a set follow this guide. Owners use it when they confirm
disagreements. The harness is `apps/menu_pipeline/course_eval.py` (pure part:
`packages/helios_parsing/course_eval.py`).

**Frozen before a test split is labelled.** Edge cases found while labelling the
*training* split may be added. Once any test section of a set has a label, the guide
is frozen for that set: a change after that is a new guide version
(`course-guide-v2`), recorded in the next set's manifest, and every set labelled
under the old version has to be relabelled before it is scored with the new one.

## 1. The nine labels

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

A gold label is always one of the nine. The agent never abstains: when nothing
fits or the items disagree, the label is `other`. Abstaining is something the
*labellers* being evaluated do, not the people labelling.

## 2. How to decide

Each section gets **one** label, worked out in two steps.

1. **Each item's course, by precedence.** Take the first rule that applies:
   1. `other`: the item is not one dish course: catering, a family pack or
      party tray, a bulk order (by the dozen, pound, gallon), a sauce, dressing,
      topping, extra or add-on, merchandise, a gift card.
   2. `kids`: the item is for children (it's in a kids section, or its name
      says so: "Kids Burger").
   3. `breakfast`: a breakfast or brunch dish (eggs, pancakes, breakfast
      tacos, kolaches, chilaquiles…).
   4. Otherwise the dish course: `appetizer`, `entree`, `side`, `dessert`,
      `drink` or `alcohol`.

   So a kids breakfast plate is `kids`, and a breakfast-taco family pack is
   `other`. A labelled course keeps kids and breakfast prices out of the other
   courses' medians, which is why there is one label per item (Amendment 1).
2. **The section's label: strict majority of its priced items.** The section
   takes course *c* when more than half its priced items are *c*. If no course
   has more than half, the label is `other`. Count unpriced items only when the
   section has no priced item at all.

What you see: the section's name path, its item names and its priced-item
count (the label file's `name_path`, `items` and `priced_items`). Label
**blind**: never look at either labeller's output, and never open the page,
the price index or another set's labels. Judge by what the items are, not by
prices.

## 3. Edge cases

**Salads and soups.**
- A salad with a protein, sold as a meal ("Chicken Caesar", "Cobb") → `entree`.
- A house, side or starter salad → `appetizer`, or `side` when it sits among
  the sides.
- "Soups & Salads", "Soup & Salad" sections → `appetizer`, unless most of
  their items are meal salads.
- Soups on their own → `appetizer`.

**Shakes, ice cream, coffee drinks.**
- Shakes, malts, floats, smoothies, boba, milk tea, aguas frescas, lattes →
  `drink`.
- Sundaes, scoops, cones, ice-cream sandwiches → `dessert`.
- A "Shakes & Sundaes" section → the strict majority.

**Mixed drinks and alcohol.**
- Each item counts by what it is: beer, wine, cocktails, spirits, seltzers and
  dessert wine → `alcohol`; mocktails and non-alcoholic beer → `drink`.
- A "Drinks" or "Bar" list takes the strict majority of its priced items, else
  `other`.

**Service-period headings** ("Lunch", "Dinner", "Late Night", "Happy Hour",
"All Day").
- They name a time, not a course, so label by the items.
- A "Lunch" list of mains → `entree`.
- A "Happy Hour" list that is mostly cocktails and beer → `alcohol`.
- A happy-hour list of drinks and bites with no majority → `other`.
- Breakfast and brunch dishes are `breakfast` whatever the heading.
- A happy-hour price is still a price, and the course label doesn't change
  that. Promotions are labelled separately
  ([ADR-0013](./adr/0013-phase5-menu-pipeline.md) Amendments 3 and 5).

**"Specials"** ("Chef's Specials", "Daily Specials", "Features").
- Label by the items: specials that are all mains → `entree`.
- A mix with no majority → `other`.

**Meals and combos.**
- A combo of a main plus a side and drink → `entree` (the main defines it).
- "Plates", "Platters" and "Dinners" of single servings → `entree`.

**Small plates.**
- "Small Plates", "Tapas", "Shareables", "For the Table", "Bites", "Chips &
  Dips", bread service → `appetizer`.

**Sides vs extras.**
- A side is a dish ordered beside a main ("Fries", "Rice & Beans", "Mac &
  Cheese") → `side`.
- Something that modifies a dish → `other`: "Add Avocado", "Extra Cheese", "Add
  a Protein", sauces, dressings, toppings.

**Bakery and pastries.**
- Sweet pastries, cookies, cakes and pies → `dessert`.
- Savoury breakfast bakes (kolaches, breakfast sandwiches) → `breakfast`.
- A café "Bakery" case takes the strict majority.

**Kids.**
- Every item in a kids section is `kids`, drinks and desserts included, so the
  section is `kids`.

**Nested sections.**
- Label the leaf section and use its parents as context: "Drinks › Beer" →
  `alcohol`; "Kids › Drinks" → `kids`.

**Not menu content.**
- A section that reached the set but isn't food or drink for sale (hours, an
  allergen notice, a promo banner) → `other`.
- Write it down as a finding, because it points at an extraction error.

When an edge case isn't covered here, choose the label that keeps the index's
medians honest. While labelling the training split, add the case to this list;
during the test split, label it `other` and note it for the write-up.

## 4. Procedure

1. **Exclusions.** Build the exclusion file: one GERS id per line, `#` for
   comments. It holds the venues of the P5-5 held-out pages, plus every venue
   in an earlier label set when this is a later version's fresh sample. Never
   open those venues' pages or sections.
2. **Draw** (`course_eval sample`): from the candidates file (every Gold-reaching
   named section of current Menu pages, exported in slice 1b), with a recorded
   seed and ~120 venues. The venue's split (~60% train / ~40% test) comes from
   a seeded hash and is written into each row. A drawn set is never redrawn
   over; the loader refuses a row whose split has moved.
3. **Label** (agent, blind). Set `agent_label` and `label` to the same course,
   and `labeller` to the agent's id; leave `owner_confirmed` false. Do the
   training split first; the guide freezes before the first test label (above).
4. **Tune** each arm on the training split only (ADR-0016 §4).
5. **Predict** with each arm over every section: one JSONL row per section
   (`section_key`, `course` or null to abstain, `confidence`, `labeller`).
6. **Review** (`course_eval disagreements`): it lists the test sections where
   an arm predicted a course different from the agent's label. An abstention is
   not a disagreement. For each one the owner sets `label` to the confirmed
   course and `owner_confirmed` to true, leaving `agent_label` untouched (it
   gives the disagreement tally).
7. **Score** each arm once (`course_eval score`). It refuses while any test
   section is unlabelled, unpredicted or awaiting review, or if the exclusion
   list differs from the one the set was drawn with.
8. **Compare** (`course_eval compare BASELINE MODEL`) and write the results up
   in `docs/reviews/`, from
   [the template](./reviews/templates/course-labeller-evaluation.md).

Labels, predictions and reports stay in gitignored `var/`
(`var/course-labels/<set>/`, `var/course-eval/<set>/`). Only counts and rates go
into `docs/reviews/`.

## 5. The gate, as the harness reads it

These are the test-split numbers. Each section is weighted by its priced items.

- **Precision** for course *c*: of the priced items in sections an arm labelled
  *c*, the share whose confirmed label is *c*.
- **Readable**: at least 20 such sections, from at least 10 venues. A course
  below that isn't emitted whatever its precision (too few test items to read).
- **Passes**: readable, with precision ≥ 0.95. `other` is never an index row.
- **Coverage**: priced items whose section an arm labelled with a passing
  course, over all test items.
- **Winner**: more covered items wins. An exact tie goes to the lexicon. No
  winner if neither arm passes a course.
