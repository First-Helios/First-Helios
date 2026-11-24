# ADR-0030: Repeatable pipeline-host runs: one master database, a batch loop and a gated swap

**Status:** Accepted 2026-11-24 under the owner's delegation (session P8-28; owner: "I defer to
your answers"). Proposed 2026-11-22 (session P8-26). Q1–Q8 all take the recommendation; see
[Decisions](#decisions-2026-11-24). Stage 1 (the tooling) is built in a separate PR.
[Amendment 1](#amendment-1-2026-11-24-phase-6-monthly-runs) (Phase 6 monthly runs: the timer, the
stop at the gate, the run report and the spot check) accepted 2026-11-24 under the owner's
delegation (session P8-29).
**Date:** 2026-11-22

## Context

Session P8-23 (2026-11-19 to 2026-11-23 UTC) recrawled the 1,746 due menu-page URLs and swapped
the result into the public database (`helios` on the Orange Pi, serving `firsthelios.com`). The
run is recorded in [2026-11-19-p8-23-pi-long-run.md](../reviews/2026-11-19-p8-23-pi-long-run.md).
It worked, but it ran on 26 hand-written files in `var/` (copy on the laptop:
`var/laptop-run/p823-scripts/`). That folder is not in git, and each new situation got a new copy
of a script:

| Need | Files as run |
|---|---|
| Batch loop | `run-loop.sh` (Pi, mode `pi`/`laptop`), `p823-laptop-loop.sh` (laptop GPU), `pi-phase.sh` + `nomodel.py` (fetch only, then re-interpretation without the model) |
| Point a CLI at the work database | `with_db.py` (swaps the database name in `DATABASE_URL`) |
| Wrap-up before a swap | `wrap-work.sh` (Pi), `p823-wrap-laptop.sh` (laptop, adds `place_sweep`) |
| Swap gate data | `compare.py`, `pricecheck.py`, `textdiff.py`, `chunkdiff.py` |
| Backups, deploy, restore | `pi-backup.sh`, `pi-code.sh`, `restore-public.sh`, `make-work.sh`, `pi-swap.sh`, `pi-swap2.sh`, `pi-swap3.sh` (these three differ only in file names), `pi-swap4.sh`, `pi-back.sh` |
| Checks and sampling | `test20.py` + `test20-run.sh` (Pi vs laptop quality), `chromium-check.sh`, `sampler.sh`, `summarize.py`, `pdf_venues.py` (scoped discovery) |

What happened, in order:

| When (UTC) | Step | Figures |
|---|---|---|
| 11-19 | `helios_work` restored on the Pi from the laptop's dump; 20-page check | 6.1 pages/h, Pi 944 vs laptop 961 accepted prices (0.982) |
| 11-19 | Batch 1's extraction refused every page: the admission fence | fence 915,058 (laptop) vs Pi cluster at transaction 27,739 |
| 11-19 | **Swap 1** after batch 2 (100 URLs) | Gold 100,009 → 99,553 (−0.46%), downtime 399 s |
| 11-21 | **Swap 2** after batch 16 (800 URLs); the planned stop after batch 10 was missed | 99,553 → 98,961 (−0.59%), 409 s |
| 11-22 | **Swap 3** after batch 26 (1,300 URLs) | 98,961 → 98,699 (−0.26%), 416 s |
| 11-23 | Pi loop stopped mid-batch 29 (01:05). Master moved Pi → laptop (GPU), then back to the Pi (01:56) when the owner needed the GPU | under an hour on the laptop, 1 GPU batch (68 pages extracted, restarted once for the thermal cutoff), 2 restores, 2 replay syncs (23,640 files the second time) |
| 11-23 | Pi deployed to `main` 5b8f62a; `pi-phase.sh`: fetch-only batches, then no-model extraction; model pages wait for the GPU | running at the time of writing (batch 030, P8-23 owns it) |
| 11-23 | **Swap 4** at the recrawl's end; model pages ran on the laptop GPU over the LAN (D2 (b)) | 98,699 → 98,499 (−0.20%), venues 1,178 → 1,221, 458 s; GPU 180.5 pages/h |
| 11-24 | **Swap 5**: #175/#176 applied (Gold refresh only) | 98,499 → 99,408, venues 1,221 → 1,233 (0 lost), 456 s |

What it cost in time, and the lessons:

1. **The admission fence.** `pg_restore` carries over `menu.admission_fence`. A dump from the laptop
   restored on the Pi held a transaction id about 890,000 ahead of the Pi's counter, so
   `menu.lock_admission()` refused every Menu write. P8-23 fixed it with
   `setval('menu.admission_fence', txid_current())`. The owner ruled (2026-11-20, answer 2) that
   this stays a documented restore step, with no migration.
2. **A laptop-side ssh wait hung on the Pi's Wi-Fi** (no keepalive), so `STOP` was not placed
   after batch 10. The loop ran six more batches (300 URLs) before the swap. A watcher on the Pi
   placed the next stop correctly.
3. **Replay files are mode 0600, owned by uid 999.** The worker writes bundles and saved answers
   through `tempfile.mkstemp` in `apps/menu_pipeline/bundle.py:95` and
   `apps/menu_pipeline/extraction.py:287`, without the `chmod(0o644)` that
   `apps/menu_pipeline/models.py:119` already does. The host user cannot read them, so every sync
   needed a chmod from inside a worker container first.
4. **Host gotchas:** the Pi's login shell is `fish` (an ssh one-liner with `$(...)` fails; scripts
   run through `bash`). Its clock is Asia/Shanghai (+08:00), so `ls` and systemd show local
   times. `pkill -f <pattern>` over ssh kills the ssh session when the pattern appears in the
   ssh command line.
