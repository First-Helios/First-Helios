# ADR-0031: Phase 8 operations basics on the Pi: off-box backups, a restore drill, image health, frontend serving, alerting, and the Pi as production

**Status:** Accepted 2026-11-28 (session P8-31). The owner answered Q6a, Q7/Q9, Q19 and Q24.
The rest were decided under the owner's delegation ("ask the questions you need answered if you
can't come to a good decision on them"), and the owner may overturn any of them before this PR
merges. See [Decisions](#decisions-2026-11-28). Proposed 2026-11-27. Nothing is built: each build
step touching `infra/` is still its own reviewed PR, and nothing reaches the Pi without the
owner's go-ahead.
**Date:** 2026-11-27
**Phase:** 8 (Operations: Prod & Resilience)
**Builds on:** [ADR-0002](./0002-containerization.md) (one image, Compose; the publishing and
multi-arch question deferred to Phase 8), [ADR-0019](./0019-public-v1-site.md) §4 and
[Amendment 1](./0019-public-v1-site.md#amendment-1-2026-11-19-what-runs-today-doc-drift-no-decision)
(the public deploy, and the Pi actually serving it), [ADR-0030](./0030-pipeline-host-runs.md)
(master database, gated swap, monthly timer), ROADMAP Phase 8 and §7 item 6 (deferred finding
R116).

## Context

`firsthelios.com` has been public since 2026-10-26. It is served from the Orange Pi through a
Cloudflare Tunnel (ADR-0019 Amendment 1). ROADMAP still calls the Pi "staging, not production"
(§4.2), and ADR-0019 Q4 (hosting) is still "deferred". Phase 8's bar is: "wipe the Orange Pi,
restore from backup, and be serving yesterday's data within 30 minutes — demonstrated, not
assumed."

The facts below were read on 2026-11-27 between 23:34 and 23:40 UTC. The Pi probe was read-only:
`df`, `lsblk`, `systemctl`, `docker ps/stats`, `pg_database_size`, and `.env` key names only,
never values. The public site was checked with `curl -I`.

### F1. The host

| | Value |
|---|---|
| Board | Orange Pi 5 Plus (RK3588, 8 cores: 4 × A55 + 4 × A76), kernel 6.1.99 |
| Memory | 31 GiB; 4.6 GiB used (Postgres 3.8 GiB, idle `llama-server` 3.3 GiB, API 83 MiB) |
| Storage | One 233 GB eMMC (`mmcblk0`): `/` 226 GB, **118 GB used (53%), 106 GB free**. No USB or NVMe disk attached |
| Network | **Wi-Fi** (`wlP2p33s0`) with a static `192.168.1.191` that the router doesn't know about (no reservation option) |
| Uptime | 24 days, since the 2026-11-03 power cut. That outage left the site at 502 until it was restarted by hand. `docker`, `helios-frontend` and `cloudflared` are now enabled at boot |
| Software | Docker 28.0.4, Compose 2.34.0, cloudflared 2026.10.4 (4 HA connections). Unattended upgrades are on. No `restic`, `rclone` or `age`. `gpg`, `zstd` and `curl` are present |
| Timers | `helios-pipeline-monthly.timer` **enabled**: next firing 2026-12-11 02:00 CST = **2026-12-10 18:00 UTC**. No crontab |

### F2. What would be lost, and where copies exist today

| Item | Size | Rebuildable? | Copies today |
|---|---|---|---|
| Public `helios` | 2.55 GB on disk; a custom-format dump is 140 MB | Only from a dump | Pi dumps taken before each deploy and swap (same eMMC); `helios_laptop`, mirrored after each swap by hand (last 2026-11-27) |
| Master `helios_work` | 2.66 GB | No: Bronze captures and extraction results (owner: never lose collected data) | A dump only when someone takes one. During a monthly run, days of fetch and extraction live **only here** |
| `helios_prev` | 2.54 GB | It is the previous public database | Kept for `swap.sh --rollback`; not a backup |
| `var/replay/` | 526 MB, 26,176 files | No: prices trace to these bundles (ROADMAP §2) | Laptop, via `replay-sync.sh` (manual, after swaps) |
| `var/models/` | 2.3 GB | Yes: re-downloaded and checked against `config/models.yaml` | None needed |
| `var/site-cache/` | 1.4 GB | Yes (fetch cache) | None needed |
| `var/pipeline-host/` (`MASTER`, `loop.env`, run reports) | 20 KB | Reports: no (never committed; figures copied into run records) | None |
| `~/helios-backups/` | 2.3 GB in 16 folders | | **All on the same eMMC** |
| Pi `.env` | | | See F3 |
| Tunnel token | | Yes: re-issued from the Cloudflare dashboard | Inside the `cloudflared` service config |
| Frontend | `~/First-Helios_Frontend` at `19db538` | Yes: the private frontend repo on GitHub | |

**Nothing is off the premises.** The laptop mirror is in the same building, isn't scheduled, and
isn't versioned. No restore onto a fresh host has ever been drilled. The only restores ever done
were into existing clusters (P8-23 restores took 374–416 s on the Pi and 59 s on the laptop,
ADR-0030 D1).

### F3. Secrets as they stand

- **The Pi's `.env` is a V1-era file.** It holds `DATABASE_URL`, `FLASK_ENV`, `FLASK_DEBUG` and
  eight third-party credentials that V2 never reads: `BLS_API_KEY`, `CBP_API_KEY`,
  `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `GOOGLE_MAPS_API_KEY`, `SERPAPI_KEY`,
  `RAPIDAPI_KEY`, `THEIRSTACK_API_KEY`, `JUJU_PARTNER_ID` (grep over `apps/`, `packages/`, YAML
  and TOML: 0 hits).
- **It has no `POSTGRES_PASSWORD` and no `HELIOS_COMPOSE_DATABASE_URL`,** so Compose falls back to
  its defaults, `helios`/`helios` (`infra/docker-compose.yml`). Postgres listens on
  `127.0.0.1:5432` only, and every container on the host is this project's, so this is a local
  risk, not a public one.
- **Nothing reaches the image.** `.dockerignore` excludes `.env`, `.env.local` and `var/`.
  `~/helios-backups/` is mode 0700.

### F4. The serving path

Cloudflare edge → tunnel → `dev_server.py` on `127.0.0.1:8080` (`helios-frontend.service`,
`Restart=always`) → API on `127.0.0.1:8000`.

- **Traffic:** since `cloudflared` started (24 days), 31,909 requests (about 1,300 a day) and 230
  errors (0.7%).
- **Local latency:** `/healthz` 6–7 ms, `/v1/venues?limit=50` 81 ms,
  `/v1/price-index/cells?area_kind=latlon_grid_0p05&limit=200` 58 ms.
- **`http://firsthelios.com/` answers 200** with no redirect and no `Strict-Transport-Security`
  header. "Always Use HTTPS" and HSTS are off.
- **Every static file is `Cache-Control: no-store`** (`dev_server.py`'s `end_headers`), and
  Cloudflare reports `cf-cache-status: DYNAMIC`/`BYPASS`. Each page view re-fetches Leaflet,
  the CSS and the JS through the tunnel.
- **No rate limit anywhere** (ADR-0019 Q5 is deferred). `ErrorCode` has no `rate_limited`.

### F5. R116 as it stands

- `infra/Dockerfile` has no `HEALTHCHECK`. Compose defines one for `api` (`/healthz` via
  `urllib`), so it exists only when the image runs under Compose.
- `test/` (1.7 MB) and `docs/` (2.9 MB) ship in the image; nothing reads them at runtime.
- The CI smoke test checks `/healthz` only.
- CI builds amd64. The Pi builds arm64 natively at deploy time. A deploy builds before
  `up -d`, so an arm64-only build failure fails the deploy, not the site. But it is found on the
  Pi, after merge.

### F6. Alerting today

None. A failed or refused monthly run (`AWAITING_SWAP`, exit 2), a full disk, or a dead site shows
only in the journal or to a visitor.

## Decision (proposed)

Six parts, each separable. Build order is at the end.

### D1. Off-box backups: restic to Cloudflare R2, nightly, encrypted on the Pi

**What is backed up, nightly:**

- `helios` (public) and `helios_work` (master), each as `pg_dump -Fc -Z0`. Uncompressed custom
  format is chosen so restic can deduplicate unchanged tables from night to night; restic
  compresses (zstd). Each dump is streamed with `restic backup --stdin-from-command`, which
  fails the snapshot if `pg_dump` exits non-zero, so a broken dump can never become a "good"
  snapshot. The dump runs inside the `postgres` container (`docker compose exec`), as
  `lib.sh`'s `pg()` already does.
- `var/replay/`, `var/pipeline-host/` (marker, `loop.env`, reports) and `DEPLOYED_COMMIT`.
- A small manifest per night: commit, `alembic_version`, `gold.current_menu` row count,
  venues with a menu, and the newest Gold `effective` time per database. The restore drill
  checks against this manifest ("yesterday's data").

**Not backed up:** `helios_prev`, `var/models/`, `var/site-cache/` (all rebuildable), and `.env`
(see secrets below).

**Where:** a Cloudflare R2 bucket, e.g. `helios-backups`, in the Cloudflare account that already
holds the domain and the tunnel. The laptop mirror stays as it is (ADR-0030 Q8) as the fast
local copy. An external USB disk on the Pi is optional (Q4).

**Tool:** [restic](https://restic.net/), a single static Go binary, pinned by version and sha256
and installed to `/usr/local/bin`. Ubuntu 22.04's packaged restic (0.12) predates compression
and `--stdin-from-command`, so the build pins a current release (≥ 0.17). It is a host tool, not
a Python dependency or a service, but it is new, hence Q1.

**When:** `helios-backup.timer`, daily at `09:00 UTC` (03:00 in Austin, 17:00 on the Pi's clock),
with `Persistent=true`. That is far from the monthly run's 18:00 UTC start on the 10th. A backup
during a running loop is safe, because `pg_dump` reads one snapshot. A backup during `swap.sh`
is not: the swap terminates connections to `helios*`. So both take one lock,
`flock var/pipeline-host/db.lock`. That needs a two-line change to `swap.sh` (Q3).

**Retention:** `restic forget --keep-daily 7 --keep-weekly 5 --keep-monthly 12`, then `prune`
once a week.

**Size and cost (estimate; the build measures the real figures):**

- **First snapshot:** about 0.3 GB of dumps after compression, plus up to 0.5 GB of replay.
- **Nightly increments:** near zero between swaps and runs, since the public database is static
  between swaps and the master between runs.
- **Steady state:** expected at 2–6 GB, inside R2's free 10 GB-month. Above it, Standard storage
  is $0.015/GB-month: 10 GB more is $0.15 a month. restic's packs are about 16 MiB, so a night is
  hundreds of writes, against 1 M free Class A operations a month. Egress (restores) is free.
- **Expected cost: $0 a month; worst case under $1.**

**Encryption:** restic encrypts on the Pi before upload (AES-256 with Poly1305
authentication). R2 holds only ciphertext. R2's own encryption at rest is not relied on.

**Credentials, and how they stay out of the repo and the image:**

| Secret | Created by | Lives in | Never in |
|---|---|---|---|
| R2 API token, scoped to the one bucket, Object Read & Write | Owner (dashboard) | Pi: `~/.config/helios-ops/r2.env` (mode 0600; directory 0700) | The repo, the deploy directory, the image, any container, logs |
| restic repository password (random, ≥ 32 bytes) | Owner | Pi: `~/.config/helios-ops/restic-password` (0600). **Also the owner's password manager.** Without an off-Pi copy, the encrypted backup can't be read when the Pi is lost | Same |
| Healthchecks ping URLs (D5) | Owner | `~/.config/helios-ops/hc.env` (0600) | Same |

- `~/.config/helios-ops/` is outside the deploy directory. The `git archive` + rsync deploy
  never touches it, it isn't in the Docker build context (the repo root), and no Compose service
  mounts it.
- restic runs on the host. `pg_dump` runs in the `postgres` container through the local socket,
  so the R2 and restic secrets never enter a container.
- The units read them with `EnvironmentFile=` and `RESTIC_PASSWORD_FILE`. The scripts never
  `set -x` or echo variables.
- The repo gets `r2.env.example` (variable names only) and a `.gitignore` entry for `r2.env` and
  `hc.env`, as a guard.

**Rotation:**

- **R2 token:** yearly or on suspicion. Create a new token, replace the file, delete the old token.
  No downtime.
- **restic password:** `restic key add`, then `restic key remove`. No re-upload.

**Known limit:** the Pi's token can delete objects, so a compromised Pi could delete its own
backups. Two answers are offered in Q5: an R2 bucket lock (retention rule) on the bucket, which
must be tested against `prune`, or the laptop pulling a second copy monthly (`restic copy`).

**The V1 `.env` (F3):** recommend the owner removes the eight V1 credentials and the `FLASK_*`
lines from the Pi's `.env`, and revokes the keys at their providers if they are still live. The
`.env` is then not worth backing up: the restore recipe recreates it from
`.env.example`-style names, with values from the password manager. Moving Postgres off the default
password is Q6.

**Owner questions (D1):**

1. **Tool and target.** restic (pinned binary) to Cloudflare R2 (*recommended*)? Or rclone +
   age (two tools, no deduplication, hand-made retention), or Backblaze B2 instead of R2 (a new
   account; similar price)?
2. **Scope and schedule.** Nightly at 09:00 UTC: `helios` + `helios_work` + `var/replay/` +
   `var/pipeline-host/` + manifest; retention 7 daily / 5 weekly / 12 monthly (*recommended*)?
3. **The lock.** Add `flock var/pipeline-host/db.lock` to `swap.sh` and the backup
   (*recommended*)? Or accept that a backup overlapping a swap fails, alerts and retries the next
   night.
4. **A local USB disk** on the Pi as a second target (fast restore without the internet,
   about $50–80 one-time), or not for now (*recommended*: the laptop mirror already gives a
   local copy)?
5. **Protection against a compromised Pi.** (a) An R2 bucket lock of 30 days, tested against
   `prune` in the build; (b) the laptop runs `restic copy` monthly into its own repository
   (*recommended*: no R2 feature dependency, and it doubles as the drill's data source); or
   (c) accept the risk.
6. **Secrets clean-up.** (a) The owner removes the V1 keys from the Pi's `.env` (*recommended*:
   now). (b) Move Postgres off `helios`/`helios`: `ALTER ROLE`, then `POSTGRES_PASSWORD` and
   `HELIOS_COMPOSE_DATABASE_URL` in `.env` (*recommended*: after the 2026-12-10 run's swap, not
   before, so the first scheduled run isn't the first run on new credentials).

### D2. The restore drill: two drills, one of them timed against the 30-minute bar

"Wipe the Pi" would also wipe the only working copy of the host, so the drills never touch the
eMMC.

**Drill A, data restore (monthly, after the swap; non-disruptive, about 15 minutes of
attention).** On the laptop:

1. `restic dump latest` of `helios`.
2. `restore.sh laptop helios_drill <dump>`.
3. Run the API image against `helios_drill` on a spare port.
4. Compare `gold.current_menu` rows, venues with a menu and `alembic_version` with the night's
   manifest, and request `/v1/venues?has_menu=true&limit=1` and `/v1/price-index/cells`.
5. Record the times (download, restore, first 200) in the run record.

This proves the backup is readable and complete, with the password from the password manager,
not from the Pi.

**Drill B, bare metal (the Phase 8 bar; once now, then after any change to the host recipe, and
at least yearly).** The Pi boots a freshly flashed stock Orange Pi OS from a **spare microSD
card**. The eMMC is left untouched, so the fallback is: power off, remove the card, boot. The
clock starts at the first login on the fresh OS. It stops when `https://firsthelios.com`
serves the backup's data: the manifest's counts match through the public API.

| Step | Budget (estimate) |
|---|---|
| (Before the clock) Flash the stock image to the card on the laptop | ~10 min, not counted |
| `bootstrap.sh` (new, in the repo): Docker from Docker's apt repo, the pinned restic, the `cloudflared` package, user and groups | 8 min |
| Code: the GitHub tarball of the manifest's commit (the repo is public), plus `DEPLOYED_COMMIT` | 1 min |
| Images: build `runtime` natively and pull Postgres; **or pull from GHCR** if D3's registry exists | 6–8 min; or 2 min |
| Data: `restic dump` → the new `recover.sh` (below) into `helios` and `helios_work` | 7 min (P8-23: 374–416 s) |
| Frontend: rsync from the laptop (private repo), then start the static server | 1 min |
| Tunnel: `cloudflared service install <token>`, with the token copied from the dashboard | 2 min |
| Checks: `swap.sh`'s endpoint list plus the manifest comparison | 1 min |
| **Total** | **~26–28 min building locally; ~20 min pulling from a registry** |

The budget is tight without a registry. That is the main argument for D3's GHCR step. The
worker image, models and `llama-server` are not needed to serve, so they are restored after the
clock stops.

**Public downtime:** the length of the drill (about 30–40 minutes) plus a reboot back to the eMMC.
Run it at a quiet hour, never within three days of the 10th, with the owner at the board.

**`recover.sh`** (new). It restores a dump into `helios` only on a cluster where `helios` does
not exist, so it refuses on a live host. It resets the admission fence, restores the same dump
into `helios_work`, and writes `MASTER`. ADR-0030's rule "public changes only through
`swap.sh`" becomes "only through `swap.sh`, or `recover.sh` on a host with no public database"
(Q8).

**Owner questions (D2):**

7. **Two drills:** A monthly on the laptop, and B once now on a spare microSD (*recommended*)?
   Or B on a rented arm64 VM instead (Hetzner CAX by the hour: cents, no site downtime, but a
   different OS image and no tunnel)?
8. **`recover.sh`** and the amended "public changes only through `swap.sh` or `recover.sh` on an
   empty host" rule (*recommended*)? Or recover through `restore.sh` + `swap.sh` with a
   hand-written gate file.
9. **Owner logistics for B:** a spare microSD (≥ 64 GB, A2 class, ~$10–15). Confirm that this
   board boots from the card ahead of the eMMC before the drill day (the SPI flash may hold a
   bootloader that changes the order). Pick a date: not 12-07 to 12-13, given the 12-10 run.
10. **The drill's definition of done:** the clock stops when the public API matches the
    manifest's `current_menu` rows, venues with a menu and `alembic_version` (*recommended*). Or
    also require the worker and the first pipeline batch.

### D3. Image health and the amd64-vs-arm64 build (R116)

**HEALTHCHECK.** In the `runtime` stage only:

```dockerfile
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"]
```

- Same probe and timings as Compose's today. **Remove** the `api` healthcheck from
  `docker-compose.yml`, so there is one definition, inherited from the image.
- `migrate` and `llama-model-check` run the same image as one-shots. They get
  `healthcheck: disable: true`.
- `worker` derives from `base`, not `runtime`, so it inherits nothing.
- `/healthz` (liveness), not `/readyz`. Plain Docker never restarts an unhealthy container, so
  the healthcheck is a status signal. Database reachability is D5's job, through `/readyz`.

**The rest of R116:**

- Add `docs/` and `test/` to `.dockerignore`. That is 4.6 MB, and the grep shows nothing reads
  them at runtime.
- **CI smoke:** wait for `.State.Health.Status == healthy`, which tests the `HEALTHCHECK`
  itself. Then run a Postgres service, `alembic upgrade head` from the image, and require
  `/readyz` and `/v1/venues?limit=1` to answer 200 on the empty database. About one more minute
  of CI.

**Arch: build arm64 natively in CI.** The repo is public, so GitHub's `ubuntu-24.04-arm` runners
are free (GA 2025-08-07).

- A sixth CI job, **"Docker image (arm64)"**, builds both `runtime` and `worker` natively and
  runs the same smoke test on `runtime`. The worker's arm64 Chromium (Playwright) is the
  likeliest arm-only break.
- It starts **non-required** for two weeks of PRs. Then the owner adds it to branch protection.

**Then, later: a registry.** ROADMAP Phase 8's "tagged releases build and push to a registry;
prod pulls".

- On a `v*` tag, both jobs push to GHCR, and a multi-arch manifest joins them.
- The Pi pulls by digest. A public package needs no credential on the Pi; CI pushes with
  `GITHUB_TOKEN`.
- This makes D2's drill comfortably fit, and makes deploys "pull, migrate, up". It changes the
  deploy flow, so it is a separate step (Q13).

**Owner questions (D3):**

11. The image `HEALTHCHECK` with Compose's `api` healthcheck removed, and `disable: true` on
    the two one-shots (*recommended*)? Or keep both definitions.
12. The arm64 CI job: native `ubuntu-24.04-arm`, non-required for two weeks, then required
    (*recommended*)? Or QEMU buildx on amd64 (slow; Chromium under emulation is fragile), or
    keep amd64-only and rely on the Pi's deploy build.
13. GHCR publishing on tags, with the Pi pulling by digest: as a follow-up ADR amendment after
    the arm64 job is green (*recommended*), now, or never (keep building on the Pi)?
14. `docs/` and `test/` out of the image, and the `/readyz` CI smoke (*recommended*)?

### D4. Serving the frontend: nginx in the Compose stack, replacing `dev_server.py`

**Why change.** `dev_server.py` has run for 24 days without an incident, and it hardens Host and
paths itself. But:

- It is `http.server`, which Python's docs say is "not recommended for production".
- It sends `no-store` on every static file (F4), so nothing is cached by browsers or Cloudflare.
- It has no rate limit.
- It is one more process outside Compose with its own unit.

**Proposed:** a `web` service in `infra/docker-compose.yml`:

- **Image:** the official multi-arch `nginx` stable Alpine image, pinned by digest (R90 style).
- **Config:** `infra/nginx/firsthelios.conf`, mounted read-only.
- **Static files:** `~/First-Helios_Frontend` bind-mounted read-only. `helios-deploy-frontend`
  keeps rsyncing there and no longer restarts anything.
- **Behaviour:**
  - Serves only `/`, `/index.html`, `/css/`, `/js/`, `/vendor/` (as `dev_server.py` does); 404
    for everything else, no directory listings.
  - Proxies `/v1/`, `/healthz` and `/readyz` to `api:8000`.
  - Caching: `index.html`, CSS and JS get `no-cache` (revalidate with ETag; file names aren't
    hashed). `vendor/` gets `max-age=86400`.
  - gzip; `X-Content-Type-Options: nosniff` and `Referrer-Policy`. The CSP stays in the page's
    meta tag. HSTS is set at Cloudflare.
  - `server_name firsthelios.com www.firsthelios.com 127.0.0.1 localhost`, with a default
    server that drops other Host values (dev_server's DNS-rebinding guard).
- **Rate limiting, second line behind Cloudflare:**
  - The client IP comes from `CF-Connecting-IP`, trusted only from the Compose network gateway
    (`real_ip_header`, `set_real_ip_from`).
  - `limit_req`: 10 r/s with burst 20 on `/v1/`, and 2 r/s with burst 5 on
    `/v1/items/*/price-history` (the numbers from ADR-0019 §4). The client loads long lists by
    itself, one page every 150 ms after the last answer, and can load two lists at once
    (frontend `js/pagination.js`). So the build must show that loading the largest drawn area
    and its venue list gets no 429 before these numbers ship.
  - A JSON 429 `{detail, code: "rate_limited", trace_id}`, with `trace_id` from `$request_id`.
    That needs `rate_limited` added to `ErrorCode` (an ADR-0008 amendment; ADR-0019 Q5).
- **Port:** `127.0.0.1:8081` during the cutover. Memory is about 10 MB.

**Cutover (owner, reversible in seconds):**

1. Bring `web` up beside `dev_server.py`.
2. Run `curl` checks against `127.0.0.1:8081`.
3. The owner changes the tunnel's published route from `localhost:8080` to `localhost:8081` in
   the dashboard.
4. After a day, `systemctl disable --now helios-frontend`.

`dev_server.py` stays in the frontend repo for local development. The same nginx config moves
unchanged to a VPS if hosting ever moves (ADR-0019 §4).

**Owner questions (D4):**

15. **nginx in Compose** (*recommended*)? Or (b) keep `dev_server.py` and fix only its caching
    in the frontend repo (no new component; rate limits only at Cloudflare's one free rule), or
    (c) Caddy instead of nginx.
16. **The 429 contract:** `rate_limited` in `ErrorCode` with nginx's JSON body, at 10 r/s burst
    20 and 2 r/s burst 5 on price history (*recommended*)? This answers ADR-0019 Q5.
17. **Also route `/v1/*` straight from the tunnel to the API** (a published path route), skipping
    the proxy hop? *Recommended: no.* One entry point keeps the limiter and logs in one place.

### D5. Minimal alerting: healthchecks.io dead-man's switches, email (and optional push)

**Channel:** [healthchecks.io](https://healthchecks.io), Hobbyist plan. It is **free** for up to
20 checks with 100 log entries each, alerts by email, and can add Telegram, Discord, ntfy or
others at no cost.

**Model:** the Pi pings, and **silence is an alert**. So "the Pi is off", "the house lost
power" and "the internet is down" alert as well, with nothing to run off the Pi.

**A second channel, independent of the Pi:** Cloudflare's "Tunnel Health Alert" notification
(email, included with Zero Trust plans), which the owner sets up. It fires when the tunnel's
connectors go down.

**Checks (6 of 20):**

| Check | Pinged by | Period / grace | Fails when |
|---|---|---|---|
| `site` | `helios-watch.timer`, every 5 min | 5 min / 10 min | Local `/readyz`, `https://firsthelios.com/healthz` or `https://firsthelios.com/v1/venues?limit=1` is not 200. The public URLs go out through Cloudflare and back through the tunnel. The failing lines are the ping body |
| `disk` | same, hourly | 1 h / 1 h | `/` at or above 85% (now 53%) |
| `backup` | `helios-backup.service`: `/start`, then success or `/fail` | 1 day / 6 h | restic or `pg_dump` fails, or the backup doesn't run |
| `monthly-run` | `helios-pipeline-loop.service`: `ExecStartPre` pings `/start`; `ExecStopPost` pings `/$EXIT_STATUS` | cron `0 18 10 * *` UTC / 4 days | The loop fails or is refused (`AWAITING_SWAP` exits 2). The timer didn't fire. Or the run hasn't ended 4 days after the 10th |
| `run-progress` | `helios-watch.timer`, hourly | 1 h / 1 h | The loop service is active and `progress.log` hasn't changed for 8 h (P8-23's slowest batch extraction: 6.6 h) |
| `awaiting-reader` | same, daily | 1 day / 1 day | `AWAITING_SWAP` is older than 3 days (a nudge, not an outage) |

**Implementation:**

- `infra/ops/watch.sh` (bash + `curl`; nothing new installed) and the
  `helios-watch.service`/`.timer` pair.
- Two lines in `helios-pipeline-loop.service`, each `curl -fsS -m 10 --retry 3`, prefixed with
  `-` so a ping failure never fails the run.
- Ping URLs live in `~/.config/helios-ops/hc.env`. Anyone holding one could send a false "all
  well", so they are kept like the other secrets.

**Cost:** $0. The only new thing is an account, which is why this is a question.

**Not proposed now:** Prometheus, node-exporter and Alertmanager (ROADMAP Phase 8). They are three
more services and a dashboard nobody watches. The six checks above are the "handful of things
that actually page". ROADMAP's "fetch failure rate" alert waits for a baseline: the 12-10 run
report gives the first monthly figure.

**Owner questions (D5):**

18. **healthchecks.io** (free) as the alert channel, plus Cloudflare's Tunnel Health Alert email
    (*recommended*)? Or self-host healthchecks (another service), or ntfy only (no
    dead-man's switch).
19. **Where alerts go:** email only (*recommended* to start), or also a phone push (Telegram,
    Discord or ntfy)?
20. **An outside prober** (UptimeRobot or Better Stack free tier) as a third, Pi-independent HTTP
    check? *Recommended: not now.* The tunnel alert covers the connector side, and silence
    covers the Pi.
21. **Thresholds:** disk 85%, run grace 4 days, progress stall 8 h, reader nudge 3 days
    (*recommended*)?
22. **Defer Prometheus/node-exporter** to after the first two monthly runs (*recommended*)?

### D6. Accept the Pi as production, for now, with exit triggers

**What runs where (measured, F1–F4):**

| | Orange Pi 5 Plus (today) | Hetzner CAX21 | Hetzner CAX31 |
|---|---|---|---|
| CPU / RAM / disk | 8 cores / 31 GiB / 233 GB eMMC (106 GB free) | 4 vCPU / 8 GB / 80 GB | 8 vCPU / 16 GB / 160 GB |
| Monthly cost | Power only: an RK3588 board at roughly 5–12 W is about 4–9 kWh, **~$0.50–1.20** (estimate, not measured) | **€10.49** + IPv4, excl. VAT (list price since 2026-06-15) | **€20.99** + IPv4 |
| Fits the API + public DB + the swap's second copy (2 × 2.5 GB) | Yes | Yes | Yes |
| Fits the pipeline (`llama-server` 5.2 GB peak, Chromium, the master) | Yes | No (8 GB) | Barely; and it loses the residential IP |
| Residential IP for fetching (ROADMAP §4.2) | Yes. Even so, the last recrawl saw 97 × `http_403` | No: datacenter IPs are blocked more | No |
| Availability | Residential power and ISP, Wi-Fi, one eMMC; one known outage (11-03, power) | Datacenter | Datacenter |
| Ops load | Exists today | A second host: patching, SSH exposure, dumps shipped over the internet each swap, a second backup source | Same |

- **A hosted move doesn't remove the Pi.** The pipeline needs the residential IP and the RAM, so
  hosting means two hosts and an internet swap path.
- **For about 1,300 requests a day,** that costs €126–252 a year plus the ops load, and buys
  datacenter power and network.
- **Hetzner's cost-optimized tiers have been reported "not available" to order** at times between
  August and October 2026 (third-party reports), so check before planning on one.

**Recommendation:** formally accept the Pi as production for now. Pair it with the cheap
mitigations, and set triggers that reopen hosting.

**Mitigations:**

- **(a) Wired Ethernet.** Free if a cable reaches the router; the board has two 2.5 GbE ports.
  It removes the Wi-Fi link and the static-IP-on-Wi-Fi gotcha from the serving path.
- **(b) Optionally, a small UPS** (~$60–100) to ride out short power cuts.
- **(c) D1, D2 and D5 above.**

**Exit triggers** (any one reopens hosting as a new ADR, with fresh prices):

1. Two unplanned outages over 1 hour in any 30 days that (a)–(c) don't prevent.
2. Sustained traffic over about 50,000 requests a day, or a public API p95 over 500 ms.
3. Any availability promise to someone else, or commercial use.
4. A drill B, or a real recovery, that misses 30 minutes for reasons a hosted box would avoid.

**Doc changes on acceptance** (each in the build PR):

- ROADMAP §4.2 becomes "the Pi is production and the pipeline host; the laptop and CI are
  pre-production". There is no separate staging host today.
- ADR-0019 Q4 is recorded as answered (b).
- README "Staging (Pi)" is renamed.
- The ADR-0002 Consequence that "prod Postgres runs on the host" is withdrawn: it stays in
  Compose.

**Owner questions (D6):**

23. **Accept the Pi as production** with exit triggers 1–4 (*recommended*)? Or start a hosting
    move now (which host, and keep the pipeline on the Pi?).
24. **Mitigations:** wired Ethernet (*recommended*), a UPS (optional, your call), both, or
    neither.
25. **Staging:** accept "laptop + CI as pre-production, no staging host" (*recommended*)? Or keep
    a staging role somewhere (a second board, or a VM by the hour).

## Build order after acceptance

Each step is its own PR. Every PR touching `infra/` gets its own review, and nothing is deployed
to the Pi without the owner's go-ahead.

1. **D3 (repo only, no Pi change):** `HEALTHCHECK`, `.dockerignore`, the CI smoke, the arm64 job.
2. **D1 + D5 scripts and units** (`infra/backup/`, `infra/ops/`, the `swap.sh` lock, two lines in
   the loop unit), with the owner creating the R2 bucket and token, the restic password and the
   healthchecks.io checks. Deployed **after the 2026-12-10 run's swap**, so the first scheduled
   run runs on the code that was deployed on 11-27. The pings could go in earlier if the owner
   wants the first run watched; that is Q26.
3. **First backup, then drill A** on the laptop. Record the times.
4. **D4 nginx** (plus the `rate_limited` ADR-0008 amendment), with the owner flipping the
   tunnel route.
5. **D2 drill B** on a microSD, timed. Record it in `docs/reviews/`. Phase 8's bar is met only
   if it is under 30 minutes.
6. **D3's GHCR step** if Q13 says so, then repeat drill B with pulls if step 5 was tight.
7. **D6 doc changes.**

26. **Watch the first scheduled run?** Deploy only the `monthly-run` and `site` pings (plus
    `hc.env`) before 2026-12-10 (*recommended*: two `-`-prefixed lines in the loop unit and one
    timer, which can't affect the run). Or wait and deploy everything after the swap.

## Decisions (2026-11-28)

**Owner** marks the owner's answers. **Delegated** marks items decided under the owner's
delegation, which take the recommendation unless noted otherwise.

| Q | Decision | By |
|---|---|---|
| 1 | restic (pinned release ≥ 0.17, sha256-checked) to a Cloudflare R2 bucket | Delegated |
| 2 | Nightly at 09:00 UTC: `helios`, `helios_work`, `var/replay/`, `var/pipeline-host/`, the manifest. Keep 7 daily, 5 weekly, 12 monthly; prune weekly | Delegated |
| 3 | `flock var/pipeline-host/db.lock` in `swap.sh` and the backup | Delegated |
| 4 | No USB disk for now (the laptop mirror is the local copy) | Delegated |
| 5 | (b) The laptop runs `restic copy` monthly into its own repository. That copy is also drill A's source | Delegated |
| 6a | The owner removes the eight V1 credentials and the `FLASK_*` lines from the Pi's `.env`, and revokes any still-live key at its provider | **Owner** |
| 6b | Postgres moves off `helios`/`helios` after the 2026-12-10 run's swap, as its own step | Delegated |
| 7 | Both drills: A monthly on the laptop; B once on the Pi from a spare microSD. The owner asked why B is needed. The answer: A proves the data, B proves the host can be rebuilt from written steps, and how long that takes. Owner chose the microSD drill | **Owner** |
| 8 | `recover.sh`, and the amended rule "public changes only through `swap.sh`, or `recover.sh` on a host with no public database" | Delegated |
| 9 | Drill B in the **week of 2026-12-14**, the owner at the board with a ≥ 64 GB A2 microSD. The card-before-eMMC boot order is checked first | **Owner** |
| 10 | The clock stops when the public API matches the manifest's `current_menu` rows, venues with a menu and `alembic_version` | Delegated |
| 11 | Image `HEALTHCHECK`; Compose's `api` healthcheck removed; `disable: true` on `migrate` and `llama-model-check` | Delegated |
| 12 | Native `ubuntu-24.04-arm` job, non-required for two weeks, then the owner makes it required | Delegated |
| 13 | GHCR publishing as a follow-up amendment, once the arm64 job is green | Delegated |
| 14 | `docs/` and `test/` out of the image; the `/readyz` CI smoke | Delegated |
| 15 | nginx in Compose replaces `dev_server.py` | Delegated |
| 16 | `rate_limited` in `ErrorCode` (an ADR-0008 amendment); nginx at 10 r/s burst 20, and 2 r/s burst 5 on price history, after the no-429 check on the largest area. This answers ADR-0019 Q5 | Delegated |
| 17 | No direct tunnel route to the API | Delegated |
| 18 | healthchecks.io (Hobbyist, free), plus Cloudflare's Tunnel Health Alert | Delegated |
| 19 | **Email only** | **Owner** |
| 20 | No outside prober for now | Delegated |
| 21 | Disk 85%, run grace 4 days, progress stall 8 h, reader nudge 3 days | Delegated |
| 22 | Prometheus and node-exporter deferred until after two monthly runs | Delegated |
| 23 | **The Pi is production for now**, with exit triggers 1–4. This answers ADR-0019 Q4 as (b) | Delegated |
| 24 | **Neither wired Ethernet nor a UPS for now.** The Wi-Fi link and residential power stay accepted risks, and D5's alerts report them. Trigger 1 (two outages over 1 h in 30 days) reopens this question first | **Owner** |
| 25 | No staging host; the laptop and CI are pre-production | Delegated |
| 26 | **Changed from the recommendation: no pings before 2026-12-10.** The owner's standing instruction for this work was not to disturb the monthly timer. So nothing changes on the Pi until that run's swap; D1, D5 and the loop-unit pings deploy together afterwards | Delegated |

**Revised schedule:**

1. D3 is repo-only, any time.
2. D1 and D5 are built as PRs before 12-10, and deployed after the 12-10 run's swap.
3. The first backup, then drill A.
4. Drill B, week of 12-14. If D1 can't be deployed and back up at least one night before the
   drill, it moves to the following week.
5. D4.
6. D6's doc changes.

**Cloudflare, as checked from outside on 2026-11-28** (after the owner changed the appendix's
settings):

| Setting | Result |
|---|---|
| Always Use HTTPS | **Working:** `http://firsthelios.com/` and `http://www.firsthelios.com/` both return 301 to `https://` |
| Minimum TLS 1.2 | **Working:** a TLS 1.1-only handshake fails; TLS 1.2 returns 200 |
| HSTS | **Working** (re-checked after the owner's fix): `strict-transport-security: max-age=2592000; includeSubDomains` on the apex and `www`. Cloudflare's No-Sniff toggle still adds no `X-Content-Type-Options` header; D4's nginx sends `nosniff` itself, so this is left as is |
| Bot Fight Mode off | **Working:** `curl` gets 200 on `/healthz`, `/v1/venues`, `/v1/price-index/cells` |
| `/v1/` rate limit (100 per 10 s per IP) | **Working** after the owner fixed the rule. The first test, 300 requests in 11.6 s, got 300 × 200. The re-test, 300 requests to `/v1/venues?limit=1` in 5.7 s, got 116 × 200 and 184 × 429; the extra 16 got through because Cloudflare counts with a short lag. The block is Cloudflare's default response: `429`, `Retry-After: 8`, `text/plain` body `error code: 1015`, not the ADR-0008 JSON shape (D4's nginx gives that). `/` kept answering 200 during the block, and `/v1/` answered 200 again 15 s later |

## Alternatives considered

| Option | Pros | Cons / why not proposed |
|---|---|---|
| Keep Pi-local dumps plus the laptop mirror only | Nothing new | Everything is in one building. Not scheduled, not versioned, never drilled. Fails Phase 8 outright |
| rclone + age, compressed dumps | Two common tools | No deduplication (140 MB a night, every night), hand-written retention, two binaries to pin |
| Backblaze B2 | Cheap ($6/TB), mature | A new account; R2 is in the account that already holds the domain |
| Postgres WAL archiving (pgBackRest, WAL-G) | Point-in-time recovery | Machinery for a database written only by swaps and monthly runs. A nightly logical dump already gives "yesterday" |
| Drill B by reflashing the eMMC | It literally wipes the Pi | Destroys the only working host if the drill fails. A microSD gives the same test with a fallback |
| QEMU arm64 builds in CI | No new runner type | Slow, and Chromium under emulation is fragile. Native arm runners are free for a public repo |
| Keep `dev_server.py` | Works; no new component | `http.server` isn't meant for production; no caching; no limiter (D4 Q15 keeps it as option b) |
| Cloudflare Pages for the static files | Free CDN | Splits the origin or needs Workers routing; another deploy surface; ADR-0019 already rejected two origins |
| Prometheus + node-exporter + Alertmanager now | ROADMAP lists them | Three services and dashboards before anyone has asked a question they answer; D5 covers the paging cases |
| Move to a hosted VPS now | Datacenter power and network | The pipeline stays on the Pi anyway (IP, RAM), so it means two hosts for ~1,300 requests a day (D6) |

## Consequences

**Easier:**

- A lost Pi is recoverable from data outside the building, with a measured time.
- A failed monthly run, a full disk or a dead site reaches the owner without anyone looking.
- arm64 breaks show up in the PR, not on the Pi.
- Static files can be cached.
- The API gets a real rate limit and a documented 429.

**Harder / accepted costs:**

- Two external dependencies: an R2 bucket and a healthchecks.io account.
- Three secrets on the Pi, plus one (the restic password) that must also live off it. Losing
  both copies of the restic password makes every backup unreadable.
- More units on the Pi: backup, watch and nginx.
- A sixth CI job.
- Drill B costs about 30–40 minutes of public downtime once a year.
- The Pi stays a residential single point of failure. The exit triggers define when that stops
  being acceptable.

**Unchanged:** the data model, the pipeline, the gate, the monthly timer and its 2026-12-10
firing, and the API's endpoints. The only API change is one `ErrorCode` value, from D4.

## Doc drift found while writing this (not fixed here)

- ROADMAP §4.2 and README call the Pi "staging"; it is production in practice (D6).
- README's ADR index says ADR-0030 Amendment 1's timer is "not yet installed". On the Pi it is
  enabled, next firing 2026-12-10 18:00 UTC.
- README "Staging (Pi)" says the code is `7070251` and data as of swap 5. The Pi runs `9c1b08c`,
  swapped 2026-11-27 (course labels).
- ADR-0019 Amendment 1's "Open" line is still true: Always Use HTTPS and an edge rate limit are not
  set (F4).

## Appendix: Cloudflare dashboard settings (owner actions)

These are the owner's to change, and none needs a code change. Dashboard labels move, so the
path is given with the setting's name.

1. **SSL/TLS → Overview:** leave the encryption mode as it is (not "Off"). With a tunnel, the
   origin leg is the tunnel itself.
2. **SSL/TLS → Edge Certificates → Always Use HTTPS: On.** Check: `curl -sI
   http://firsthelios.com/` returns `301` with `Location: https://…`.
3. **SSL/TLS → Edge Certificates → Minimum TLS Version: TLS 1.2.**
4. **SSL/TLS → Edge Certificates → HTTP Strict Transport Security (HSTS) → Enable,** only after
   step 2 works:
   - Max-Age: **1 month** to start; raise it to 6–12 months after 2–4 weeks without problems;
   - Apply HSTS policy to subdomains (includeSubDomains): **On**. Only the apex and `www` exist,
     both behind Cloudflare;
   - Preload: **Off**. Hard to undo; reconsider after a year at 12 months;
   - No-Sniff header: **On**.
   - Check: `curl -sI https://firsthelios.com/` shows `strict-transport-security: max-age=2592000;
     includeSubDomains`.
5. **Security → WAF → Rate limiting rules → Create rule** (the free plan allows one rule, a 10 s
   counting period and a 10 s mitigation timeout):
   - Name: `api-per-ip`;
   - When incoming requests match: **URI Path** *starts with* `/v1/`. If "starts with" isn't
     offered on the plan, use *wildcard* `/v1/*`, or *contains* `/v1/`;
   - Characteristics: **IP** (the free plan's only one);
   - Rate: **100 requests per 10 seconds**. The client's heaviest pattern is a list that loads
     its remaining pages by itself: one page at a time, 150 ms after the previous one answers,
     until a browsing-memory cap (frontend `js/pagination.js`). That is at most about 4–6
     requests a second per list, or 40–60 per 10 s, and two lists can load at once. So 100 leaves
     headroom for one person, and `swap.sh`'s three public checks and D5's watcher (three
     requests every 5 minutes) are far below it. A scraper looping on the API is not;
   - Action: **Block**, duration **10 seconds**. Not a challenge: the client's `fetch` calls
     can't solve one. Keep the default response unless the plan offers a custom JSON body, in
     which case use `{"detail":"rate limited","code":"rate_limited","trace_id":null}`.
   - The nginx limiter (D4) is the finer, per-route second line.
6. **Security → Settings → Bot Fight Mode: leave Off.** It challenges non-browser clients,
   including `swap.sh`'s and the watcher's `curl` checks.
7. **Notifications → Add → Tunnel Health Alert** (optional, D5): email on a tunnel status change.

## References

- ROADMAP Phase 8, §4.2, §7 item 6 (R116); [2026-09-22 review](../reviews/2026-09-22-full-codebase-review.md) R116.
- `infra/Dockerfile`, `infra/docker-compose.yml`, `infra/docker-compose.pi.yml`, `.dockerignore`,
  `.github/workflows/ci.yml` (job `docker`), `infra/pipeline-host/` (`swap.sh`, `restore.sh`,
  `dump.sh`, `lib.sh`, `mirror-laptop.sh`, the loop unit and timer), `apps/api/schemas.py`
  (`ErrorCode`), frontend `dev_server.py`.
- [restic](https://restic.net/) (encryption, `--stdin-from-command`, compression in repository v2).
- [Cloudflare R2 pricing](https://developers.cloudflare.com/r2/pricing/): 10 GB-month, 1 M
  Class A and 10 M Class B operations free; Standard $0.015/GB-month; free egress.
- [Hetzner price adjustment](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/)
  (CAX11/21/31: 5.99/10.49/20.99 from 2026-06-15);
  [Northflank](https://northflank.com/blog/hetzner-cloud-server-price-increases) and
  [bitdoze](https://www.bitdoze.com/de/hetzner-cloud-guenstige-tarife/) (third-party; the
  availability reports).
- [healthchecks.io pricing](https://healthchecks.io/pricing) (Hobbyist: 20 checks, free).
- [Cloudflare rate limiting rules](https://developers.cloudflare.com/waf/rate-limiting-rules/)
  (free: one rule, 10 s period, 10 s timeout);
  [HSTS](https://developers.cloudflare.com/ssl/edge-certificates/additional-options/http-strict-transport-security/);
  [Always Use HTTPS](https://developers.cloudflare.com/ssl/edge-certificates/additional-options/always-use-https/);
  [Tunnel notifications](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/monitor-tunnels/notifications/).
- [GitHub arm64 runners for public repositories, GA](https://github.blog/changelog/2025-08-07-arm64-hosted-runners-for-public-repositories-are-now-generally-available/).
- Python [`http.server`](https://docs.python.org/3/library/http.server.html) security note.
