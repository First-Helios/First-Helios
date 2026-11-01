# Page-check precision on P8-20's new pages (P8-21, owner Q2)

Session P8-21, 2026-11-01. Measurement only: no pipeline, model, schema or `infra/` change, and
no database written. The owner asked (ADR-0025, Owner answers, Q2) for a larger sample than the
§8 held-out's 50 pages before any verifier change.

Version: the production page check `classifier-v2+v3` (ADR-0013 Amendment 27), as saved on
`helios_laptop` after P8-20's re-collection. Page bodies, packets and labels stay untracked in
`var/p8-21/precision/` (worktree `p8-21-d2prime`). This file keeps counts and URLs' hosts only.

**Result: precision 0.890 (178 / 200), Wilson [0.839, 0.926], below the 0.95 bar.** Counting
single-item detail pages as menus, 0.940 [0.898, 0.965], still below it.

## Frame and draw

- **Pool:** the §8 held-out's `pool-kept.json` (P8-21 held-out record): 1,016 distinct page
  texts that are live (`resolved`, not rejected), new since P8-20 (2026-10-28) and unseen by any
  earlier labelling, with the coverage set's hosts excluded. Every one passed the production
  page check.
- **Draw** (`prdraw.py`): the 50 held-out pages removed (966 eligible), then a simple random
  sample of **200 texts**, seed **20261102** (`draw.json` sha256 `51bf22bb…`). Page-level, not
  one page per host, so the estimate is the pool's page precision.
- 154 own-site pages, 46 platform pages (Toast, DoorDash, Uber Eats, Grubhub, Clover).

## Labels

- **Brief** (`LABELLING.md`): the §8 held-out's page label (`menu`: the page prints a
  restaurant's menu items, priced or not; partial menus count; another location's or another
  restaurant's menu still counts), with a kind for `not_menu`: `hub`, `article`, `product`,
  `other`; or `empty`.
- **First pass:** 10 Sonnet subagents, 20 pages each, from offline packets (body blocks, chrome
  marked; 45,000 characters at most). Several said they skimmed the ends of long packets.
- **Re-check (this session):** every `not_menu`, every low-confidence label, and every `menu`
  label on a page with fewer than 5 priced body blocks (59 pages), plus a URL scan of the rest
  and 5 spot checks. 14 labels changed:
  - 10 **single-item detail pages** (one dish or product, its nutrition or cart) were split
    between `menu`, `product` and `other`. They get their own kind, `item`, and are reported
    both ways;
  - 2 pages the first pass called hubs print dishes (6 named breakfast tacos; dish cards), so
    `menu`;
  - P.F. Chang's "Menu Nutritionals To Go" (a nutrition table of every dish) is `not_menu`.
- One `menu` page is an SEO copy of another restaurant's drink menu with prices, on a
  restaurant's own site (Din Tai Fung's on a pizzeria's). It counts as `menu` by the brief.

## Result

| | Pages | Precision | Wilson 95 % |
|---|---|---|---|
| All (single-item pages are not menus) | 200 | **0.890** (178) | [0.839, 0.926] |
| All (single-item pages are menus) | 200 | 0.940 (188) | [0.898, 0.965] |
| First pass alone | 200 | 0.895 (179) | [0.845, 0.930] |
| Own-site pages | 154 | 0.857 (132) | |
| Platform pages | 46 | 1.000 (46) | |

**The 22 false accepts, by kind:**

| Kind | Pages | Examples |
|---|---|---|
| `item`: one dish or product | 10 | a dish page with nutrition (Hawaiian BBQ, Snap Kitchen, 85C), a shop product (a cookie set, a pound-cake slice) |
| `article` | 4 | a press release, a food article, a restaurant blog post, a recipe roundup |
| `product` | 3 | a pre-order tart box, a ticketed dinner, cake-tasting appointments |
| `other` | 3 | a nutrition table, category prose, a food-truck booking page |
| `hub` | 2 | empty category accordions, category navigation |

The §8 held-out's five (a recipe article, a press release, two hubs, a ticketed dinner) are the
same kinds. P8-20's several-pages discovery (ADR-0022) reaches deeper own-site pages, where
single-item pages and posts live.

## What the false accepts cost

Gold rows carried by each drawn page's menu-page record (`helios_laptop`, read-only):

| Page | Gold rows: 0 | 1 | 2–4 | 5+ |
|---|---|---|---|---|
| menu (178) | 32 | 5 | 6 | 135 |
| not menu (22) | **19** | 1 | 0 | 2 |

- 19 of the 22 put nothing in Gold: extraction finds no items, or the validator rejects them.
  They cost extraction time only.
- **Three carry 329 priced rows**, and one class is harmful:
  - **P.F. Chang's nutrition table: 317 priced rows, all false.** Calories and servings were read
    as prices: Chang's Chicken Lettuce Wraps at $330.00 (330 calories), BBQ Pork Spare Ribs at
    $2.00 (2 servings).
  - Cake-tasting appointments: 11 rows; a category hub: 1 row.
- **The nutrition-table class over the whole of Gold** (records whose page path names
  nutrition): **5 records, 1,354 priced rows**, all of this shape. The same P.F. Chang's page is
  stored for 4 venues (317 rows each), plus one other `/menu-nutritionals/` page (86 rows).
  Only the path was searched, so this is a floor.

## Artefacts (untracked, `var/p8-21/precision/` in worktree `p8-21-d2prime`)

`prdraw.py`, `draw.json` (+ `.sha256`), `packets/`, `LABELLING.md`, `prdeal.py`, `deal.json`,
`labels/P01–P10.json` (first pass), `prcheck.py`, `recheck-queue.json`, `prview.py`,
`prscore.py` (the re-check's decisions, with reasons), `labels-final.json`, `report.txt`,
`pritems.py`.
