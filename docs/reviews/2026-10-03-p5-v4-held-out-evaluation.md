# Held-out evaluation of pipeline version v4 (ADR-0013 §8)

Laptop run coordinator session (C), from 2026-10-03: the §8 evaluation that
[Amendment 9](../adr/0013-phase5-menu-pipeline.md#amendment-9-2026-10-03-pipeline-version-v4-tuned-on-the-p5-5-pages)
item 4 requires before v4 runs extraction. The version under evaluation:

```
qwen3-4b-instruct-2507-q4_0@e0ba675d86ab;prompt-v2.3;chunk-v2.1;segment-v2;repairs-v4;validator-v4;classifier-v2
```

**Status: in progress.** Owner decisions recorded; RUN-C-01 issued. No draw, label or
model call yet.

The procedure is the v4 tuning record's
[next held-out evaluation](./2026-10-03-p5-pipeline-v4-tuning.md#next-held-out-evaluation-needed-before-any-extraction-run),
which repeats P5-5's ([record](./2026-09-30-p5-held-out-evaluation.md)). It is measured
only: the pipeline (`apps/menu_pipeline/**`, `packages/helios_parsing/**`) and the
harness rules (Amendment 9 item 1) are frozen at main `d00618c`. A logic change there
would make a new version and void this evaluation. The owner runs every laptop step from
the checklists below; this session never sees page text, labels or venue names. Page
bodies, labels, outputs and worksheets stay in gitignored `var/menu-eval/v4/` on the
laptop. This file keeps counts, rates and hashes. Pages are named by an opaque id
(`sha256(record key)[:12]`).

## Owner decisions (before any sampling)

| | Question | Answer |
|---|---|---|
| V1 | Draw seed | **20261003** (the session date, as P5-5's 20260930). The draw runs once, with no re-draws. The adjudicator's shuffle seed is **20261004** |
| V2 | Scorable pages | **10**, as P5-5: label in draw order until 10 pages print prices |
| V3 | Exclusions for the 18 venues labelled in P5-5 | **Venues plus their hosts, URLs and page text**: the 18 venues; their website and own-site page hosts (platform hosts excepted, as for the spike's hosts); their page URLs; any page whose text hash equals one of their pages'. Amendment 9 item 4 names only "the 18 venues", but chain locations share pages (1,635 menu-URL records on 894 URLs), so a sibling venue could otherwise draw a page that v4 was tuned on |
| V4 | P5-5's laptop scripts (draw, the `due_pages` filter for the held-out Versions, harness copy, disagreement worksheet) | **Reuse**: the owner pastes their source, this session reviews it and writes the adapted versions verbatim into the checklists; each script's sha256 is recorded. No repo code change |
| V5 | Extraction database; Menu-write commit fix | **A disposable `TEMPLATE` clone of `helios_laptop`**, as P5-5, so `helios_laptop` keeps every page due for the first full pass. **Slow commits are tolerated**: scores come from the saved raw answers, which are written before each page's Menu write |

Carried over unchanged:

- From P5-5 (Amendment 8): the sample source is the laptop first pass (`helios_laptop`,
  E1). Pages are static only (E1b). A fresh agent labels them, and the labels are frozen
  and hashed before the first model call (E2). Promo marks and promo entries are labelled
  (E3). Pass or fail is decided on point estimates over the pooled pages, with Wilson
  intervals and usable prices recorded and not gated (E4). `classifier-v2` is unchanged,
  so its S6f evaluation stands, and its precision on the draw is recorded. The real
  extract CLI runs against the pinned `llama-server` image (E5). Disagreements go to a
  blinded adjudicator, and the owner confirms every label change (item 3). The label
  conventions of item 4 apply.
- From P5-7 (Amendment 9 item 1): the harness is frozen with H1a variant-aware matching
  and H1b strict gold-row false reject; the corruption seed is 7.
- Exclusions from P5-5: the spike's venues, its hosts (platforms excepted), and the URLs
  the spike or the S6f render probe fetched. One page per venue, and at most one venue
  per site.

## Procedure (planned)

Each run is an owner-run checklist below. Each checklist is issued after the previous
run's results have been checked.

| Run | What | Gate before the next run |
|---|---|---|
| RUN-C-01 | Preconditions and inventory (read-only): the laptop's due queue at v4, P5-5's files, the source of P5-5's scripts and commands | Due queue as expected; scripts reviewed |
| RUN-C-02 | Draw (seed 20261003, exclusions as V3) and page export; every body re-segments byte-for-byte to its bundle's blocks | Exclusion and order counts add up |
| RUN-C-03 | Blind labels by a fresh local agent (a self-contained prompt in the checklist), in draw order until 10 pages print prices; then frozen and hashed | Freeze time and manifest hash reported **before** RUN-C-04 is issued |
| RUN-C-04 | Extraction of the held-out Versions with the real extract CLI on a `TEMPLATE` clone, then `compare` / `loss` / `corrupt` with the blind labels | Extraction start is after the freeze; extracted pages = held-out pages |
| RUN-C-05 | Disagreement worksheet, the blinded adjudicator (a fresh local agent), the owner's confirmations, the confirmed label set hashed and scored | Both label sets hashed, both scores recorded |

Before anything is recorded, the results are checked against the checklist: the
preconditions match, the label freeze and manifest hash come before the extraction
start, and the counts add up. A gap is asked about, never filled in.

## Owner-run checklist

### RUN-C-01: preconditions and inventory (read-only)

Nothing here writes to a database or draws a page, and no completion is requested from
the model server. Run it in the checkout that holds the laptop pass's `var/replay/`
(its menu-page bundles), with `DATABASE_URL` exported as for the P5-5 draw.

**Stop and report** if `HEAD` isn't the commit named in chat, the code check doesn't
print `code = d00618c`, `git status` lists a tracked change, `uv sync` fails, the
database isn't `helios_laptop`, `llama-model-check` doesn't print `ok`, or `/props`
doesn't show the manifest file with 2 slots. A due queue other than the expected one is
not a stop: report it and go on.

```bash
# 0. Start time, and which checkout holds what (paths not needed: yes/no per line)
date -u +%FT%TZ
git worktree list | wc -l
ls -d var/replay/menu-page var/replay/menu-extract var/menu-eval/p5-5
#    if var/menu-eval/p5-5 is in another worktree, say so and run step 6 there

# 1. The commit: this branch, whose code equals main d00618c (only docs differ)
git fetch origin claude/p5-v4-held-out-eval-9umdsy
git switch --detach FETCH_HEAD
git rev-parse HEAD                                       # = the commit named in chat
git status --porcelain --untracked-files=no              # expect no output
git diff --quiet d00618c HEAD -- . ':(exclude)docs' && echo "code = d00618c"
uv sync --frozen --extra menu                            # expect exit 0

# 2. The database
uv run --frozen python -c "import os; from sqlalchemy.engine import make_url; print(make_url(os.environ['DATABASE_URL']).database)"
#    expect: helios_laptop

# 3. The model server: the file check, then /props (no completion is requested)
C="docker compose -f infra/docker-compose.yml -p helios-v4eval --profile menu"
$C up -d --wait --build llama-server
$C logs --no-log-prefix llama-model-check | tail -1
#    expect: Qwen3-4B-Instruct-2507-Q4_0: ok (...)
$C exec -T llama-server curl -s localhost:8080/props \
  | python3 -c 'import json, sys; p = json.load(sys.stdin); print(p["model_path"], p["total_slots"])'
#    expect: /models/Qwen3-4B-Instruct-2507-Q4_0.gguf 2
$C stop llama-server

# 4. The due queue at v4, and the database size (reads only, then rolls back)
uv run --frozen python - <<'EOF'
import json
from collections import Counter

from sqlalchemy import text

from apps.menu_pipeline.extract import EXTRACTION_MODEL
from apps.menu_pipeline.extraction import PipelineVersion, model_tag
from apps.menu_pipeline.menu_writes import due_pages
from apps.menu_pipeline.models import load_manifest
from packages.helios_core.db.session import get_sessionmaker

V4 = ("qwen3-4b-instruct-2507-q4_0@e0ba675d86ab;prompt-v2.3;chunk-v2.1;"
      "segment-v2;repairs-v4;validator-v4;classifier-v2")
version = PipelineVersion(model=model_tag(load_manifest()[EXTRACTION_MODEL]), classifier="classifier-v2")
assert version.llm == V4, version.llm
with get_sessionmaker()() as session:
    due, skipped = due_pages(session, version.llm)
    size = session.execute(text("SELECT pg_size_pretty(pg_database_size(current_database()))")).scalar()
    session.rollback()
print(json.dumps({"method_version_ok": True, "due": len(due),
                  "by_reason": Counter(page.reason for page in due),
                  "by_scope": Counter(page.subject_kind for page in due),
                  "skipped": skipped, "db_size": size}))
EOF
#    expect: due 1632, by_reason {"new": 1632}, by_scope 1631 organization + 1 establishment,
#    up_to_date 0 (P5-5 extracted on a clone, so helios_laptop has no llm page)

# 5. Saved raw answers. v4 shares the slice-5 extractor key (model, prompt, chunking,
#    segmenter), so P5-5's answers are in this folder; v4 reuses any it finds by text hash.
ls var/replay/menu-extract | wc -l
ls var/replay/menu-extract/f20a8b6e3b49afd1 | wc -l      # expect at least 10 (P5-5)

# 6. P5-5's files: directory names, top-level file names and sizes (no contents)
find var/menu-eval/p5-5 -type d | sort
find var/menu-eval/p5-5 -maxdepth 1 -type f -printf '%f %s\n' | sort
#    Then, for the blind and the confirmed label directories: the JSON file count
#    (expect 18 each) and each set's manifest hash, recomputed the way P5-5 computed it
#    (expect blind 183db924…, confirmed 78766370…). If the hash doesn't reproduce, say
#    how you computed it.

# 7. Script source (code only): every script in the P5-5 folder, with its sha256
for f in $(find var/menu-eval/p5-5 \( -name '*.py' -o -name '*.sh' \) | sort); do
  echo "=== $f $(sha256sum "$f" | cut -c1-64)"; cat "$f"; done
#    Before pasting, check for hard-coded venue names, page URLs, page text or
#    credentials; replace any with <redacted> and say where.
date -u +%FT%TZ
```

Also paste, if you have them:

- **P5-5's exact commands** for the `TEMPLATE` clone, the extraction run (Compose project
  `helios-p55`, how the worker reached the clone's database, how the `due_pages` filter
  was invoked), the copy of the raw answers into the harness layout, and
  `compare` / `loss` / `corrupt`, from shell history or notes. Replace passwords with `***`.
- **The P5-5 labeller's and adjudicator's prompts** (from the P5-5 session). They hold no
  page text. Reusing their wording keeps this set's label grain the same as P5-5's.

```text
RUN-C-01 RESULTS
utc_start:
worktrees:                       (count)
checkout_has:                    menu-page yes/no, menu-extract yes/no, p5-5 yes/no (or: in worktree …)
head:                            (git rev-parse HEAD)
code_check:                      (code = d00618c, or nothing)
tracked_changes:                 (git status output; expect none)
uv_sync:                         ok / error (paste the error)
database:
llama_model_check:               (the last log line)
props:                           (model_path total_slots)
due_report:                      (the JSON line)
menu_extract_folders:
saved_answers_f20a8b6e3b49afd1:
p5_5_dirs:                       (listing)
p5_5_files:                      (listing)
blind_labels:                    files=…  manifest=…  (method)
confirmed_labels:                files=…  manifest=…
scripts:                         (step 7 output, redactions noted)
p5_5_commands:                   (pasted, or "none kept")
p5_5_prompts:                    (pasted, or "none kept")
utc_end:
errors:                          (tracebacks, if any)
```

## Results

Pending: RUN-C-02 to RUN-C-05.
