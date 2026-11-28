# Off-box backups and restore drills: runbook (ADR-0031 D1, D2)

Decisions: [ADR-0031](../../docs/adr/0031-phase8-operations-basics.md) (Q1–Q10). The repo
holds no secret: the R2 token, the restic password and the healthchecks.io ping URLs live on
each host in `~/.config/helios-ops/` (mode 0700, files 0600), and the restic password also lives
in the owner's password manager. Without that second copy, the encrypted backup can't be read
once the Pi is lost.

| Piece | What it does |
|---|---|
| `backup.sh` | The nightly backup: the manifest, `pg_dump -Fc -Z0` of `helios` and `helios_work` streamed into restic, `var/replay/` + `var/pipeline-host/` + `DEPLOYED_COMMIT`, retention 7/5/12, prune on Sundays |
| `helios-backup.service`, `.timer` | Runs it daily at 09:00 UTC, as `orangepi`, secrets via `EnvironmentFile=` |
| `restic.sh` | restic with the secrets loaded (the Pi's shell is fish, which can't source `r2.env`) |
| `fetch-night.sh` | One night's `helios.dump`, `helios_work.dump` and `manifest.json` out of the repository |
| `laptop-copy.sh` | The laptop's monthly `restic copy` into its own repository (Q5b) |
| `install-restic.sh` | restic 0.19.1, pinned by version and sha256 (arm64 and amd64) |
| `bootstrap.sh` | A freshly flashed Orange Pi OS to a host that can restore and serve (drill B) |
| `r2.env.example` | The names in `r2.env`, no values |
| `../pipeline-host/recover.sh` | Restores a night into a host with **no** public database (refuses on a live host) |
| `apps.menu_pipeline.backup_manifest` | The facts a restore is checked against: alembic, `current_menu` rows, venues with a menu, newest `effective_instant` |

**The lock.** `swap.sh` (both modes), `recover.sh` and `backup.sh` hold
`var/pipeline-host/db.lock` (`lib.sh` `db_lock`). A backup that meets a swap waits up to 2 h
instead of dumping mid-rename. A running pipeline loop doesn't take the lock: `pg_dump` reads one
snapshot.

**One night in the repository.** Every snapshot of a night has host `helios-pi` and the tag
`night-<UTC stamp>`: `/helios.dump`, `/helios_work.dump`, the files, and `/manifest.json`. The
manifest is written last, so a night that has one is complete (`fetch-night.sh` takes the newest
such night). `restic.sh snapshots --host helios-pi` lists them.

## One-time setup (after the 2026-12-10 run's swap, with the owner's go-ahead)

Owner, in the Cloudflare dashboard and the password manager:

1. **R2 → Create bucket** `helios-backups` (Standard storage, automatic location).
2. **R2 → Manage API tokens → Create token:** permission *Object Read & Write*, scoped to
   `helios-backups` only, no expiry (rotation below). Keep the S3 access key ID and secret: the
   dashboard shows them once. Note the account ID in the S3 endpoint.
3. **The restic password:** generate one of at least 32 random bytes (for example
   `openssl rand -base64 33`), save it in the password manager **first**, then on the Pi.

On the Pi, after a deploy that contains this directory:

```bash
sudo bash infra/backup/install-restic.sh                    # restic 0.19.1, sha256-checked
install -d -m 0700 ~/.config ~/.config/helios-ops
install -m 0600 infra/backup/r2.env.example ~/.config/helios-ops/r2.env
nano ~/.config/helios-ops/r2.env                            # the key pair and the account ID
install -m 0600 /dev/null ~/.config/helios-ops/restic-password
nano ~/.config/helios-ops/restic-password                   # paste from the password manager
bash infra/backup/restic.sh init                            # once: creates the repository in R2
sudo cp infra/backup/helios-backup.service infra/backup/helios-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start helios-backup                          # the first run, watched:
journalctl -u helios-backup -f
bash infra/backup/restic.sh stats --mode raw-data           # record the real first-snapshot size
sudo systemctl enable --now helios-backup.timer
systemctl list-timers helios-backup.timer                   # next firing (the Pi shows local time)
```

`hc.env` (D5, `infra/ops/`) adds `HC_BACKUP_URL`. Without it the backup runs unwatched.

**Rotation.** R2 token: yearly or on suspicion. Create a new token, replace the two keys in
`r2.env`, then delete the old token (no downtime). restic password: `restic.sh key add` (new
password in the password manager first), update `restic-password`, then `restic.sh key remove
<old id>`. No re-upload.

## Drill A: data restore on the laptop (monthly, after the swap; about 15 minutes)

It proves the backup is readable and complete, using the password from the password manager,
not from the Pi. The laptop's `~/.config/helios-ops/` holds its own `r2.env` and
`restic-password` (from the password manager). Record each time in the run record.

```bash
bash infra/backup/laptop-copy.sh                            # the monthly second copy (Q5b), checked
bash infra/backup/fetch-night.sh ~/helios-drill/<date>      # prints the night, seconds, sha256s
DATA=<deploy dir> bash infra/pipeline-host/restore.sh laptop helios_drill ~/helios-drill/<date>/helios.dump
uv run --env-file <deploy dir>/.env python -m apps.menu_pipeline.backup_manifest --db helios_drill \
  --expect ~/helios-drill/<date>/manifest.json --as helios   # must print "match"
uv run --env-file <deploy dir>/.env python -m apps.menu_pipeline.with_db helios_drill \
  -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8090 &
curl -fsS -o /dev/null -w '%{http_code} %{time_total}\n' 'http://127.0.0.1:8090/v1/venues?has_menu=true&limit=1'
curl -fsS -o /dev/null -w '%{http_code} %{time_total}\n' http://127.0.0.1:8090/v1/price-index/cells
kill %1
uv run --env-file <deploy dir>/.env python -m apps.menu_pipeline.with_db postgres \
  --pg psql -c 'DROP DATABASE helios_drill WITH (FORCE)'
```