5. **Laptop GPU thermal band.** At the old 85 °C pause / 78 °C resume band the GPU paused 12 times
   in 13 minutes (01:24–01:38 UTC on 11-23). The owner raised the cutoff to 91 °C.
6. **A no-model phase needed a monkeypatch.** `nomodel.py` replaces the extractor with one that
   refuses calls, and lifts `MAX_CONSECUTIVE_FAILURES` (3, `apps/menu_pipeline/extraction.py:111`).

Phase 6 (ROADMAP) asks for scheduled, change-only runs on the Pi with a run report.
ADR-0009 §3 and ADR-0013 §3 put the pipeline on the Pi as a low-priority batch job, and ADR-0019
Amendment 1 records that the Pi now hosts both the public site and the pipeline. None of them
says how a run moves data into the public database. This ADR proposes that procedure. It does not
change pipeline stages, the schema, the fence function or the hosting decision (ADR-0019 Q4).

## Decision

Pipeline runs follow one procedure:

- **One master database at a time.** The pipeline writes only to the master. The public database
  is replaced from the master by a gated swap.
- **One batch loop.** It has two host modes (`pi`, `laptop`) and phases: full, fetch only, extract,
  and extract without the model. It stops itself at the swap cadence.
- **The swap gate P8-23 used, written down.** Rows drop under 5%, every lost venue is explained,
  backups come first, and the checks run after the restore.

Where the tooling lives is an owner decision (D4, Q1). The recommendation is a hybrid: tested
database-facing code in `apps/`, and host orchestration in `infra/pipeline-host/`.

### D1. One master database at a time

**Roles.**

| Database | Role |
|---|---|
| The **master** (`helios_work` on the Pi, or `helios_laptop` on the laptop) | The only database the pipeline writes (fetch, extract, sweeps, rescore, Gold) |
| Public `helios` on the Pi | Read by the API. Written only by a swap, which restores a master dump |
| `helios_laptop` while the master is on the Pi | A mirror of public, restored after each swap. It is the only copy of the data off the Pi (no off-box backup yet, Phase 8). Not written by the pipeline |

**Rule.** Exactly one database is the master. A host that does not hold the master runs no
pipeline writes. A marker file `var/pipeline-host/MASTER` on each host names the master host, the
time it moved, and the sha256 of the dump it came from. The loop refuses to start unless the
marker names its own host. P8-23 kept this rule by hand. The marker makes the rule mechanical.

**Same code on both sides.** A run uses one commit on every host that touches the master: the
Pi's `DEPLOYED_COMMIT` and the laptop's `git archive` of that commit (`code-5b8f62a` in P8-23). The
loop logs the commit. A handover with different commits re-interprets pages under different
pipeline versions, so it is refused.

**Moving the master** (the handover; P8-23 did it three times):

1. **Stop the loop on the source.** Between batches, wait for `loop end`. A stop mid-batch is
   safe: both CLIs commit per URL or page, and the next run takes the rest. P8-23 stopped
   mid-batch twice.
2. **Dump the source master:** `pg_dump -Fc`, then record the sha256. Dumps were 108–128 MB.
3. **Back up the target's database** if it holds anything the dump doesn't. As a mirror it
   normally doesn't, but P8-23 backed it up every time and this keeps that.
4. **Restore into the target:** drop, create, then `pg_restore --no-owner --role=helios` with
   stderr captured (0 lines every time in P8-23). It took 374–416 s on the Pi and 59 s on the
   laptop.
5. **Reset the fence after every restore**, whichever way the master moves:
   `select setval('menu.admission_fence', txid_current(), true);`. It is harmless onto an older
   cluster and required onto a younger one. One rule avoids having to decide which case applies.
   `pi-swap4.sh` already does it on both of the Pi's databases.
6. **Sync `var/replay/` from source to target.** It holds bundles, saved page answers and
   exact-chunk records (ADR-0013 Amendment 37); 459 MB on the Pi at the time of writing. It
   must be complete before the target extracts, or pages whose saved answers are missing go to
   the model again.
   - Out of the Pi: until the 0600 fix (Q6) is in, chmod in a worker container first.
   - Into the Pi: new directories must be writable by uid 999. Use
     `rsync --chmod=Da+rwx,Fa+r`, or chmod afterwards, as `var/site-cache` already is.
7. **Move the marker,** then start the loop on the target.

**Not proposed:** two masters with a merge. Bronze, Menu and Gold ids are serial, so two
diverging databases have no merge path. Streaming or physical replication is also out: the hosts
differ in architecture (arm64 and amd64), and a 120 MB dump is cheap.

### D2. The batch loop

One loop replaces `run-loop.sh`, `p823-laptop-loop.sh` and `pi-phase.sh`.

**Per batch:**

1. Fetch: `apps.menu_pipeline.run --limit 50 --render` under `xvfb-run`. It fetches the URLs past
   the refetch window and renders JavaScript-only pages.
2. Extract every due page: `apps.menu_pipeline.extract`. Saved page answers and exact chunk
   answers are reused, and changed text goes to the model.
