# Pipeline host: runbook (ADR-0030 stage 1)

How a pipeline run moves data from the master database into the public one. Decisions:
[ADR-0030](../../docs/adr/0030-pipeline-host-runs.md). The database-facing pieces are tested
CLIs in `apps/menu_pipeline/`, and the host glue lives here.

| Piece | What it does |
|---|---|
| `python3 -m apps.menu_pipeline.batch_loop` | The batch loop: phases, `STOP`, `--stop-every`, the `MASTER` check, thermal modes (on the host, stdlib only) |
| `python -m apps.menu_pipeline.swap_gate` | The gate: rows and venues with a menu each fall under 5%, and every lost venue is classified (worker image) |
| `python -m apps.menu_pipeline.extract --no-model` | Re-interpretation from saved answers only (replaces P8-23's `nomodel.py`) |
| `python -m apps.menu_pipeline.with_db` | Points a CLI (`-m`) or a PostgreSQL tool (`--pg`) at another database of the same server |
| `python -m apps.menu_pipeline.run_report` | The run report: pages, outcomes by reason code, model pages/h, SoC and throttling, 45-day venue freshness, the gate (worker image; the loop runs it at every run end) |
| `python -m apps.menu_pipeline.spot_check` | The monthly spot check's labelling packet: 10 newly extracted pages, seeded (worker image; the loop runs it at a normal run end) |
| `dump.sh`, `restore.sh` | One database to a dump (sha256), or a dump into one non-public database, **always** followed by the admission-fence reset |
| `move-master.sh` | A master move between the Pi and the laptop (run on the laptop) |
| `replay-sync.sh` | `var/replay/` between the hosts |
| `mark-master.sh` | Writes `var/pipeline-host/MASTER` |
| `swap.sh` | The swap into public: `helios_next`, then the rename, the checks, and an automatic rollback |
| `mirror-laptop.sh` | `helios_laptop` restored from the swapped dump |
| `laptop-llama.sh` | The laptop GPU's `llama-server` (P8-23's image and flags) |
| `helios-pipeline-loop.service`, `loop.env.example` | The loop under systemd on the Pi (never enabled at boot) |
| `helios-pipeline-monthly.timer` | Phase 6: starts the loop on the 10th of each month, 18:00 UTC (ADR-0030 Amendment 1) |

Stage 1 is deployed on the Pi (`d2cadea`, 2026-11-24): the unit is installed and `MASTER` names
the Pi. Amendment 1's pieces (the run's end steps, the report, the spot check, the timer) reach
the Pi with the next deploy, and the timer needs the owner's `sudo` install below.

## Roles

- **The master** is the only database the pipeline writes: `helios_work` on the Pi (the
  normal case) or `helios_laptop`. `var/pipeline-host/MASTER` on each host names it.
- **Public `helios`** (Pi) changes only through `swap.sh`.
- **`helios_laptop`** mirrors public after each swap, while the master is on the Pi.

## One-time setup on the Pi (owner)

1. Deploy a commit that contains this directory (the usual `git archive`, rsync and
   `DEPLOYED_COMMIT` steps; README "Staging (Pi)"), then rebuild the worker image, because
   `extract --no-model` and `with_db` are new code.
2. Install the unit: see the header of `helios-pipeline-loop.service`. Copy
   `loop.env.example` to `var/pipeline-host/loop.env`.
3. Mark the master: `bash infra/pipeline-host/mark-master.sh pi <DEPLOYED_COMMIT>
   <sha256 of the dump helios_work was restored from>`. `helios_work` equals public after
   swap 5 (dump `helios_work-2026-11-24-p8-23-swap5.dump`, a9af1391…).

## A run (master on the Pi, GPU pages on the laptop)

1. Laptop: `DATA=<deploy dir> bash infra/pipeline-host/laptop-llama.sh up 192.168.1.183`,
   then, in a second terminal:
   `python3 -m apps.menu_pipeline.batch_loop --host laptop --phase gpu-watch --data-dir <deploy dir>`.
2. Pi: `sudo systemctl start helios-pipeline-loop` (or the monthly timer does). It stops
   itself after `--stop-every` batches ("swap due"), or when a fetch takes fewer URLs than
   `--batch` (done). It also stops on `touch var/pipeline-host/STOP` or after a failed CLI.
   Watch with `journalctl -u helios-pipeline-loop -f` or `tail
   var/pipeline-host/logs/progress.log`. From the laptop, use short polls only: `timeout 60
   ssh -o ConnectTimeout=10 -o ServerAliveInterval=15 …`.
   - At "done" or "swap due" the loop wraps the master itself (rescore, Gold refresh, the
     gate), writes the spot-check packet and the run report under
     `var/pipeline-host/reports/<run>/`, and leaves `var/pipeline-host/AWAITING_SWAP`. It never
     swaps. Until the marker is gone the loop refuses to start (see "Phase 6 monthly runs").
   - A `STOP` or a failed CLI writes the report only.
3. When the GPU is needed back: `touch var/pipeline-host/STOP` on the laptop (ends
   `gpu-watch`), then `laptop-llama.sh down`. The Pi's extraction then fails three chunks in
   a row, the loop stops, and the pages stay due. Change `--server` in `loop.env` before
   restarting.

## Phase 6 monthly runs (ADR-0030 Amendment 1)

**Install the timer once** (owner, sudo), after a deploy that contains it:

```bash
sudo cp infra/pipeline-host/helios-pipeline-monthly.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now helios-pipeline-monthly.timer
systemctl list-timers helios-pipeline-monthly.timer   # next firing; Pi shows local time
```

