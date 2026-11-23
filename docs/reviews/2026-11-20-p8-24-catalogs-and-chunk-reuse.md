# P8-24: store catalogs in the page check, and cheaper Pi extraction (measurements)

Session P8-24, 2026-11-20, on the laptop, alongside the P8-23 Pi recrawl run by another
session. Measurements and two proposals:
- **§1 store catalogs:** the owner's 2026-11-20 decision on #169 Q2 ("catalogs → page check,
  measured on the next precision sample"). The rule is small and generic, so it is built:
  ADR-0015 Amendment 4, `place-v3`, in #171.
- **§2 chunk-answer reuse:** ADR-0013 Amendment 37, proposed here, not built.

**Nothing live was written.** `helios_laptop` and the Pi are untouched. The databases used are
scratch: `helios_p824_test`, restored from `var/laptop-run/helios_work-2026-11-19-p8-23.dump`
(`helios_work` after P8-23's batch 2, equal to public at that swap: 99,553 Gold rows), and
`helios_p824unit_test` for the tests. From the Pi, read-only:
- the list of menu-page Versions observed since 2026-11-19 08:00Z: a `SELECT` in a read-only
  transaction on `helios_work`;
- its `var/replay`: streamed out through a read-only Docker mount as the worker's uid, since
  the files are 0600;
- `var/p823/logs` and the loop's progress log.

Artefacts are untracked, in the main checkout's `var/p8-24/`: `precision/` (§1), `chunks/`
(§2) and `pi/` (the Pi copy). This file keeps counts, hosts and URLs only.

## 1. Page-check precision, and store catalogs

### 1.1 Frame and draw

- **Pool** (`pool.py`). The 3,194 menu-page records' latest Versions:
  - 3,030 are live (resolved, not R4-rejected, with a bundle);
  - they hold 1,692 distinct texts;
  - **823 texts were never labelled**: not in P8-21's seen hashes, its precision draw or its
    §8 held-out draw.

  770 of the 823 were observed in October, 53 in P8-23's batches 1–2. "Recent" is read as
  this unlabelled live set. The Pi's batch 3 and later texts are left out: their state lives
  in the Pi's database, and page kinds don't change with a refetch.
- **Random part** (`draw.py`): a simple random sample of **200 texts**, seed **20261120**
  (`draw.json` sha256 `5dba0f3a…`). 60 platform pages, 140 own-site.
- **Purposive part** (reported apart, never in the estimate):
  - every live text on an amazon/walmart host: the Amazon grocery aisle, 2 records;
  - every own-site live text with a #170 article path (`ARTICLE_SEGMENTS`): 8 texts.

  The Walmart page and 3 article-path pages fell in the random part. 209 pages in all.

### 1.2 Labels

- **Brief** (`LABELLING.md`): `menu`, `catalog`, `article` or `other`. `other` carries a kind:
  `item`, `hub`, `nutrition`, `event`, `empty` or `misc`.
  - `menu` follows the P8-21 brief.
  - `catalog` is a store's product listing (groceries, retail goods, merchandise).
  - An article that also prints a priced menu list is `menu`.
- **First pass:** 12 Sonnet subagents, 16–18 offline packets each (about 170,000 characters,
  balanced by size). They saw neither the part nor any score. Several said they skimmed the
  ends of long packets.
- **Re-check** (this session, P8-21's rule), 92 queued:
  - every non-menu label (23);
  - every low-confidence label (30);
  - every `menu` with fewer than 5 priced body blocks (58).

  All reasons were read and 3 packets read in full. **2 labels changed:**
  - Cotton Patch's "Daily Lunch Specials" news post → `menu`: it prints a 7-meal priced list,
    which matches #170's finding;
  - Pizza Inn's "Sandwiches & Pasta" → `other/hub`: one dish and category blurbs.

### 1.3 Result: `classifier-v2+v3` precision on the random part

| | Pages | Precision | Wilson 95 % |
|---|---|---|---|
| All (single-item pages are not menus) | 200 | **0.920** (184) | [0.874, 0.950] |
| All (single-item pages are menus) | 200 | 0.950 (190) | [0.910, 0.973] |
| Platform pages | 60 | 0.967 (58) | |
| Own-site pages | 140 | 0.900 (126) | |

P8-21's sample (a different pool: P8-20's new pages) gave 0.890 [0.839, 0.926].

**The 16 false accepts, by kind:**

| Kind | Pages | Examples |
|---|---|---|
| `item` | 6 | one taco, one platter, one brioche, one soft-serve page, two sandwiches |
| `hub` | 4 | category tiles (RA Sushi), collapsed catering categories (Dickey's), Subway's category list, Pizza Inn |
| `article` | 2 | two recipe posts |
| `empty` | 2 | Grubhub Chick-fil-A pages: "This menu isn't available right now" |
| `catalog` | 1 | Walmart's meal-planning page |
| `event` | 1 | a ticketed wine dinner |

- **Cost:** they put **16 rows in Gold**. 13 of the 16 put none; Walmart puts 14 and two hubs
  1 each. The 184 menus carry 14,859.
- **No threshold separates them.** Raising both classifiers' thresholds until the Walmart page
  fails (v2 0.82, v3 0.79) loses 28 of the 184 menus and drops 9 of the 16.
- **The purposive pages:**
  - the Amazon aisle is a `catalog`;
  - of the 8 article-path texts, 6 are `article` and 2 are `menu`: Cotton Patch's specials
    post and The Human Bean's Shopify drink list, the two #170 names;
  - the random part's 3 article-path pages are 2 Human Bean drink lists (`menu`) and 1 recipe
    post (`article`).

### 1.4 Catalog signals, and the rule

Generic store signals, counted in the body blocks of all 1,692 live texts (`score.py`,
`gold.py`):

| Signal | Texts with ≥ 1 | On the two catalogs | Verdict |
|---|---|---|---|
| Unit price (`$2.23/lb`, `59.5 ¢/oz`) | 45 | Walmart 12, Amazon 0 | fires on BBQ by the pound, crawfish by the pound |
| Pack size (`Pack of 12`, `6-pack`, `12 Count`) | 75 | 15, 42 | fires on beer, taco boxes, a bakery's own goods |
| Net quantity (`32 Ounce`, `1 L`) | 766 | 36, 72 | drinks and steaks print sizes |
| Star rating ("out of 5 Stars") | 1 | Walmart only | misses Amazon |
| "Add to cart" block | 1 | Amazon only | misses Walmart |
| **List or struck price** (`List Price`, `Typical price`, `Was $N`, `Compare at $N`) | **3** | **20, 11** | the third is one DoorDash menu with 1 |

**The rule** (`store_catalog`, built in #171, ADR-0015 Amendment 4): a page is a store catalog
when at least 3 body blocks print a list or struck price. It runs as part of the place check,
now `place-v3`. It uses no store's own words, and no host, platform or venue list.

- **Every live text:** it fires on 2 texts, 3 records, both `catalog`: precision 2/2, recall
  2/2 of the known catalogs.
- **Every stored menu-page bundle** (2,951, laptop and Pi, older Versions included): only the
  Versions of those two pages fire. The two DoorDash Chick-fil-A pages print one "Was $"
  block each.
- **`place_sweep --dry-run` on `helios_p824_test`:** 3,012 checked, `store_catalog` 3,
  `wrong_place` 0, `other_location` 0.
- **Cost if applied:** 98 Gold rows (42 + 42 + 14). Three venues lose their only menu, which
  was never theirs.
- **Recall on unseen catalogs is not measured.** The rule was picked after looking at both
  known catalogs, and the corpus holds no third. A catalog that prints one price per product
  and no struck prices is missed.

## 2. Cheaper Pi extraction: chunk-answer reuse and volatile text

### 2.1 Data

- The Pi's Versions observed since 2026-11-19 08:00Z: 471 rows; 451 in batches 1–6 (batch 7
  was running).
- The bundles from the Pi's `var/replay` copy.
- Saved answers under the live extractor (`…;prompt-v2.4;chunk-v2.3;segment-v2`). Each
  answer has every chunk's raw output, `wall_s`, prompt and generated tokens.

A run page **went to the model** when its text had no saved answer before it: production's
rule. The pre-run corpus is the 2,016 texts answered before the run. **112 pages, 918
chunks, 117,175 slot-seconds.** 108 of the pages have an older Version. The run's own logs
count 121 pages and 987 chunks; the reconstruction finds 9 pages fewer (not traced).

### 2.2 How much could have been reused (`reuse.py`, `walltime.py`, `bykind.py`)

| Scheme | Chunks | Avg characters | Model time reused | Characters reused |
|---|---|---|---|---|
| exact chunk-v2.3 strings (P8-23's 21%) | 918 | 1,273 | 0.231 | 0.228 |
| chunk-v2.3, block ids renumbered chunk-locally | 918 | 1,204 | **0.410** | 0.385 |
| the same, volatile text out of the key | 918 | 1,152 | 0.414 | 0.406 |
| content-defined cuts, min 600 characters, anchor 1/8 | 1,899 | 677 | n/a | 0.517 |
| content-defined, min 1,000, anchor 1/8, volatile out | 1,118 | 978 | n/a | 0.483 |
| content-defined, min 600, anchor 1/4, volatile out | 2,015 | 625 | n/a | 0.546 |
| content-defined, min 1,200, anchor 1/2 (today's size) | 980 | 1,141 | n/a | 0.399 |

- **By host kind** (model time, renumbered ids): platform 0.156 of 24,945 s, own-site 0.479
  of 92,230 s. Platform pages are 21% of the model's time.
- **Chrome-only changes:** 21 own-site pages changed only in lines the model is never sent.
  Exact matching reuses 41 of their 88 chunks, renumbered matching all 88.
- **The reuse source barely matters:** the record's previous Version gives 0.382, every
  earlier answer 0.383.

### 2.3 What changes on delivery-platform pages (`diffs.py`, `volatile.py`)

Each changed line between a model page and its previous Version is sorted into one of four
classes:
- **chrome:** not sent to the model;
- **volatile:** sent, and empty once ratings, preorder times, fees, distances, hours,
  "Sold Out", lone separators and "<name> logo" are removed;
- **moved:** its volatile-stripped form is also on the other side;
- **content:** everything else.

| | Pages | Changed lines | Chrome | Of the sent: volatile | moved | content | content with a `$` price |
|---|---|---|---|---|---|---|---|
| Platform (Grubhub 13, Uber Eats 6, DoorDash 5, Toast 3, Clover 1) | 28 | 5,632 | 1.8% | **48.5%** | **38.9%** | 12.6% | **78 lines (1.4%)** |
| Own-site | 80 | 5,504 | 5.3% | 0.0% | 24.7% | 75.3% | 1,657 lines |

- **What churns, by platform:**
  - Grubhub: "Preorder for …", its own rating and rating count, fees, and a nearby-restaurants
    carousel (logo, rating, minutes, miles), all in body blocks;
  - Uber Eats: item ratings joined to the price (`$5.69 • 93% (108)`), reordered "most liked"
    items, dated customer reviews, neighbourhood link lists in chrome;
  - DoorDash: item ratings and "#3 Most liked", reordered featured items;
  - Clover: today's hours and "Sold Out".
- **Platform content lines** are mostly other restaurants' names and reviews.
- **Real menu changes are rare on platforms** and common on own sites.

### 2.4 Pages that come back to a known text

In batches 3–6, 279 of the 346 changed records returned to a text answered before (progress
log: 106/121, 100/118, 34/47, 39/60). Page-level reuse already serves those with no model
call: pages alternate between known states.

### 2.5 Proposal

ADR-0013 Amendment 37 (this PR):
- **Stage 1:** a chunk-answer store keyed by the chunk text with renumbered block ids, and the
  saved answer's ids mapped back. Model time reused 0.231 → 0.410, with the chunker
  unchanged. Recommended.
- **Stage 2:** volatile text out of the key, +0.004. Not proposed.
- **Stage 3:** content-defined boundaries. A new chunker, so a §8 GPU check and a full
  re-extraction. Not proposed now.

Owner questions Q1–Q4 are in the amendment.

## 3. Decisions

None were delegated for this session's design questions. Every choice below was listed for
the owner, with the session's default. **The owner accepted all of them as recommended on
2026-11-20**, including ADR-0015 Amendment 4 Q1–Q4 (#171) and ADR-0013 Amendment 37 Q1–Q4:
- **"Recent" texts:** read as the unlabelled live set (§1.1).
- **Two re-check label changes** (§1.2).
- **Catalog rule placement** (place check, not the classifier) and its threshold of 3:
  ADR-0015 Amendment 4, Q1–Q2.
- **Stage 1 as the recommended chunk change:** ADR-0013 Amendment 37, Q1–Q4.

## 4. Scratch state

- `helios_p824_test` (restored P8-23 dump) and `helios_p824unit_test` (tests): drop when the
  #171 merges.
- The Pi copy in `var/p8-24/pi/` (287 MB) can be deleted once §2 is reviewed.
