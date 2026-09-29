# classifier-v1 evaluation (ADR-0013 §8)

The recorded evaluation that lets page classifier `classifier-v1` ship as ADR-0015's
menu-page verifier (session S6d part 2, 2026-09-29). Page bodies and labels stay in
gitignored `var/`, as in the spike; this file keeps the numbers.

## What was trained

- **Configuration, frozen by the spike** before any of the held-out venues existed:
  `potion-base-8M` embedding of `page_text` (title, URL path, headings, body; 2,000
  characters) plus the seven layout features in `packages/helios_parsing/page_features.py`,
  standardized, logistic regression `C = 0.5`; threshold = the lowest one whose
  venue-grouped out-of-fold precision reaches 0.95.
- **Changed from the spike:** the price tokens behind the layout features are the
  validator's v3 regex (the spike's stage D used v2). Nested cross-validation below
  reproduces the spike's numbers exactly.
- **Data:** spike page labels (branch `spike/menu-model`, `spikes/menu_model/labels/pages`),
  `menu` vs `not_menu` only (menu hubs are `not_menu`; `js_only` and `empty` pages are
  excluded, as in the spike). First candidate export: 179 pages, 48 menus.
  Second export (never used to choose the configuration): 9 labelled menu pages and 130
  unlabelled fetched pages.
- **Shipped weights** (`config/page_classifier_v1.json`): refit on all 188 labelled pages
  (57 menus), threshold 0.508. The plain-Python scorer reproduces scikit-learn's
  probabilities (checked by the training script).
- **Reproduce:** the command in `apps/menu_pipeline/train_page_classifier.py`'s docstring
  (about 10 s on a laptop).

## Results

| Measure | classifier-v1 | S4 heuristic (`s4-v1`) | Bar (ADR-0013 §8) |
|---|---|---|---|
| Nested CV, first export (179 pages): precision | **0.976** (40 TP, 1 FP) | 0.597 (27 FP) | ≥ 0.95 ✔ |
| Nested CV, first export: recall | **0.833** (8 FN) | 0.833 | ≥ previous verifier ✔ (tie) |
| Held-out labelled menus (9, second export): recall | **9/9** | 8/9 | ≥ previous ✔ |
| Held-out unlabelled pages (130): called a menu | 21 | 42 | — |
| …of which hand-checked as menu content | **21/21** (19/21 counting two homepages that embed the full menu as not-a-menu) | not checked | ≥ 0.95 ✔ (0.905 strict) |

- The held-out precision check labels only the pages the classifier accepted (by hand,
  this session): P. Terry's, School House Pub, MasFajitas, CraigO's, Mi Madre's (dinner,
  drinks), Bien Hoa, Corner Bakery (twice), Amici (lunch), Dimassi's, Gloria's, El Pollo
  Rico (two menus), Pollo Campero, Taco Cabana, Freebirds, Rollin Smoke, and The League
  (`/menus`). The two homepages (The League, Haymaker) print their menu items; discovery
  never accepts a homepage as a menu URL, so their verdicts don't reach saved data. It
  measures precision only; held-out recall rests on the 9 labelled menus.
- Speed: 1–32 ms per page on a laptop CPU (the spike measured 22 ms on the Pi).

## Known limits

- **Rendered platform pages** (from the S6f render probe, not in training): Square,
  Clover and Grubhub menus score 0.62–0.999, but **every rendered Toast order page is
  rejected** (0.004–0.28 despite 80–147 prices). Junk platform pages (jobs, gift cards,
  marketing signup) all score ≈ 0. S6f must label rendered platform pages and train a
  successor version before Toast menus can be saved.
- JavaScript-only pages are rejected without rendering (ADR-0013 §4).
- 48 + 9 menu pages is a small positive set; the precision estimate is the spike's
  "optimistic" CV plus a 21-page hand check, not a large held-out sample.
