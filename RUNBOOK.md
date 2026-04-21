# First-Helios Runbook

Operations reference for the First-Helios project. Covers the Orange Pi 5 Plus production host, local dev workflow, scheduler jobs, and troubleshooting.

---

## Infrastructure Overview

| Component | Details |
|-----------|---------|
| Production host | Orange Pi 5 Plus at 192.168.1.191 (Ubuntu Jammy, ARM64 / RK3588) |
| Public URL | http://192.168.1.191 |
| Web stack | nginx (port 80) → Gunicorn (port 8765), 9 workers + 2 threads |
| Flask entry point | `server.py` |
| Database | PostgreSQL 14 — user: helios, db: helios, host: localhost:5432 |
| DATABASE_URL | `postgresql+psycopg://helios:helios@localhost:5432/helios` |
| Boot mode | Headless (multi-user.target, no display manager) |
| CPU governor | performance (persisted via `cpugov` systemd service) |

---

## Systemd Services

All services are enabled and start on boot.

| Service | Purpose |
|---------|---------|
| `helios` | Gunicorn web server. WorkingDirectory: `~/First-Helios`, EnvironmentFile: `.env` |
| `helios-collector` | Standalone APScheduler process (`collector_main.py`) |
| `helios-update.timer` | Polls GitHub every 5 min; git pull + pip install + restart if changed |
| `nginx` | Reverse proxy on port 80 |
| `postgresql` | Database |
| `cpugov` | Sets CPU governor to performance |

### Common service commands

```bash
# Status
sudo systemctl status helios helios-collector nginx

# Restart web server
sudo systemctl restart helios

# Restart collector
sudo systemctl restart helios-collector

# Stop / start
sudo systemctl stop helios
sudo systemctl start helios
```

---

## Auto-Update

The OPi pulls from `git@github.com:4Fortune8/First-Helios.git` using a deploy key at `~/.ssh/github_deploy`. Every 5 minutes the timer fires `dev/update.sh`, which:

1. Checks for new commits on the remote
2. Runs `git pull`
3. Runs `pip install -r requirements.txt` if `requirements.txt` changed
4. Restarts the `helios` **and** `helios-collector` services if any files changed

> **Important:** Both services must be restarted on deploy. If only `helios` is restarted, the collector keeps running stale code (or stays dead if it crashed).

Update logs: `/var/log/helios-update.log`

```bash
tail -f /var/log/helios-update.log
```

To deploy a change: push to GitHub and wait up to 5 minutes, or `sudo systemctl restart helios` to pick up immediately after a confirmed pull.

### Food Price Index rollout

The Price Index feature needs three deployment pieces to be live on the Orange Pi:

1. Backend migration + API deploy from `First-Helios`
2. Collector restart so live scrapes persist menu graph rows
3. Frontend deploy from `First-Helios_Frontend`

The Orange Pi host updater should restart both `helios` and `helios-collector` on backend changes. That collector restart is required because menu persistence is wired into the website scraper runtime, not only the API server.

One-time rollout after the backend code lands:

```bash
ssh orangepi@192.168.1.191
cd ~/First-Helios

# Apply the new menu graph tables.
.venv/bin/alembic upgrade head

# Estimate replay volume before writing.
.venv/bin/python scripts/backfill_menu_tables.py --dry-run

# Backfill from cached website scrape bundles.
.venv/bin/python scripts/backfill_menu_tables.py
```

If the dry-run reports very few bundles with shapes, most cached bundles predate menu persistence. In that case, run a fresh website scraper pass after deploy so live scrapes populate the new menu tables:

```bash
cd ~/First-Helios
PYTHONPATH=. .venv/bin/python collectors/meal_deals/website_scraper.py --all --skip-checked-days 0 --chunk-size 25
```

Post-deploy checks:

```bash
curl -k "https://127.0.0.1/api/price-index?region=austin_tx&limit=5"
curl -k "https://127.0.0.1/api/price-index/facets?region=austin_tx"
sudo journalctl -u helios -n 50
sudo journalctl -u helios-collector -n 50
sudo journalctl -u helios-frontend -n 50
```

---

## Collector Entry Point

`collector_main.py` is the standalone scheduler process used by the `helios-collector` systemd service.

```bash
# Start persistent scheduler (used by systemd)
python collector_main.py

# Fire all daily jobs sequentially (good for first-run or catch-up)
python collector_main.py --run-now

# Fire one job by ID
python collector_main.py --job <job_id>

# List all registered job IDs (* = included in --run-now)
python collector_main.py --list-jobs
```

### Manual test pull (SSH into OPi first)

