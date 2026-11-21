# P8-25: chunk-answer reuse (ADR-0013 Amendment 37 stage 1): build and quality gate

Session P8-25, 2026-11-20/21, on the laptop, alongside the P8-23 Pi recrawl run by another
session. The owner accepted Amendment 37 Q1–Q4 as recommended (recorded on #172): build stage 1,
per-chunk records with a one-time backfill, the laptop-GPU gate of Q3 before any Pi run, and a
report count only.

**Result: the Q3 gate fails.** Stage 1 is built and tested but **must not be deployed**. Owner
questions are at the end.

**Nothing live was written.** `helios_laptop` and the Pi are untouched. Pi data was read from
the read-only P8-24 copy in the main checkout's `var/p8-24/pi/` (its `var/replay` and the
P8-23 version list `pairs.csv`). Tests ran on the scratch database `helios_p825_test`. The
backfill was timed on a scratch copy of the Pi's saved answers, with its bundles symlinked
read-only. Artefacts are untracked, in the main checkout's `var/p8-25/`.

## 1. What was built (branch `p8-25-chunk-reuse`)

- **Key** (`apps/menu_pipeline/chunk_answers.py`): (extractor version, sha256 of the chunk-v2.3
  chunk with its block ids replaced by chunk-local `k0`, `k1`, … in order of first appearance).
- **Id map:** on a hit, the saved answer's `"b"` ids are mapped back through the two chunks' id
  lists. An answer that cites an id outside its own chunk is not reused; that chunk goes to the
  model.
- **Run** (`extraction.py`): a page with no saved page answer looks each chunk up before
  sending it. Only misses go to `llama-server`, and the assembled answers are validated as today.
- **Records:** a reused chunk is recorded in the page record as `{"raw", "reused": <key>}`, with
  no timings. Each chunk the model answers gets its own record in
  `var/replay/menu-extract/<extractor>/chunks/<key>.json.gz`, holding its ids and source page.
- **Report:** `reused_chunks`. No method-version change.
- **Backfill** (`python -m apps.menu_pipeline.backfill_chunks --base-dir .`): chunk records
  from the existing page records and their bundles. No database, no model; it never rewrites
  a file.

On the Pi's saved answers (P8-24 copy), the backfill read 2,980 bundles and 2,128 page records
(0 without a bundle) and wrote 13,776 chunk records in 37 s on the laptop: 56 MB on disk,
mostly 4 KiB block overhead.

## 2. The gate (owner Q3)

**Frame.** P8-24's page set: the P8-23 recrawl's batches 1–6.
- The chunk store is rebuilt as production would see it after the backfill: every page record
  saved before the run, then each model page's own chunks after it (first written wins).
- **112 model pages, 918 chunks**: the same counts as P8-24.
- **352 chunks would be reused, on 59 pages: 0.383 of the chunks, 0.405 of the Pi's model
  time** (P8-24: 0.410).
  - 209 of them have identical ids, an exact match: 0.224 of the model time.
  - 143 match only after renumbering: 0.178.
  - None is unmappable. All 352 hits come from answers saved before the run.

**Arms**, per reusable chunk. The page's other chunks keep the Pi's actual answers in every arm.

| Arm | Answer |
|---|---|
| S | the saved answer with its ids mapped: what stage 1 uses |
| F1, F2 | the new chunk extracted fresh on the laptop GPU, in two full passes |
| G | control: the saved chunk (old ids) extracted fresh on the GPU, ids mapped |
| P | the Pi's own answer to the new chunk, from the run's page record |

**GPU runtime:** the pinned `server-cuda` image of the earlier laptop passes, Qwen3-4B Q4_0,
2 slots, ctx 12288, `LlamaClient.extract_chunk` (sparse retry included). Each pass took about
15 min.

**Compare:** each page's accepted rows (`llm_stream` verdicts `accept`: normalized item,
variant, amount). Multiset symmetric difference between two arms, page by page, summed over the
59 pages.

| Pair | Rows differing | Of rows compared | Share | Pages differing | Chunks word-for-word equal |
|---|---|---|---|---|---|
| **S–F1 (reused vs fresh)** | **271** | 6,363 | **0.043** | 24 | 175 / 352 |
| **S–F2** | **269** | 6,347 | **0.042** | 24 | 169 |
| **F1–F2 (fresh vs fresh)** | **76** | 6,384 | **0.012** | 15 | 253 |
| G–F1 (renumbering only, same GPU) | 233 | 6,341 | 0.037 | 23 | 187 |
| G–F2 | 243 | 6,325 | 0.038 | 22 | 201 |
| S–P | 260 | 6,328 | 0.041 | 26 | 168 |
| P–F1 (Pi fresh vs GPU fresh) | 185 | 6,365 | 0.029 | 24 | 216 |

