# Rule "same" narrowed, resolve-v4 applied, and validator grounding proposed (ADR-0013 Amendments 29–30, P8-15)

Session P8-15, 2026-10-25 to 2026-10-26. It carries out the owner's rulings after P8-14
([Amendment 29](../adr/0013-phase5-menu-pipeline.md#amendment-29-2026-10-24-proposed-stage-5d-page-template-and-duplicate-emissions),
note at its end):
- it narrows duplicate rule "same" and re-checks it on dev;
- it applies resolve-v4 to `helios_laptop` and refreshes Gold;
- it times the stage on the Pi;
- it proposes the validator-grounding follow-on as Amendment 30. Nothing in Amendment 30 is
  built.

Scope:
- **Branch.** PR #124 (the re-land of #123) is on main as `7f75b4d`, merged to `main`. The
  P8-14 worktree was locked by a live idle session, so this session did not work in it. It
  replayed #125's four commits onto main without `04e261c`, which landed as #124. The tree is
  byte-identical to #125's head. That makes PR #126, which supersedes draft #125, without
  force-pushing #125's branch.
- **Data.** Every page came from its stored bundle, and every answer from the saved production
  answers (`var/replay/menu-extract/`, extractor
  `qwen3-4b-instruct-2507-q4_0@e0ba675d86ab;prompt-v2.4;chunk-v2.3;segment-v2`). There were no
  fetches and no model calls.
- **Writes:** Menu (re-interpretation) and Gold on `helios_laptop` only (section 4). Nothing
  was written to Bronze or identity. There was no schema, migration, dependency, model, prompt,
  chunker or segmenter change, and no per-site rule.
- **Credentials.** Database access went through `uv run --env-file`, as P8-12 did. Nobody read
  `.env` by hand.

**Result.**
- **Rule "same" narrowed** (unpriced copies stay). The test is added; 28 of 28 mutations are
  killed; `make ci` and CI's strict job (1,756 passed, 0 skipped) are green.
  - Dev is unchanged except duplicate removal: 567 → 349 rows, section exact 0.7230 → 0.7212.
  - On the P8-14 set, pages losing a gold item drop 4 → 2, and every stage bar now passes.
  - The corpus loses no price Evidence, and ungated invariance is now exact.
- **`helios_laptop`:** 1,597 pages re-interpreted with 0 failed and 0 model calls.
  - Prices written 68,795 → 70,885.
  - Gold `current_menu` 58,031 → 59,860 rows; one-item sections 2,161 → 1,976.
- **Pi:** resolve-v4 adds a median of 26 ms per page on one A76 core (154 ms against 119 ms).
- **Amendment 30 (proposed):** g1f + G3 as validator-v9.
  - Dev: +51 gold items, 0 lost; FR 0.1008 → 0.0993, catch 0.9950 → 0.9949.
  - It fixes Vivo and Paloma.
  - G2 (price before name) fixes Dahlia but false-gates normal pages. That is an owner fork.
- Owner questions are in section 8 and in PR #126.

## 1. Owner rulings recorded

Amendment 29 gains the note "Owner rulings after P8-14" (commit `55cadca`), and its status line
points to it:
- Q1, rule "same" narrowed;
- Q2, the known validator gap;
- Q3, apply and time;
- Q4, grounding next.

## 2. Rule "same" narrowed

- **`page_template.remove_duplicates`:** a printed item's extra copies go only when every copy
  cites the same **non-empty** set of printed price spans. Unpriced copies stay, because the
  validator may have grounded a second printed dish onto the first print. The change is one
  condition, and the module and function docstrings were updated with it.
- **Version.** `RESOLVER_VERSION` stays `"resolve-v4"`: #125 (now #126) is not merged.
  `method_version` stays 126 characters.
- **Test.** `test_duplicate_removal_same_rule` gains two cases:
  - two unpriced copies of "Pork Taco" under two model sections, both `downgrade` with name
    Evidence and no price Evidence, are both kept;
  - two priced copies citing the same span are still reduced to the first.
- **Mutation** (`var/p8-14/mutate.py`, extended): the new mutation "dedupe: non-empty spans"
  switches the condition off and fails `test_duplicate_removal_same_rule`. **28 of 28**
  mutations are killed (`var/p8-15/mutate.txt`).

## 3. Re-check (dev; P8-14 figures for comparison)

All three sets are dev now: P8-13's 746 pages (294 scorable), the corpus (863 page texts), and
the P8-14 held-out set (Q1).

**Dev, 746 pages** (`var/p8-15/devrepro.txt`):

| | Narrowed | P8-14 |
|---|---|---|
| Duplicate rows removed | **349** | 567 |
| Gated recall, kept precision, usable, price accuracy | 0.9310, 0.8436, 0.8555, 0.9934 | identical |
| ADD / DROP / RE-NAME / ATTACH (checked against gold) | 926 / 853 / 77 / 29 | identical |
| Gated pages losing a gold item | 10 (27 items) | 10 (27 items) |
| Section exact, all pages (resolve-v3 0.7151) | **0.7212** | 0.7230 |
| Dish-named sections (resolve-v3 734) | 672 | 654 |
| Section pages gaining / losing exact items | 148 / 5 | 155 / 7 |

Every stage bar passes, as in P8-14. The kept unpriced copies cost a little section accuracy,
since some of them still sit under a dish-named model section. That is the intended trade.

**Corpus, 863 page texts** (`var/p8-15/corpusrepro.txt`):

| v3 → v4 | Narrowed | P8-14 |
|---|---|---|
| Items | 61,644 → 61,242 (−402) | → 60,992 (−652) |
| Duplicate removal alone: items | −345 | −596 |
| Sections | 8,472 → 8,345 (−127) | → 8,284 (−188) |
| One-item sections | 1,740 → 1,581 (−159) | → 1,540 (−200) |
| Priced items, prices, distinct price Evidence | +1,248, +1,345, +1,750 | identical |
| Price Evidence lost to duplicate removal | 0 | 0 |
| Ungated page texts whose distinct items differ | **0** | 8 (spelling of a removed copy only) |
| Ungated price Evidence differs; v4 prices off the Version's blocks | 0; 0 | 0; 0 |

- Duplicate removal now takes only priced copies, so priced items and prices are unchanged.
  Ungated invariance is now exact.
- This run's timings are not comparable: three 8-worker jobs shared the CPU. Section 5 has the
  dedicated timing.

**The P8-14 set** (49 pages, 38 scorable, 37 gated; `var/p8-15/heldout-template.txt`,
`heldout-report.txt`, `heldout-losses.txt`):

| | Narrowed | P8-14 |
|---|---|---|
| Duplicate rows removed | 19 | 33 |
| **Gated pages losing a gold item** (at most 3.7 allowed) | **2 (5 items): pass** | 4 (7 items): FAIL |
| §8 item recall | 0.903 (2,144 / 2,373) | 0.903 (2,142 / 2,373) |
| Section exact on gated pages (resolve-v3 0.6906) | 0.6962 | 0.6998 |
| Price accuracy, FR, catch, usable | 0.916, 0.156, 1.000, 0.759 | identical |

- **Both dedupe losses are gone:** `79f66c5309ed` "Paloma" and `ad991b67d739` "Vegetarian
  Antipasto".
- **The two pages still losing** are P8-14's DROP-of-the-title-line cases: Dale's Essenhaus
  `98eb9a11564d` (4 items) and `bb9c743f965e` "Quinoa Bowl".
- Every Q6 stage bar now passes on this set. It is dev now, so this is not a §8 result. The §8
  held-out re-test of resolve-v4 waits for the next crawl (Q1).

**Verification:**
- `make ci` (lockfile, lint, typecheck, tests) with `var/` parked outside the worktree:
  **pass**, with 808 passed and 948 skipped (the database tests: no local test database was
  made).
- **CI on #126:** all five merge checks plus the PR-title check pass. The strict database job
  ran **1,756 passed, 0 skipped**, and `alembic check` reports no new upgrade operations.

## 4. Applied to `helios_laptop` (owner go-ahead, Amendment 29 Q3)

This ran after section 3's checks: no gold loss beyond P8-14's DROP cases, and CI's strict job
green.
- **Backup:** `var/laptop-run/helios_laptop-2026-10-26-pre-p8-15.dump` (36.4 MB, 36 tables).
- **Dry run** (read only, at alembic `13081a087231`):
  - 1,597 pages due, all `reinterpret`;
  - every one with saved answers and a matching bundle;
  - `method_version` with `resolve-v4`, 126 characters.
- **Re-interpretation** (`var/p8-15/reinterp.py run`, this branch's code):
  - `run_extraction` ran with an extractor that refuses any model call;
  - 1,597 of 1,597 pages written, **0 failed, 0 model calls, 0 withdrawals**;
  - wall time 74 min. P8-12 took 31; the prototype runs of section 6 shared the CPU.
- **Gold refresh:** `apps.gold.refresh`, effective `2026-10-26T17:52:23Z`.

| | Before (resolve-v3, P8-12) | After (resolve-v4) |
|---|---|---|
| Run report: items written / prices written | 121,925 / 68,795 | 121,692 / **70,885 (+2,090)** |
| Run report: unsectioned items; empty pages; flagged | 9,379; 29; 350 | 9,360; 29; 350 |
| Run report: [5d] (page records; an organization copy counts again) | — | gated 737; ADD 3,119, DROP 2,390, RE-NAME 206, ATTACH 72; duplicates removed 604 |
| Gold `current_menu` rows | 58,031 | **59,860 (+1,829)** |
| … items / variants | 53,679 / 4,352 | 55,403 / 4,457 |
| … distinct items | 54,729 | 56,821 |
| … sections | 9,426 | 9,375 (−51) |
| … one-item sections | 2,161 | **1,976 (−185)** |
| … subjects | 943 | 943 |
| Price index rows / families | 351 / 947 | 351 / 947 |

- Counts: `var/p8-15/counts-before.json`, `counts-after.json`.
- Logs: `reinterp-run.log`, `gold-refresh.log`.
- **Owner's reported records** (`var/p8-15/cases.txt`): Vivo (20402) and 21479 no longer hold
  any section of two items or fewer. P8-12's list of single-dish "sections" there is gone.
  - Vivo's second printed Chipotle Enchiladas is still missing. That is a validator fix
    (Amendment 30, g1f).
- Writes went to Menu (corrections) and Gold only. Nothing was written to Bronze or identity.

## 5. Pi timing (owner go-ahead, speed only)

`var/p8-15/pi/timing.py` is P8-14's `timing.py` with its data root taken from an environment
variable.
- **The kit:** this branch's code (`git archive HEAD`), the 863 page texts' bundles and saved
  answers, and the corpus list.
- **Where it ran:** `~/p8-15-timing` on the Pi (Orange Pi 5 Plus, now at 192.168.1.191), with a
  frozen `uv sync`. It ran outside the Helios Compose stack.
- **How:** pinned to one A76 core (`taskset -c 4`), sequential, each page best of 3. The core
  stayed at 2.256 GHz and 34–35 °C throughout.
- **Writes:** no database and no model. The kit was deleted afterwards.

| Pi, one core (863 page texts) | Median | p95 | Max | Total |
|---|---|---|---|---|
| resolve-v3 (`rows_of` → judge → [5c]) | 119.3 ms | 562 ms | 3.42 s | 168 s |
| resolve-v4 (`llm_stream`) | 154.4 ms | 812 ms | 4.14 s | 228 s |
| Added by resolve-v4 | 26.2 ms | 280 ms | 1.76 s | 60 s |

- On the 481 [5d]-gated texts, the median added time is 59.5 ms (p95 363 ms).
- The Pi is about 2.1× the laptop (P8-14 laptop: median 57.0 / 72.6 / 11.9 ms).
- A full saved-answer re-interpretation adds about one CPU-minute on the Pi. That is small
  beside a model call per chunk.
- **Host key.** `known_hosts` holds a stale ED25519 entry for 192.168.1.191 (another device had
  that address before). The Pi at .191 serves the key already trusted for its old address .219
  (`SHA256:1vtX3+mBMoepGUofDUiODx4c8HiPK9yARaBCVKMTfNo`). The session connected with
  `HostKeyAlias=192.168.1.219` and left `known_hosts` unchanged.

## 6. Amendment 30 proposed: validator grounding (prototype only)

The full text is in [Amendment 30](../adr/0013-phase5-menu-pipeline.md#amendment-30-2026-10-26-proposed-validator-grounding-to-the-nearest-print-and-glued-names).
Prototype: `var/p8-15/ground.py`.
- It patches the validator where `resolve.judge` calls it. So [5d], the re-judge, [5b] and
  the harness's gold-row FR and corruption catch all see each variant.
- Outputs: `ground-dev*.txt` and `ground-corpus*.txt`.

**Traced cases.** Each one has its own mechanism:

| Case | Cause | Variant that fixes it |
|---|---|---|
| Vivo, second Chipotle Enchiladas | The claim b0287 doesn't print the name; no print at or after the cursor, so the row falls back to the page's first print, b0136 | g1f (and g1, g1u) |
| Vegetarian Antipasto `ad991b67d739` | The claim b0522 lands 2 blocks past the print b0520; the cursor rule sends it to b0922, in a later menu | g1 / g1u only |
| Paloma `79f66c5309ed` | The claim b0041 is right, but the block glues name to description ("PalomaHerredura …") | G3 |
| Dahlia Café `d57b5b288970` (the Q2 gap) | Each price is printed just above its name. The validator and the model both bind the next dish's price; the model also prices section headings ("BURGERS $15.01") | G2 |

**Dev results** (793 pages; Amendment 30 has the table):
- **g1f + G3**, measured together: +51 gold items and 0 lost. FR 0.1008 → 0.0993, catch
  0.9950 → 0.9949, price accuracy and usable prices flat. Recommended.
- **g1 / g1u** re-claim 16,000–18,000 rows for a net −9 to −11 gold items. Not recommended.
- **G2** cuts Dahlia's wrong-price accepts 105 → 4. Dev-wide, price accuracy goes 0.9785 →
  0.9832 and FR 0.1008 → 0.0961.
  - **But it false-gates normal pages on the corpus:** Mom's Special Cooking and Wen's Café,
    2 of 8 gated page texts, both spot-checked. Neither page is labelled.
  - The cause on Wen's: dish headings in a second style become section bounds.
  - Owner fork Q2.

**Side measurement: where every dev gold price goes** (`var/p8-15/gap.py`, `gap.txt`; asked
during the session). Of 24,421 gold prices under resolve-v4:

| Bucket | Share |
|---|---|
| Accepted at the gold price | 81.5 % (resolve-v3: 77.6 %) |
| Item missed | 7.8 % (11.4 %) |
| Wrong amount | 4.1 % (4.0 %) |
| `price_not_grounded` | 3.7 % (3.9 %) |
| Unpriced row | 2.3 % (2.5 %) |
| Other validator reasons | 0.6 % (0.6 %) |

[5d] closes about a third of the missed items (2,792 → 1,903). `html_inline` is the weakest
format: 65 % accepted, with 20 % of items missed.

## 7. Artefacts (untracked, `var/p8-15/` in the worktree)

- **Re-check:** `devrepro.txt` / `.json` (and P8-14's as `devrepro-p8-14.json`),
  `corpusrepro.txt`, `heldout-template.txt`, `heldout-report.txt`, `heldout-losses.txt`,
  `mutate.txt`. The scripts are P8-14's, run from a copy in `var/p8-14/`; `mutate.py` is
  extended there.
- **Laptop:** `reinterp.py`, `counts.py`, `counts-before.json`, `counts-after.json`,
  `reinterp-run.log`, `report_diff.py`, `gold-refresh.log`, `cases.py` / `cases.txt`, `probe.py`.
- **Pi:** `pi/timing.py`, `pi/lib.py`, `timing-pi.txt`.
- **Amendment 30:** `ground.py`, `ground-dev*.txt`, `ground-corpus*.txt`, `peek_g2.py`,
  `gap.py` / `gap.txt`.

## 8. Owner questions

1. **Amendment 30, Q1 to Q3:** build g1f + G3 as validator-v9 (recommended)? Which G2
   section-bound option, if any? Is G1 scoped to g1f?
2. **Held-out re-test:** should the §8 re-test of resolve-v4 (and of validator-v9, if built)
   be scheduled on the next crawl's new page texts? This pool's gated texts are all used.
3. **PR #125:** may it be closed? #126 replaces it. A comment on #125 says so; the session
   did not close it.
4. **The two remaining [5d] DROP losses** (a dish whose only name line reads like a
   description: Dale's Essenhaus, "Quinoa Bowl"). Queue them with the follow-ons, or accept
   them?
5. **`known_hosts`:** replace the stale 192.168.1.191 entry with the Pi's key, or keep using
   the alias? A DHCP reservation would stop the address moving again.