Record: download seconds (`fetch-night.sh`), restore seconds (`restore.sh`), the manifest match,
both 200s. A mismatch or a failed restore is a finding in `docs/reviews/`.

## Drill B: bare metal on a spare microSD (the Phase 8 bar: under 30 minutes)

Week of 2026-12-14, owner at the board (Q9). Never within three days of the 10th. The eMMC is
never touched: the fallback is to power off, remove the card and boot. **The site is down for the
drill** (about 30–40 minutes), so pick a quiet hour.

**Before the clock (not counted):**

- Confirm the board boots from the card ahead of the eMMC (the SPI flash may hold a bootloader
  that changes the order): boot a card once and check `lsblk` / `findmnt /`.
- Flash the same Orange Pi Ubuntu 22.04 server image the Pi runs onto the card (laptop, ~10 min).
- On the laptop: `bash infra/backup/fetch-night.sh ~/helios-drill/b` and note the manifest's
  `commit` and `tag`. Have the password manager open (restic password, R2 keys) and the tunnel's
  connector token from the Zero Trust dashboard (Networks → Tunnels → the tunnel → install
  connector).
- Power off the Pi (`sudo poweroff`), insert the card, power on.

**The clock starts at the first login on the fresh OS.** Write down each step's end time.

| # | Step | Budget |
|---|---|---|
| 1 | Network: Wi-Fi (`sudo nmcli dev wifi connect <SSID> password <…>`) or a cable. Any address works; the tunnel is outbound | 1 min |
| 2 | `curl -fsSLO https://raw.githubusercontent.com/First-Helios/First-Helios/<commit>/infra/backup/bootstrap.sh && sudo bash bootstrap.sh <commit>`, then log out and back in (docker group) | 8 min |
| 3 | Secrets: `~/.config/helios-ops/r2.env` and `restic-password`, mode 0600, from the password manager (as in setup) | 1 min |
| 4 | Images and data, in two terminals (below) | 7–8 min |
| 5 | Frontend: on the laptop, the owner's `helios-deploy-frontend` (or `rsync -a --delete --exclude .git` of the frontend checkout to `~/First-Helios_Frontend/`), then `sudo systemctl start helios-frontend` | 1 min |
| 6 | Tunnel: `sudo cloudflared service install <token>` | 2 min |
| 7 | Checks (below) | 1 min |

Step 4, from `~/First-Helios`:

```bash
DC="docker compose -f infra/docker-compose.yml -f infra/docker-compose.pi.yml --env-file .env"
# terminal 1: images (Postgres pulled, the API built natively)
$DC up -d postgres && $DC build api migrate
# terminal 2: the night's dumps, into var/ so the API container can read the manifest
bash infra/backup/fetch-night.sh var/recover <tag>
# then, once both are done:
bash infra/pipeline-host/recover.sh var/recover/helios.dump var/recover/helios_work.dump
$DC up -d api                                               # migrate runs first: a no-op at this commit
```

Step 7, the clock stops when all of these pass:

```bash
$DC run --rm --no-deps -T api python -m apps.menu_pipeline.backup_manifest \
  --db helios --expect var/recover/manifest.json            # "match": rows, venues, alembic (Q10)
for u in https://firsthelios.com/ https://firsthelios.com/healthz \
  'https://firsthelios.com/v1/venues?has_menu=true&limit=1' https://firsthelios.com/v1/price-index/cells; do
  curl -s -o /dev/null -w "%{http_code} $u\n" "$u"
done                                                        # all 200
```

The API has no count endpoint, so the manifest's counts are compared in the database the public
API serves. The public URLs prove the tunnel, the frontend and the API serve it.

**After the clock:** record the step times in `docs/reviews/` (Phase 8's bar is met only under
30 minutes; ADR-0031 exit trigger 4 if it misses for reasons a hosted box would avoid). Then
`sudo poweroff`, remove the card, boot the eMMC, and check the site with `swap.sh`'s public URLs.
The card's tunnel connector disappears with it. Delete the stale connector in the dashboard if
one is listed.

## A real recovery (the Pi is lost)

Drill B's steps, on whatever host replaces it, with these additions:

- **Before `recover.sh`:** restore the night's files into the deploy directory (the tree is
  stored relative to it), so `var/replay/` and the run reports come back. `recover.sh` then
  rewrites `MASTER`:

  ```bash
  bash infra/backup/restic.sh snapshots --host helios-pi --tag <tag>   # the files snapshot's ID
  bash infra/backup/restic.sh restore <id> --target ~/First-Helios
  ```

- **After the site serves:** the worker image (`$DC --profile menu build worker`), the models
  (`python -m apps.menu_pipeline.models download …`, checked against `config/models.yaml`), the
  pipeline units and timer (`infra/pipeline-host/README.md`), these backup units, and the static
  `192.168.1.191` address if the host is on the home LAN again.