3. Write one progress line, as `summarize.py` does: outcomes, Versions, extracted, reused, model
   pages, chunks, prices, pages/h, temperatures.

**Options:**

| Option | Values |
|---|---|
| `--host` | `pi`: CLIs run in the Compose `worker` with `docker-compose.pi.yml`. `laptop`: `uv run --extra menu` from a `git archive` of the run's commit, GPU `llama-server` |
| `--phase` | `full` (fetch + extract), `fetch` (fetch only, as `pi-phase.sh`), `extract` (extract only), `extract-no-model` (re-interpretation only, as `nomodel.py`) |
| `--batch N` | default 50 |
| `--stop-every N` | default 10: stop after every 10th batch and log "swap due" |

**The loop ends when:**

- the `STOP` file exists (checked between batches);
- `--stop-every` is reached;
- a CLI exits non-zero; or
- a fetch finds nothing due.

**The stop happens on the host.** The loop stops itself at the cadence, so no second process
places `STOP`, and nothing waits from the laptop. That removes the swap 2 failure. Anyone watching
from the laptop polls with short calls, each one closing again:
`timeout 60 ssh -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=4 …`.
Nobody holds a long-lived ssh wait.

**Process supervision.** P8-23 started loops with `setsid nohup … &`. Whether the loop runs under
a systemd unit instead is Q2.

**Per-batch cost** (P8-23, Pi, batches 2–28 from its `progress.log`; batch 1's extraction died
on the fence after 6 s):

| | Low | Median | High |
|---|---|---|---|
| Fetch (50 URLs) | 93 s (batch 5) | | 1,074 s (batch 2) |
| Extraction | 1.0 h (batch 14, 9 model pages) | 2.7 h | 6.6 h (batch 2, 54 model pages) |
| Pages/h, reuse included | 5.0 (batch 23) | | 42.4 (batch 4) |

In total, 950 pages were extracted in 75.9 h, 484 of them by the model. That is about 6.4 model
pages per extraction hour, in line with the 20-page check's 6.1 pages/h.

**Thermal modes** (owner rules: `feedback` 2026-11-19 and 2026-11-23):

- **`pi`: no pause.** Temperatures are only logged (the sampler every 15 s, the SoC peak per
  batch). The SoC peaked at 85.8–86.8 °C with frequency cap 1.0 (no throttling reported).
- **`laptop`: measured on the GPU.**
  - Between batches: wait while the GPU is above 91 °C, until it is below 81 °C.
  - Mid-batch: `docker pause` the llama container above 91 °C and unpause it below 84 °C. Requests
    wait, within the client's 1,800 s timeout.
  - The CPU (94–97 °C under ordinary load) is logged only.
  - `run-loop.sh`'s old `laptop` mode, which watched the SoC at 85/78/75 °C, is dropped.

**What runs on which processor:**

| Work | Where | Why |
|---|---|---|
| Fetch and render | Pi | residential IP, Chromium works on arm64, cheap |
| Re-interpretation from saved answers (`extract-no-model`) | Pi | needs no model; P8-23 runs it now |
| Model pages | the laptop GPU when the owner frees it, otherwise the Pi CPU | Pi CPU about 6.4 model pages/h. The GPU is faster, but P8-23 recorded no clean GPU rate (its one GPU batch was restarted mid-batch) |
| Sweeps, rescore, Gold refresh, compare, swap | Pi | Gold refresh 73–74 min on the Pi |

**Two ways to put model pages on the GPU:**

- **(a) Move the master to the laptop.** This is what P8-23 did. It costs two handovers (dump,
  restore, fence, replay sync, both ways). Fetching stops on the Pi meanwhile.
- **(b) Keep the master on the Pi and point the Pi's extract at the laptop's `llama-server`**
  (`--server http://<laptop>:8083`). ADR-0013 §3 already says the model call is an HTTP endpoint
  that can move hosts without code changes.
  - Only chunk text crosses the network, so Wi-Fi is enough. The data and replay stay in one
    place.
  - When the owner takes the GPU back, the container stops. Three consecutive chunk failures end
    the extract, the loop stops on the non-zero exit, and the pages stay due.
  - It needs the laptop's `llama-server` reachable on the LAN (today it binds `127.0.0.1`): Q3.

**`extract --no-model`.** This replaces `nomodel.py`'s monkeypatch with a CLI flag on
`apps.menu_pipeline.extract`. It refuses model calls, a page that needs the model stays due, and
the consecutive-failure stop does not apply. The report counts refused chunks. It is a small code
change, built only after acceptance.

### D3. The swap gate, its cadence and the backups

**Sequence on the master's host:**

1. Sweeps: `place_sweep`, when the run's code has new withdrawal rules.
2. `apps.menu_pipeline.rescore`.
3. `apps.gold.refresh`.
4. The comparison with public: today `compare.py`.
5. The gate.
6. Backups.
7. The restore into public.
8. The checks.
9. The laptop mirror restore and the replay sync to the laptop.

**The gate as P8-23 applied it** (decided under the owner's delegation; the owner kept it for the
~10-batch cadence on 2026-11-20):