Accepted rows per arm: F1 3,200, F2 3,184, S 3,163, P 3,165, G 3,141. Reuse loses about 1% of
the rows; most of the difference is churn in both directions.

**Gate (reused vs fresh ≤ fresh vs fresh): 270 > 76, FAIL.**

### Split by match kind (`split.py`)

Derived arms are compared with F1. The other reusable chunks take F2, so the F2–F1 noise on them
is counted in.

| Arm | Reused chunks | Rows differing from F1 | Pages differing |
|---|---|---|---|
| F2 (floor) | none | 76 | 15 |
| E: exact-id chunks reused, renumbered ones fresh | 209 | 118 | 21 |
| R: renumbered chunks reused, exact-id ones fresh | 143 | 229 | 18 |

### Reading

1. **The ids matter.** On the same GPU in the same session, the saved chunk with its old ids
   (G) differs from the new chunk (F) about 3× more than F differs from itself. The model reads
   block ids as tokens, and a different id sequence changes its answer beyond run-to-run noise.
   Rows moved per reused chunk, against F1 and with the floor's noise included: renumbered
   (R) 229 / 143 ≈ 1.6, exact-id (E) 118 / 209 ≈ 0.56.
2. **The same-session floor is stricter than any saved answer can meet.** Exact-id reuse (E)
   gives the model identical input. Its excess over F1–F2 (118 vs 76) comes only from the saved
   answer being from another run (saved before P8-23, mostly by the laptop passes). Today's
   page-level reuse has the same property, so it would not pass this floor either.
3. For scale, the Pi against the laptop GPU on the same chunks (P–F1) differs by 185 rows. That
   is the machine-to-machine variation production already accepts. Renumbered reuse alone (R,
   229) still exceeds it.

## 3. Deployment notes (Pi worker, next swap): **on hold**

These notes apply only if the owner rules for deployment. Nothing here was done.
1. Merge first, then at a swap (the loop is stopped by its `STOP`/watcher, between batches):
   - update the Pi backend checkout to the merge commit;
   - rebuild the worker image: `docker compose --profile menu build worker`, about 90 s cached.
2. **Backfill once**, in a worker container as uid 999, since the saved answers are 0600 uid
   999. Run `python -m apps.menu_pipeline.backfill_chunks --base-dir <deploy dir>`, with no
   `with_db.py` (it needs no database).
   - Expect about 2,128 page records plus those the recrawl has added since (batches 7–26),
     and roughly 14,000 to 20,000 chunk records.
   - About 1 min on the laptop for the P8-24 copy, so a few minutes on the Pi.
   - A second run writes nothing.
3. Resume `var/p823/run-loop.sh pi`. Each batch's `extraction run complete` line now carries
   `reused_chunks`; `chunks` (model calls) should fall by about 40% of the time on changed
   pages. Watch the first batch's `rows` counts against earlier batches.
4. **Rollback:** the previous worker image. Chunk records are additive files in a `chunks/`
   subfolder, which the old code never reads (it reads only `<text hash>.json.gz`). Page
   records written with `"reused"` entries stay valid for the old code, which reads only
   `raw`. No database change.
5. Gold changes only through the next swap, as today.

## Owner questions

- **Q1. Renumbered reuse** fails the gate, and the control attributes the excess to the ids.
  - Recommended: **do not ship it**.
  - Alternative: accept the about 1% row loss and 4% churn for 0.178 of model time.
- **Q2. Exact-id chunk reuse** (0.224 of model time) gives the model identical input. It exceeds
  the same-session floor only as much as any saved answer does, which page-level reuse already
  accepts.
  - Recommended: **ship stage 1 restricted to exact ids**, keyed by the chunk text as sent.
    That's a small change to this branch (same records, key without renumbering), with the gate
    re-run on the exact-id chunks.
  - Its bar would be "no worse than page-level reuse": E vs the run-to-run difference of
    whole-page saved answers. That needs one more GPU measurement.
  - Alternative: drop stage 1 entirely.
- **Q3. Gate wording for any future reuse.** Keep "≤ fresh vs fresh in one session" (strict:
  nothing saved passes it)? Or compare against "saved answer vs fresh for identical input"
  (E-type), which is the noise production already lives with?