```bash
ssh orangepi@192.168.1.191
cd ~/First-Helios && source .venv/bin/activate

# Test a single job board
python collector_main.py --job theirstack
python collector_main.py --job serpapi_jobs
python collector_main.py --job jobicy
python collector_main.py --job activejobs
python collector_main.py --job jobspy
python collector_main.py --job usajobs
python collector_main.py --job austin_gov

# Fire all job board jobs at once
python collector_main.py --run-now
```

Expected output per job: `✓ <job_id> finished in Xs` with a signal count in the log line above it.

**Gate notes — these will skip without error:**
- `jobicy` — hourly gate (skips if run < 60 min after last run; clear with `rm data/jobicy_cache.json`)
- `activejobs` — 24-hour gate (clear stale cache with `rm data/rapidapi_activejobs_cache.json`)
- `serpapi_jobs` — no gate, rotates industry on each run
- `theirstack` — no gate, but API times out occasionally; retry is safe

**If a job returns 0 signals unexpectedly:**
```bash
# Check rate budget
curl http://localhost:8765/api/rate-budget | python3 -m json.tool

# Tail scheduler logs
sudo journalctl -u helios-collector -n 50
```

---

## Scheduler Jobs

Jobs are defined in `core/scheduler.py` and configured in `config/scheduler.yaml`.\nEvent collector jobs are auto-discovered from `collectors/events/`.

To disable a job without removing it: set `enabled: false` in `config/scheduler.yaml`.

Check status via API: `GET /api/scheduler/status`

### Job Postings (daily)

| Job ID | Schedule | Description |
|--------|----------|-------------|
| `jobspy` | Cron 4:00 AM | JobSpy — Indeed/Glassdoor chain + wage modes; recomputes scores |
| `reddit` | Interval 6h | Reddit sentiment; recomputes scores |
| `austin_gov` | Cron 5:30 AM | City of Austin Workday portal |
| `usajobs` | Cron 6:00 AM | USAJobs federal listings |
| `serpapi_jobs` | Cron 7:00 AM | SerpAPI Google Jobs; rotates through 20 industry keys |
| `rapidapi_activejobs` | Cron 8:00 AM | Active Jobs DB via RapidAPI |
| `juju` | Cron 8:30 AM | Juju XML search API |
| `theirstack` | Cron 9:00 AM | TheirStack jobs + company intelligence |
| `jobicy` | Interval 1h | Jobicy remote jobs; rotates through industry tags |

### Labor Market / Regulatory (weekly/monthly)

| Job ID | Schedule | Description |
|--------|----------|-------------|
| `bls` | Cron Monday 6:00 AM | BLS bulk fetch (v2 if BLS_API_KEY set, else v1 fallback) |
| `qcew` | Cron 1st of month 7:00 AM | QCEW; **skips unless month in {1, 4, 7, 10}** |
| `cbp` | Cron Monday 8:00 AM | Census CBP; **skips unless month = 4** |
| `nlrb` | Cron Wednesday 7:00 AM | NLRB labor cases; recomputes scores |
| `warn_tx` | Cron Tuesday 7:00 AM | Texas WARN Act filings |
| `baseline_recompute` | Cron Sunday 4:00 AM | Recomputes labor market baselines |

### Store / Employer Discovery (Sunday stagger)

| Job ID | Schedule | Description |
|--------|----------|-------------|
| `atp_starbucks_austin` | Sunday 2:00 AM | AllThePlaces — Starbucks, Dutch Bros, McDonald's |
| `overture_starbucks_austin` | Sunday 2:15 AM | Overture chain cross-validation |
| `osm_starbucks_austin` | Sunday 2:30 AM | OSM Overpass fallback |
| `overture_local_austin` | Sunday 3:00 AM | Overture local employer discovery |

### Maintenance

| Job ID | Schedule | Description |
|--------|----------|-------------|
| `google_maps` | Cron Monday 5:00 AM | Google Maps reviews; recomputes scores |
| `posting_expiry` | Cron daily 3:00 AM | Marks `is_active=False` on expired postings |
| `posting_purge` | Cron Sunday 3:30 AM | Hard-deletes inactive postings older than 90 days |
| `event_expiry` | Cron daily 3:30 AM | Marks `is_active=False` on expired events |
| `event_purge` | Cron Sunday 4:00 AM | Hard-deletes inactive events older than 90 days |
| `log_purge` | Cron 1st of month 2:00 AM | Purges API request logs older than 90 days |
| `snapshot_purge` | Cron 1st of month 2:30 AM | Purges snapshots older than 180 days |

### Events Hub (auto-discovered)

Event collectors are auto-discovered from `collectors/events/` via the `@event_collector` decorator.
Schedules are declared in each collector file and registered at startup. See `config/event_sources.yaml` for the full catalog.

