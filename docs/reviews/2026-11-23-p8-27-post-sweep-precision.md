# P8-27: the page check's precision after the swap-4 sweep (#170, #171)

Session P8-27, 2026-11-23, on the laptop. This is a measurement only; no code or data changed.
It follows the P8-24 method (record
[2026-11-20-p8-24-catalogs-and-chunk-reuse.md](./2026-11-20-p8-24-catalogs-and-chunk-reuse.md)
§1) on the data after P8-23's swap 4. That data has #170 (article pages, ADR-0015 Amendment 3)
and #171 (store catalogs, place-v3, ADR-0015 Amendment 4) applied by `place_sweep`. The sweep
withdrew 61 records (58 `article_page`, 3 `store_catalog`).

**Nothing live was written.** The pool was read from `helios_p827b_test`, a scratch database
restored from `helios_work-2026-11-23-p8-23-swap4.dump` (equal to public, 98,499 Gold rows), in a
read-only transaction. The bundles came from the laptop's `var/replay`, synced at swap 4.
Artefacts are untracked, in the main checkout's `var/p8-27/precision/`.

## Result

| | Pages | Precision | Wilson 95 % |
|---|---|---|---|
| **All (single-item pages are not menus)** | 150 | **0.940** (141) | [0.890, 0.968] |
| All (single-item pages are menus) | 150 | 0.973 (146) | [0.933, 0.990] |
| Platform pages | 49 | 0.959 (47) | |
| Own-site pages | 101 | 0.931 (94) | |

P8-24's random part, on the pool before the sweep, gave **0.920 [0.874, 0.950]**. The two
intervals overlap, so the samples show no significant change. The gain matches what #170/#171
target: **no catalog and no article page was drawn**, against 3 of 16 false accepts in P8-24.

**Catalogs and articles left after the sweep.** P8-24's purposive check (every live text on an
amazon/walmart host, or an own-site text with an `ARTICLE_SEGMENTS` path) finds **none**. Before
the sweep, P8-24 found the Amazon aisle (2 records) and 8 article-path texts. 2 of those 8 were
real menus: Cotton Patch's priced lunch-specials post, which the sweep withdrew (2 venues lost
their menu at swap 4), and a Human Bean drink list. That is the accepted cost of #170's
path rule.

## The 9 false accepts

| Kind | Pages | Examples |
|---|---|---|
| `item` | 5 | Huddle House product pages ×2, a Cuban breakfast sandwich, a Snap Kitchen snack bar, a pound-cake slice |
| `event` | 2 | a ticketed wine dinner, a bakery's cake-tasting appointments page |
| `empty` | 1 | a Grubhub Chick-fil-A page: "This menu isn't available right now" |
| `misc` | 1 | Bruster's "how to order" cake/pie guide (size and layer options, no named dishes or prices) |

Single-item pages remain the largest kind, as in P8-21 and P8-24.

## Frame, draw and labels

- **Pool** (`pool.py`): the live menu-page states (resolved, not R4-rejected, with a bundle),
  one per distinct text, less every text labelled before. That excludes P8-21's seen hashes, its
  precision and held-out draws, and P8-24's draw.
  - 3,297 states, 2,864 live, 1,720 distinct live texts.
  - **1,010 never labelled**: 235 observed in October, 775 in November.
- **Draw** (`draw.py`): a simple random sample of **150 texts**, seed **20261123** (`draw.json`
  sha256 `1cb9ae7e…`); 49 platform, 101 own-site. The purposive part was empty (above).
- **First pass:** 9 Sonnet subagents with P8-24's brief (`LABELLING.md`, unchanged), 16–17
  packets each. They saw neither scores nor the part.
  - Result: 141 `menu`, 5 `item`, 2 `event`, 1 `misc`, 1 `empty`.
  - Several labellers said they decided long packets from their first 3,000–5,000 characters,
    and two wrote one generic reason for most pages. So the first pass is read as a screen.
- **Re-check:** a second, independent Sonnet pass, 6–7 packets each. It was told to read every
  line and to cite the deciding blocks and the number of item names. The queue used P8-24's rule:
  every non-menu label (9), every low-confidence one (17), and every `menu` with fewer than 5
  priced body blocks (43). That is **58 pages**.
  - The two passes agree on 57.
  - The one disagreement, the Bruster's cake and pie guide (`menu` on re-check), was read in full
    by the session and kept as `other/misc`.
- **Limit:** the 92 high-confidence menus with 5 or more priced body blocks were labelled once,
  by a pass that sometimes skimmed. A skim errs toward `menu` only when the page's top prints
  dishes. P8-21's and P8-24's re-checks changed 2 of 92 queued labels and none outside the queue
  rule, so the residual error is likely small, but it is not measured here.

**Judgements the brief leaves to the labeller,** applied as in P8-24:
- a delivery page that prints only 6 "featured" items over empty categories is `menu`
  (partial menu);
- a closed Uber Eats store that still prints its dishes is `menu`.