1. `gold.current_menu` rows fall less than 5% against public.
2. Every venue that loses its menu (no longer `_has_menu`, the API's own test) is explained by
   `compare.py`, plus a page check where `compare.py` is not enough. `compare.py` gives the
   record's latest capture outcome, its Version count from public to work, and its newest llm
   Menu page. The page check asks whether the refetched page still prints prices
   (`pricecheck.py`).
3. After the restore: `pg_restore` with no stderr, the expected `alembic_version`, migrate exit 0,
   every local endpoint and `firsthelios.com` 200, and `alembic check` clean. If a check fails,
   restore the pre-swap backup.

| | Swap 1 | Swap 2 | Swap 3 |
|---|---|---|---|
| After batch | 2 | 16 | 26 |
| `current_menu` rows | 100,009 → 99,553 (−0.46%) | 99,553 → 98,961 (−0.59%) | 98,961 → 98,699 (−0.26%) |
| Venues with a menu | 1,214 → 1,216 (3 gained, 1 lost) | 1,216 → 1,183 (1 gained, 34 lost) | 1,183 → 1,178 (5 lost) |
| Citywide median | 1031 → 1050 | 1050 → 1049 | 1049 → 1050 |
| API downtime | 399 s | 409 s | 416 s |

Every lost venue fell into one of four kinds:

| Kind | Venues |
|---|---|
| **R4 withdrawal after a refetch** (`not_menu` or `js_only`) | Chick-fil-A Uber Eats, Rudy's (8), Sazan Ramen |
| **Site state changed** | Another Broken Egg (3): prices appear only once a location is chosen |
| **Site rebuilt** | Lutie's, Bottega |
| **Pages with one or two prices, re-extracted to no priced row** | Chili's (23 on one URL), Maggiano's, Vitality Bowls |

**Gaps in the gate as written:**

- Nothing bounds lost venues. Swap 2 lost 34, 2.8% of 1,216, all explained.
- The median is not looked at (+1.8% at swap 1).
- "Explained" is a judgment each time. Q4 proposes a venue bar and a classification computed in
  the comparison.

**Cadence:** about every 10 batches (owner 2026-11-20), and at the end of a run. At P8-23's
median of 2.7 h of extraction per batch, that is about 1–3 days on the Pi. With `--stop-every 10` the loop stops itself there.

**Swap mechanism.** Today: stop the API, drop `helios`, create it, `pg_restore`, start the API, for
about 400 s of downtime. The alternative is Q5:

1. Restore into `helios_next` while the API keeps serving.
2. Stop the API.
3. `ALTER DATABASE helios RENAME TO helios_prev` and `ALTER DATABASE helios_next RENAME TO helios`.
4. Start the API.

Downtime becomes the API restart, and rollback is the reverse rename. It costs one extra copy of
the database on disk.

**Backups** (as P8-23 did, under `~/helios-backups/<run>/` on the Pi, sha256 recorded):

- before each swap, a dump of public (`pi-helios-pre-swapN.dump`) and the master dump that was
  restored (`helios_work-swapN.dump`);
- before any code deploy, a tarball of the deploy directory (without `var/` and `.env`);
- on the laptop, a dump of `helios_laptop` before each mirror restore.

Sizes: dumps 108–128 MB. P8-23's directory holds 1.2 GB (11 dumps, 4 code tarballs), all Pi
backups 2.5 GB, and the Pi's disk is at 101 of 226 GB. Retention is Q7.

### D4. Where the tooling lives (options; the owner decides)

| Option | Pros | Cons |
|---|---|---|
| **A. Repo CLIs under `apps/`** (e.g. `apps/menu_pipeline/run_loop.py`, `swap_report.py`) | Tested and type-checked in CI. Versioned with the code it drives, so a schema change that breaks `compare.py`'s SQL fails a test, not a swap | Host actions (`docker compose`, `pg_dump`, sysfs temperatures, `nvidia-smi`, rsync) don't belong in the app's import graph. CI can't exercise them. More Python to review |
| **B. Scripts under `infra/pipeline-host/`** | Matches what ran. Ops-shaped. Lives beside the Compose files it calls | `infra/` is stop-and-ask (CLAUDE.md). Shell is untested in CI (no shellcheck hook today). `compare.py`'s SQL would sit outside test coverage |
| **C. Documented commands only** (a runbook; scripts stay in `var/`) | No code to review or maintain | The drift P8-23 already shows: three swap copies that differ only in file names, two loop variants, a monkeypatch. Each run re-derives the procedure |
| **Hybrid (recommended)** | Database-facing logic is tested where the schema is. Host glue is short and readable | Two places to look. Needs the `infra/` go-ahead |

**Hybrid, concretely:**

- **In `apps/`, tested:**
  - `apps/menu_pipeline/swap_report.py`: `compare.py`, plus the lost-venue kind and the gate
    verdict as JSON.
  - `extract --no-model` (D2).
  - The 0600 fix (Q6).
  - A `with_db`-style runner, so the worker image can target a named database without putting
    the password on a command line.
- **In `infra/pipeline-host/`, about four scripts:**
  - `loop.sh`
  - `swap.sh`, one parameterised script replacing the four copies
  - `move-master.sh`
  - `sampler.sh`
- **A runbook:** `docs/runbooks/pipeline-host.md`, with the steps above, the host gotchas, and
  the commands to resume.

**Scheduling** (a systemd timer on the Pi, or manual starts) is Q2.

### Not in this ADR

- Hosting or prod (ADR-0019 Q4).
- Off-box backups and restore drills (Phase 8).
- A queue service (stop-and-ask).
- Scheduling monthly discovery (ADR-0009 §3).
- Any change to `menu.lock_admission()` or the fence (owner: no migration).
- A swap with no human or agent reading the gate report.

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| The pipeline writes public `helios` directly | No swap, no downtime | A half-run is public. No gate. A bad batch can't be rolled back short of a restore |
| Two masters (Pi and laptop) merged later | Both hosts work at once | Serial ids diverge, and there is no merge path for Bronze, Menu or Gold |
| Physical or logical replication instead of dump/restore | Continuous copy | PostgreSQL documents physical replication only between servers of the same hardware architecture (Pi arm64, laptop amd64). Logical replication of this schema is far more machinery than a 120 MB dump |
| Move the master for GPU work (what P8-23 did) | No LAN exposure | Two handovers per GPU session, and the Pi idles meanwhile (D2 (b) is the alternative, Q3) |
| Keep hand-written scripts per run | Fastest the first time | 26 files, 4 swap copies, and lessons that live only in run records and memory |

## Consequences

- **Easier:**
  - A run resumes from a documented state.
  - The swap gate is the same every time, and its data is tested code.
  - The swap 2 miss (a stop that depended on a laptop ssh session) cannot recur.
  - A master move is one script with the fence and the permissions handled.
- **Harder:**
  - More code to keep in step with the schema (that is the point of putting `swap_report` under
    test).
  - `infra/` gains run scripts that the owner reviews.
  - The marker file is one more piece of state that can be wrong. If it is, the loop refuses to
    start. It never writes to a second master.
- **Unchanged:**
  - Pipeline versions and stages (ADR-0013).
  - The data model.
  - What the API serves between swaps.

## References

- [P8-23 run record](../reviews/2026-11-19-p8-23-pi-long-run.md) (swaps 1–3, the fence, the change
  rate, the thermal rules). Swap 4 and the GPU/no-model phase are recorded there by P8-23.
- [ADR-0013](./0013-phase5-menu-pipeline.md) §3 (Pi runtime) and Amendments 36–37 (validator-v12,
  exact chunk reuse).
- [ADR-0019 Amendment 1](./0019-public-v1-site.md) (the Pi hosts the site and the pipeline).
- [ADR-0009](./0009-venue-discovery-source-dedupe-and-schedule.md) §3 (monthly cadence on the Pi).
- README "Staging (Pi)".
- Scripts as run: `var/laptop-run/p823-scripts/` (laptop) and `~/First-Helios/var/p823/` (Pi).
  Neither is in git.

## Owner questions

Each has a recommendation. Nothing is built until these are answered.

1. **Where the tooling lives (D4).**
   - Hybrid (*recommended*): database-facing pieces in `apps/` under test, host glue in
     `infra/pipeline-host/`, and a runbook.
   - The alternatives are A (all in `apps/`), B (all in `infra/`) and C (runbook only).
   - `infra/` is stop-and-ask, so this needs your go-ahead either way.
2. **Scheduling.**
   - *Recommended:* manual starts for now. Each run still needs your go-ahead for data writes,
     and the gate needs a reader. Run the loop under a systemd unit instead of `setsid nohup`, so
     it survives logouts and logs to the journal.
   - Add a timer only when Phase 6's monthly cadence starts. Its `OnCalendar` should name UTC
     explicitly, because the Pi's clock is Asia/Shanghai.
3. **Model pages on the GPU (D2).**
   - (b) *Recommended:* keep the master on the Pi and point its extract at the laptop's
     `llama-server` over the LAN. Bind it to the laptop's LAN address with `--api-key`, only while
     a run uses it.
   - (a) Move the master as P8-23 did. Keep it for when the Pi is down.
4. **Swap gate additions (D3).**
   - *Recommended:*
     - add a second bar: venues with a menu fall less than 5%, with a stop-and-ask above it;
     - have `swap_report` classify each lost venue into the four kinds seen;
     - make a page check mandatory only for an unclassified venue;
     - report the median shift without a bar.
   - The alternative is to keep the gate exactly as written.
5. **Swap mechanism (D3).**
   - *Recommended:* restore into `helios_next`, then rename. Downtime is an API restart instead
     of about 400 s, and rollback is the reverse rename.
   - The alternative is to keep drop-and-restore.
6. **The 0600 replay files.**
   - *Recommended:* `chmod(0o644)` before the rename in `bundle.py` and `extraction.py`, as
     `models.py` already does. That is a small code PR with no `infra/` change.
   - The alternatives are a umask in the Dockerfile (`infra/`) or keeping the chmod step in the
     handover.
7. **Backup retention on the Pi.**
   - *Recommended:* per run, keep everything until the run record merges. After that keep the
     pre-run public dump, the last pre-swap dump and the last swapped master dump, and delete the
     rest (P8-23 would keep 3 of its 11 dumps).
   - The alternative is to keep everything.
8. **The laptop mirror.**
   - *Recommended:* keep restoring `helios_laptop` after every swap. It is the only copy of the
     data off the Pi until Phase 8's off-box backups, and it keeps dev equal to public.
   - The alternative is to restore it only on demand.

## Decisions (2026-11-24)

Decided under the owner's delegation (owner, 2026-11-24: "I defer to your answers"). Each question
takes its recommendation.

1. **Tooling: hybrid.** Database-facing code in `apps/` under test; host glue in
   `infra/pipeline-host/`. The batch loop itself is an `apps/` CLI (it calls only the pipeline
   CLIs, the thermal sensors and `docker`), so its stop rules are tested.
2. **Scheduling: manual starts under a systemd unit** (not `setsid nohup`). A timer only when
   Phase 6's monthly cadence starts, with `OnCalendar` in UTC.
3. **Model pages: the Pi stays master** and its extract calls the laptop's `llama-server` over the
   LAN. P8-23 already ran this way for swap 4: 265 pages at 180.5 pages/h, 0 failed. Moving the
   master (a) stays for when the Pi is down.
4. **Swap gate additions:** venues with a menu must fall less than 5% (stop-and-ask above it), and
   the gate report classifies each lost venue automatically into the kinds seen in swaps 1–4:
   - **R4 withdrawal** (the record's newest capture is `not_menu`, `js_only` or a withdrawal rule);
   - **site change** (a newer capture with changed text and no priced Menu page since);
   - **JSON-LD precedence** (a newer jsonld page that hides the llm page; #176 fixed the bug, the
     kind stays so a regression shows);
   - **Unsectioned** (the newest llm page prices only Unsectioned items, which never reach Gold:
     #177 Q1 keeps that rule);
   - **re-extraction to zero** (the newest llm page of an unchanged record has no priced row).

   A venue that fits none is **unclassified** and blocks the gate until a page check explains it.
   The median shift is reported without a bar.
5. **Swap mechanism: restore into `helios_next`, then rename** (`helios` → `helios_prev`,
   `helios_next` → `helios`). Rollback is the reverse rename.
6. **0600 replay files: done** in #175 (`chmod(0o644)` before the rename).
7. **Retention: 3 dumps per run** once the run record merges: the pre-run public dump, the last
   pre-swap dump and the last swapped master dump.
8. **Laptop mirror: keep restoring `helios_laptop` after every swap.**

**Stage 1 (the build):**

- `apps/menu_pipeline/swap_gate.py`: the comparison, the two bars, the lost-venue kinds and a JSON
  verdict.
- `apps/menu_pipeline/batch_loop.py`: phases `full`, `fetch`, `extract`, `extract-no-model`, an
  optional `--server` for a remote `llama-server`, `pi`/`laptop` thermal modes, the `STOP` file,
  `--stop-every`, the `MASTER` marker check, and "done when a fetch takes fewer URLs than the
  limit" (P8-23's runaway loop: four redirecting URLs stayed due, so "fetched == 0" never came).
- `infra/pipeline-host/`: the master move (dump, restore, fence reset, replay sync), the
  `helios_next` swap, and a systemd unit for manual starts.

Stage 1 is deployed by the owner; no host runs it before then.

## Amendment 1 (2026-11-24): Phase 6 monthly runs

**Status:** Accepted 2026-11-24, decided under the owner's delegation (session P8-29; owner: "I
delegate the design. Take the recommended option"). The owner may overturn any item before the
build PR merges. Built in a separate PR.

ROADMAP Phase 6 asks for a monthly run on the Pi after discovery, a run report, and the monthly
spot check (ADR-0013 §8, Amendment 3). Decision 2 above left the timer for this point: "a timer
only when Phase 6's monthly cadence starts, with `OnCalendar` in UTC". This amendment says when
the timer fires, what a scheduled run does when it reaches the gate, and what the run report
holds and where it lives.

### A1. The timer

- **`infra/pipeline-host/helios-pipeline-monthly.timer`** starts the existing
  `helios-pipeline-loop.service`:
  - `OnCalendar=*-*-10 18:00:00 UTC`. The Pi's clock is Asia/Shanghai, so the time zone is
    named. That is 02:00 on the Pi and 12:00 in Austin.
  - `Persistent=true`: a firing missed while the Pi was off runs at the next boot.
  - The owner enables it once with `sudo systemctl enable --now helios-pipeline-monthly.timer`.
    The service keeps no `[Install]` section, so manual starts work as before.
- **One unit for both kinds of start.** systemd never runs a second copy of an active service.
  A firing while a manual run is going does nothing, so two loops cannot write the master at
  once.
- **Why the 10th.** The first firing is 2026-12-10 18:00 UTC, the day after most menu URLs come
  due again (20-day refetch window after the 2026-11-19…23 recrawl). After that the day does not
  matter: each run fetches every due URL once, and the 20-day window is shorter than the ~30 days
  between runs, so every URL is due again at the next firing. On the Pi (systemd 249),
  `systemd-analyze calendar "*-*-10 18:00:00 UTC"` gives its next run as Thu 2026-12-10
  18:00:00 UTC.
- **"After discovery."** Discovery is not scheduled. ADR-0030 left that out, and a discovery run
  needs a downloaded Overture release and writes the master. The month's discovery (an Overture
  refresh when a new release exists, then `resolve_urls`) stays an owner or agent step against
  the master, done before the 10th. The run that follows fetches whichever menu URLs exist by
  then. A month without discovery still refetches every saved URL, and that is the freshness
  job. Scheduling discovery belongs in its own amendment (ADR-0009 §3).
- **`loop.env` for monthly runs: `--stop-every 0`.** A monthly run goes to the end of the due
  URLs and stops once, at one gate. The 10-batch cadence was for the 1,746-URL recrawl, when
  public lagged by days. With `--stop-every 10`, a scheduled run would stop after batch 10 and
  leave the rest due until a reader swapped and restarted it. The owner may keep 10;
  `loop.env.example` shows both.

### A2. What a run does at the gate: it stops and waits for a reader

No run swaps on its own. ADR-0030 rules out "a swap with no human or agent reading the gate
report". A passing gate still leaves judgement to the reader: the median shift has no bar, gained
venues are not checked, and a swap may need a deploy first. So a run ends the same way whether the
gate passes or stops.

**When the loop ends normally** (a fetch took fewer URLs than `--batch` ("done"), `--stop-every`
was reached ("swap due"), or an `extract` / `extract-no-model` phase exited 0). A `fetch`-phase
run is the exception and gets the report only: its pages are not extracted yet, and a marker
would block the extraction phase that follows (P8-23's fetch-then-extract pattern).

1. **Wrap on the master:** `apps.menu_pipeline.rescore`, then `apps.gold.refresh`, then
   `apps.menu_pipeline.swap_gate --public helios --master <db>`, saved as the run's `gate.json`.
   `place_sweep` is not part of the automatic wrap. It runs only when the code has new
   withdrawal rules, and the reader runs it before regating.
2. **The spot-check packet** (A4).
3. **The run report** (A3), which carries the gate's verdict and the spot check's seed.
4. **The `var/pipeline-host/AWAITING_SWAP` marker**, holding the run id, the gate's exit status
   and the time.

No dump is taken and nothing is restored. The swap stays the README's manual sequence (`dump.sh`,
then `swap.sh`).

**When the loop ends otherwise** (the `STOP` file, or a failed CLI): only the run report, with
the end reason. There is no wrap, gate, packet or marker. `STOP` means a person ended the run on
purpose, and a failed CLI needs a reader anyway. Both cases leave pages due for the next run.

**A wrap step that fails** (rescore or Gold refresh non-zero, or the gate exiting with anything
other than 0 or 1): the loop still writes the report and the marker, records the failed step,
and exits 1.

**The marker blocks the next start.** While `AWAITING_SWAP` exists, the loop refuses to start
(exit 2, logged with the run it waits for). This applies to a timer firing as well; the refusal
is in the journal, and the next report's freshness shows what the wait cost. The marker is
removed in one of two ways:

- `swap.sh`, after a successful swap;
- by hand (`rm var/pipeline-host/AWAITING_SWAP`), when the reader decides to continue without a
  swap (for example, a stopped gate that needs more batches first).

### A3. The run report

**`python -m apps.menu_pipeline.run_report`** runs in the worker image (it needs the master
database). The loop runs it at every loop end except a refusal. It reads:

- the run's lines in `var/pipeline-host/logs/progress.log` (from the last `loop start`);
- each batch's CLI summary (`batch-NNN-{fetch,extract,extract-only}.out`, the
  `menu-page run complete:` and `extraction run complete:` lines);
- the run's `gate.json`, when there is one;
- the master database, for freshness.

**Where it lives.** `var/pipeline-host/reports/<run-id>/` on the master's host, where `<run-id>` is
the loop start in UTC (`20261210T180002Z`). The folder holds:

- `run-report.json` and `run-report.md` (a short summary for people);
- `gate.json`;
- `spot-check/`.

The loop creates `reports/<run-id>/` with mode 0777, because the worker runs as uid 999 and
cannot write `var/pipeline-host/` (P8-28, #180). `var/replay/` and `var/site-cache/` are already
set up the same way. Reports are a few kilobytes and are never pruned. They are not committed: at
the swap, the reader copies the figures into the run record in `docs/reviews/`, as P8-23 did.

**Contents:**

| Section | Fields |
|---|---|
| Run | id, host, phase, database, commit (`DEPLOYED_COMMIT`), start and end (UTC), end reason, batches |
| Pages | URLs fetched, renders, records with a new or changed Version, unchanged re-reads, URLs not yet due after the last batch; pages extracted, of those from saved answers, model pages, chunks sent and chunks reused, items and prices written |
| Outcomes by reason code | Capture outcomes and reason codes (fetch), extraction failures by reason, due pages by reason, R4 withdrawals |
| Model | model pages, extraction hours, model pages/h, all extracted pages/h |
| Thermal (ADR-0013 §3) | SoC peak: the highest of each extraction's probe and the loop's end-of-batch readings. Lowest CPU frequency cap (`scaling_max_freq / cpuinfo_max_freq`). `throttled` = a cap below 1.0. All per batch as well |
| Freshness (ROADMAP §2) | as of the report's time, in the master: covered venues (venues with a menu, the API's `_has_menu`), venues observed within 45 days, their share against the 80% target, and venues by age of their newest observation (≤ 20 d, 21–45 d, > 45 d, never) |
| Gate | passed, stop reasons, row and venue change, median shift, lost venues by kind |
| Spot check | seed, candidate pages, pages drawn, packet path |

**A venue's newest observation** is the newest `succeeded` `menu-page` Capture at an endpoint of
any record behind the venue's Gold rows (Establishment or Organization scope, as the gate reads
them). An unchanged re-read writes such a Capture without a Version (ADR-0013 Amendment 4), so a
venue whose menu did not change is still fresh. Freshness is measured in the master, not public:
public lags until the swap, and the swap makes it equal to the master.

