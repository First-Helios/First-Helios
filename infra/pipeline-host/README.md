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
| `dump.sh`, `restore.sh` | One database to a dump (sha256), or a dump into one non-public database, **always** followed by the admission-fence reset |
| `move-master.sh` | A master move between the Pi and the laptop (run on the laptop) |
| `replay-sync.sh` | `var/replay/` between the hosts |
| `mark-master.sh` | Writes `var/pipeline-host/MASTER` |
| `swap.sh` | The swap into public: `helios_next`, then the rename, the checks, and an automatic rollback |
| `mirror-laptop.sh` | `helios_laptop` restored from the swapped dump |
| `laptop-llama.sh` | The laptop GPU's `llama-server` (P8-23's image and flags) |
| `helios-pipeline-loop.service`, `loop.env.example` | The loop under systemd on the Pi, for manual starts only |

Nothing here has run on a host yet: this is stage 1, and the owner deploys it.

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
2. Pi: `sudo systemctl start helios-pipeline-loop`. It stops itself after `--stop-every`
   batches ("swap due"), or when a fetch takes fewer URLs than `--batch` (done). It also stops
   on `touch var/pipeline-host/STOP` or after a failed CLI. Watch with `journalctl -u
   helios-pipeline-loop -f` or `tail var/pipeline-host/logs/progress.log`. From the laptop,
   use short polls only: `timeout 60 ssh -o ConnectTimeout=10 -o ServerAliveInterval=15 …`.
3. When the GPU is needed back: `touch var/pipeline-host/STOP` on the laptop (ends
   `gpu-watch`), then `laptop-llama.sh down`. The Pi's extraction then fails three chunks in
   a row, the loop stops, and the pages stay due. Change `--server` in `loop.env` before
   restarting.

## The swap (on the Pi, loop stopped)

```bash
DC="docker compose -f infra/docker-compose.yml -f infra/docker-compose.pi.yml --env-file .env"
W="python -m apps.menu_pipeline.with_db helios_work"
B=~/helios-backups/<run>
$DC --profile menu run --rm --no-deps -T worker $W -m apps.discovery.place_sweep  # only with new withdrawal rules
$DC --profile menu run --rm --no-deps -T worker $W -m apps.menu_pipeline.rescore
$DC --profile menu run --rm --no-deps -T worker $W -m apps.gold.refresh
$DC --profile menu run --rm --no-deps -T worker python -m apps.menu_pipeline.swap_gate \
  --public helios --master helios_work --out var/pipeline-host/gate.json
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

## Open (owner)

- **`llama-server --api-key`** (ADR-0030 Q3): the client sends no key, and adding one touches
  auth and secrets (stop-and-ask). Until then, bind the laptop's server to the LAN only while
  a run uses it, as P8-23 did.