| Collector | Schedule | Description |
|-----------|----------|-------------|
| `ticketmaster` | Every 6h | Ticketmaster Discovery API |
| `eventbrite` | Every 6h | Eventbrite API |
| `meetup` | Every 4h | Meetup GraphQL API |
| `do512` | Every 6h | Do512.com local events scraper |
| `austin_city` | Daily 5:00 AM | City of Austin Socrata data |
| `austintexas_org` | Daily 6:00 AM | Visit Austin tourism calendar |

---

## API Keys (.env on OPi)

| Key | Status |
|-----|--------|
| `BLS_API_KEY` | Set |
| `CBP_API_KEY` | Set |
| `SERPAPI_KEY` | Set |
| `RAPIDAPI_KEY` | Set |
| `THEIRSTACK_API_KEY` | Set |
| `REDDIT_CLIENT_ID` | Not set — reddit runs in public/degraded mode |
| `GOOGLE_MAPS_API_KEY` | Not set — google_maps job skipped |
| `JUJU_PARTNER_ID` | Not set — juju job skipped |

---

## Monitoring

```bash
# Web server logs
sudo journalctl -u helios -f

# Scheduler / collector logs
sudo journalctl -u helios-collector -f

# nginx request log
tail -f /var/log/helios-access.log

# Auto-update log
tail -f /var/log/helios-update.log

# All services at once
sudo systemctl status helios helios-collector nginx
```

### DB row counts (as of 2026-03-31)

| Table | Rows |
|-------|------|
| `mob_transition` | 256,831 |
| `ref_texaswages` | 86,528 |
| `local_employers` | 45,618 |
| `ref_employer_name_index` | 37,128 |
| `brand_groups` | 36,563 |
| `revelio_employment` | 23,188 |
| `revelio_hiring` | 23,188 |
| `ref_occupation_aliases` | 18,981 |
| `scores` | 16,363 |
| **DB total** | **249 MB** |

```bash
# DB size
PGPASSWORD=helios psql -U helios -h localhost -d helios -c "SELECT pg_size_pretty(pg_database_size('helios'));"

# Row count
PGPASSWORD=helios psql -U helios -h localhost -d helios -c "SELECT COUNT(*) FROM local_employers;"
```

---

## Local Dev Workflow

```bash
# 1. Pull live data from OPi (~30 seconds)
bash dev/sync_from_opi.sh
bash dev/sync_from_opi.sh --dry-run   # compare row counts without syncing

# 2. Activate venv
source .venv/bin/activate

# 3. Run server locally
python server.py                       # http://localhost:8765

# 4. Push changes
git push origin main
# OPi auto-pulls within 5 minutes
```

**Python:** 3.12 | **Venv:** `.venv/` | **Deps:** `pip install -r requirements.txt`

---

## Fresh Setup (new machine or OPi re-provision)

```bash
# On the OPi — run once after cloning
bash dev/opi5_setup.sh

# Restore database from a local dump
PGPASSWORD=helios pg_dump -U helios -h localhost -d helios > helios_backup.sql
scp helios_backup.sql orangepi@192.168.1.191:~/
ssh orangepi@192.168.1.191 "PGPASSWORD=helios psql -U helios -h localhost -d helios < ~/helios_backup.sql"
```

---

## Troubleshooting

### Web server not responding

```bash
sudo systemctl status helios nginx
sudo journalctl -u helios -n 50
```

Check Gunicorn is bound on port 8765 and nginx is proxying. If the `helios` service crashed, the journal will have the Python traceback.

### Collector jobs not running

```bash
sudo systemctl status helios-collector
sudo journalctl -u helios-collector -n 100
```

If stopped unexpectedly, check for import errors or a missing `.env`. Use `python collector_main.py --list-jobs` to verify registration and `python collector_main.py --run-now` to test outside systemd.

### Auto-update not pulling

```bash
tail -50 /var/log/helios-update.log
```

Common causes: SSH key permissions on `~/.ssh/github_deploy`, network issue, or merge conflict. The deploy key must be added to GitHub at `https://github.com/4Fortune8/First-Helios/settings/keys`.

### Database connection errors

```bash
sudo systemctl status postgresql
PGPASSWORD=helios psql -U helios -h localhost -d helios -c "SELECT 1;"
```

If PostgreSQL restarted after a crash, `helios` and `helios-collector` may need a restart too.

### A collector job silently skipping

Some jobs have built-in schedule guards:
- `qcew` — only runs in months 1, 4, 7, 10
- `cbp` — only runs in month 4
- `google_maps`, `juju`, `reddit` — require API keys not currently set

Run `python collector_main.py --job <job_id>` to fire directly and see output.

### Disk space

```bash
df -h ~
```

If disk fills up, run `python collector_main.py --job posting_purge` to manually trigger the 90-day inactive posting cleanup.