### A4. The monthly spot check (ADR-0013 §8, Amendment 3 item 4)

**`python -m apps.menu_pipeline.spot_check`** runs in the worker image, at a normal loop end, after
the gate and before the report.

**What it draws:** 10 of the run's newly extracted pages, or all of them if there are fewer. A
page qualifies when all of these hold:

- it is a published `llm` Menu page;
- it was accepted between the run's start and end;
- it is the first `llm` page of its Version, meaning new or changed text.

Re-interpretations after a pipeline bump repeat known text, so they are not drawn; new layouts
come with new text.

**Seed:** the run id's digits (`20261210180002`), unless `--seed` is given. It is recorded in the
packet's manifest and the run report.

**The packet,** `reports/<run-id>/spot-check/`, is laid out the way `apps.menu_pipeline.evaluate`
reads it:

- `pages/<page_id>.html` and `pages/<page_id>.blocks.json`: the Capture bundle as production
  read it (`page_html` and the bundle's segmented blocks). The harness prefers the stored blocks
  over re-segmenting, so a page scores on what production read even after a segmenter change.
  A PDF page also keeps `<page_id>.pdf`, which is what its labeller reads (as built, P8-29);
- `labels/`: empty, for the gold-label files;
- `extract/run-<run-id>/<page_id>.json`: the run's saved page answers, kept for scoring;
- `manifest.json`: seed, window, candidate count, and per page the Menu page id, record key, URL,
  venue, Version and bundle path;
- `README.md`: the labelling brief.

**Blind labelling.** The labeller gets `pages/` and the brief only. Opening `extract/` before the
labels are frozen breaks the blind rule. After that, scoring is
`evaluate report run-<run-id> --data <packet> --labels <packet>/labels`.

**Who labels, and what a failure triggers,** stay as in Amendment 3: an agent labels, the owner
confirms disagreements, and a failure makes the pages the next held-out set without blocking the
run. Labelling is not automated, and the loop only writes the packet.

### A5. Phase 6 "done when": a re-run against unchanged data

Phase 6's "done when" clause includes "a re-run against an unchanged site produces zero new
observations and no extraction". The build PR proves it two ways:

- **An automated database test:** fetch, extract, then fetch again past the refetch window with
  the same bytes, served from the replay bundle with no network, then extract again. Expected:
  no new Version, Menu page or price observation, and no model call. The second fetch writes one
  `succeeded` Capture per URL; that Capture is the freshness signal (A3).
- **A recorded measurement on a scratch copy** of the swap-5 dump: `extract --no-model`
  against unchanged stored data finds no page due.

### Built (P8-29, 2026-11-24)

- **Code:** `apps/menu_pipeline/run_report.py`, `apps/menu_pipeline/spot_check.py`, the run's end
  steps in `batch_loop.py` (`--public` names the gate's comparison; a laptop master passes
  `helios_laptop`), `infra/pipeline-host/helios-pipeline-monthly.timer`, and `swap.sh` removing
  `AWAITING_SWAP`. Not deployed: the Pi runs `d2cadea` until the owner deploys.
- **A5, the test:** `test_a_rerun_against_unchanged_pages_adds_no_observation_and_no_extraction`
  (strict database suite). After the re-fetch: 1 URL fetched, 1 unchanged, 0 new or changed
  Versions, an extraction with 0 due and 0 chunks, the model called once in total (the first
  pass), and Versions, Menu pages and price observations unchanged, with Captures +1. The same
  test draws the first pass's page as the only spot-check candidate, scores its packet's blocks
  as the bundle's, and finds the re-read as the venue's newest observation.
- **A5, the measurement:** a scratch restore of the swap-5 dump (`helios_work-2026-11-24-p8-23-swap5.dump`,
  99,408 `current_menu` rows), with a hard-linked copy of the laptop's `var/replay` (26,176
  files). `extract --no-model`: due 0, up to date 2,863, extracted 0, chunks 0, refused model
  calls 0, 1.9 s. Versions (29,874), Captures (44,876), Menu pages (31,372), price observations
  (1,165,814) and replay files were unchanged afterwards.
- **The report on real data** (same copy, 2026-11-24 06:46 UTC):
  - **Freshness:** 1,214 of 1,233 covered venues observed within 45 days, 98.5%, which meets
    the 80% target. By age: 1,107 within 20 days, 107 at 21–45 days, 19 over 45 days.
  - **Why the 126 venues older than 20 days are stale:** 123 of them got a recrawl fetch after
    2026-11-19 that failed: 97 × `http_403`, 10 × `http_429`, 7 × `http_404`, 5 ×
    `robots_unavailable`, 2 × `http_500`, 1 × `redirect_refused`, 1 × `robots_disallowed`.
    The other 3 were not refetched. Their menus stay in Gold, because a failed fetch withdraws
    nothing.
  - **The spot check:** the P8-23 window of 2026-11-23 has 374 candidates. Seed 20261123000000
    drew 10 pages, 6 of them PDF menus. Every page's saved answers are present, and its stored
    blocks chunk into exactly as many chunks as it has answers.

### Not in this amendment

- Scheduling discovery (ADR-0009 §3).
- An unattended swap, or a dump taken before a reader asks for one.
- Labelling the spot check automatically.
- Off-box copies of reports or dumps (Phase 8).