Set `--stop-every 0` in `var/pipeline-host/loop.env` (see `loop.env.example`), so a monthly
run goes to the end of the due URLs and stops once, at one gate.

**Each month:**

1. Before the 10th, discovery (owner or agent, by hand, against the master), when there is a
   new Overture release.
2. The 10th, 18:00 UTC: the timer starts the loop.
3. At the run's end, the reader reads `var/pipeline-host/reports/<run>/`:
   - `run-report.md` (and `.json`): pages fetched, changed and extracted, outcomes, model
     pages/h, SoC peak and frequency cap, freshness against 45 days / 80%, and the gate;
   - `gate.json`: `passed`, `stop_reasons`, `lost_by_kind`;
   - `spot-check/`: the labelling packet (`README.md` is the brief; the labeller sees
     `pages/` only).
4. Then one of:
   - **swap**: from "The swap" below, skip the wrap (already done) and run `dump.sh` and
     `swap.sh` with `reports/<run>/gate.json`. `swap.sh` removes `AWAITING_SWAP`;
   - **continue without a swap**: `rm var/pipeline-host/AWAITING_SWAP`, then start the loop.
5. The spot check: label the packet blind, then score it (the brief has the command); a
   failure is a finding in `docs/reviews/` (ADR-0013 Amendment 3).

A timer firing while `AWAITING_SWAP` exists starts the loop, which refuses (exit 2): the unit
shows as failed and the journal says which run waits. A firing while a run is going does
nothing.

**A report by hand** (for example, after a run that ended on `STOP`), in the worker:

```bash
$DC --profile menu run --rm --no-deps -T worker $W -m apps.menu_pipeline.run_report \
  --run-id <run> --end-reason stop_file
```

## The swap (on the Pi, loop stopped)

```bash
DC="docker compose -f infra/docker-compose.yml -f infra/docker-compose.pi.yml --env-file .env"
W="python -m apps.menu_pipeline.with_db helios_work"
B=~/helios-backups/<run>
$DC --profile menu run --rm --no-deps -T worker $W -m apps.discovery.place_sweep  # only with new withdrawal rules
$DC --profile menu run --rm --no-deps -T worker $W -m apps.menu_pipeline.rescore
$DC --profile menu run --rm --no-deps -T worker $W -m apps.gold.refresh
# stdout, redirected by the host shell: the worker runs as uid 999 and can't write var/pipeline-host/
$DC --profile menu run --rm --no-deps -T worker python -m apps.menu_pipeline.swap_gate \
  --public helios --master helios_work > var/pipeline-host/gate.json
bash infra/pipeline-host/dump.sh pi helios_work $B/helios_work-swapN.dump
bash infra/pipeline-host/swap.sh var/pipeline-host/gate.json $B/helios_work-swapN.dump $B
```

- **A stopped gate** (exit 1) is a stop-and-ask. Read `gate.json`: `stop_reasons`,
  `lost_by_kind` and each lost venue's records. An `unclassified` venue needs a page check.
  If the owner says go, pass their reason as `swap.sh`'s 4th argument.
- **`swap.sh`** refuses a dump whose `alembic_version` differs from public's (deploy first). A
  failed check renames back on its own. `swap.sh --rollback` restores the previous public
  database (`helios_prev`, kept until the next swap) by hand.
- **Afterwards, on the laptop:** `DATA=… BACKUPS=… bash infra/pipeline-host/mirror-laptop.sh
  helios-backups/<run>/helios_work-swapN.dump`.
- **Retention (Q7):** after the run record merges, keep 3 dumps per run: the pre-run public
  dump, the last pre-swap dump and the last swapped master dump.

## Moving the master (ADR-0030 D1; only when the Pi can't run it)

Stop the loop first (`STOP`, then wait for "loop end"). On the laptop:

```bash
DATA=<deploy dir> BACKUPS=<backup dir> bash infra/pipeline-host/move-master.sh pi-to-laptop
```

The laptop runs the loop from a `git archive` of the Pi's `DEPLOYED_COMMIT`, with a
`DEPLOYED_COMMIT` file in it (the loop compares it with `MASTER`):

```bash
git archive <commit> | tar -x -C <code dir> && echo <commit> > <code dir>/DEPLOYED_COMMIT
cd <code dir> && python3 -m apps.menu_pipeline.batch_loop --host laptop --data-dir <deploy dir> \
  --server http://127.0.0.1:8083
```

Move back with `move-master.sh laptop-to-pi`. Every restore resets the admission fence.

## Host gotchas (P8-23)

- The Pi's login shell is `fish`, so ssh one-liners can't use `$(...)`. These scripts send
  plain `bash <script> <args>` commands.
- The Pi's clock is Asia/Shanghai. The loop logs in UTC.
- Never `pkill -f <pattern>` over ssh when the pattern is in the ssh command line: it kills the
  ssh session.
- The Pi's system Python is 3.10, so the loop is written for it (a test checks the syntax).

## Decided under the owner's delegation (2026-11-24)

- **No `llama-server --api-key` for now** (ADR-0030 Q3). The server is on the home LAN, is bound
  to the laptop's LAN address only while a run uses it (`laptop-llama.sh up <address>`, then
  `down`), and serves only model completions. A key needs new secret handling in `.env` and the
  client, so it waits until the server is exposed beyond the LAN or runs unattended.
- **A stop mid-batch leaves no container.** The loop names each Pi worker container
  `helios-loop-<batch>-<step>`, and the unit's `ExecStopPost` removes any still running. That
  holds whether or not `docker compose run` passes systemd's SIGTERM on to its container.
