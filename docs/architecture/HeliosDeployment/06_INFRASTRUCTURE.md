# 6. Infrastructure & Operations

> **Audience:** Anyone deploying, monitoring, or troubleshooting First Helios.
>
> **Full operations reference:** [RUNBOOK.md](../../RUNBOOK.md) at project root.

---

## Production Host

| Component | Detail |
|-----------|--------|
| **Hardware** | Orange Pi 5 Plus — ARM64/RK3588, 32GB RAM |
| **OS** | Ubuntu 22.04 (Jammy), headless (`multi-user.target`) |
| **LAN address** | `192.168.1.191` |
| **CPU governor** | `performance` (persisted via `cpugov` systemd service) |

---

## Web Stack

```
Browser / Extension
       │
    nginx (:80)
       │
  Gunicorn (:8765, 9 workers, 2 threads)
       │
  Flask — server.py
       │
  PostgreSQL 14 (helios:helios@localhost:5432/helios)
```

| Layer | Config |
|-------|--------|
| **nginx** | Reverse proxy, port 80 → 8765 |
| **Gunicorn** | 9 workers, 2 threads per worker |
| **Flask** | `server.py`, port 8765, 1MB POST body cap, CORS enabled |
| **Database** | `DATABASE_URL=postgresql+psycopg://helios:helios@localhost:5432/helios` |

---

## Systemd Services

All start on boot and are managed via `systemctl`.

| Service | Purpose | Entry Point |
|---------|---------|-------------|
| `helios` | Web server | Gunicorn → `server.py` |
| `helios-collector` | Scheduler (data collection) | `collector_main.py` |
| `helios-update.timer` | Auto-deploy (polls GitHub every 5 min) | `dev/update.sh` |
| `nginx` | Reverse proxy | System nginx |
| `postgresql` | Database | System PostgreSQL 14 |
| `cpugov` | CPU governor → performance | One-shot on boot |

### Common Commands

```bash
# Check status
sudo systemctl status helios helios-collector nginx

# Restart web server
sudo systemctl restart helios

# Restart collector/scheduler
sudo systemctl restart helios-collector

# View logs
journalctl -u helios -f
journalctl -u helios-collector -f
```

---

## Auto-Deploy

The OrangePi pulls from `git@github.com:4Fortune8/First-Helios.git` using a deploy key at `~/.ssh/github_deploy`. Every 5 minutes, `helios-update.timer` fires `dev/update.sh`:

1. Check for new commits on remote
2. `git pull`
3. `pip install -r requirements.txt` (if requirements changed)
4. Restart `helios` and `helios-collector` services (if code changed)

**This means:** push to `main` and it deploys within 5 minutes.

---

## Scheduler

The scheduler runs as a separate process (`helios-collector` service) via `collector_main.py`. It uses APScheduler's `BackgroundScheduler` with cron and interval triggers.

### Configuration
- **Job definitions:** `config/scheduler.yaml` — enable/disable, cron schedule per job
- **Job registration:** `core/scheduler.py` — reads YAML, registers jobs with APScheduler
- **Rate limits:** `core/rate_manager.py` — enforces daily API budgets per source

### Job Categories

| Category | Jobs | Schedule |
|----------|------|----------|
| **BLS / Labor** | qcew, jolts, oews, laus, cbp | Monthly cron |
| **Job Boards** | jobspy, serpapi, jobicy, theirstack, workday, usajobs, activejobs, juju | Varies (6h–weekly) |
| **Events** | Ticketmaster, Eventbrite, Meetup, Do512, Austin City, Visit Austin | Auto-discovered via plugin registry |
| **Employers** | Overture Maps, AllThePlaces, OSM | Weekly (Sunday) |
| **Maintenance** | posting_expiry, posting_purge, event_expiry, event_purge, log_purge, snapshot_purge | Daily or monthly cron |
| **SpiritPool** | burn_pool_cleanup | Daily at 02:45 UTC |

### Checking Scheduler Status

```bash
# Via API
curl http://localhost:8765/api/scheduler/status

# Via system health dashboard
python scripts/system_health_dashboard.py
```

---

## Rate Management

External API calls are governed by `core/rate_manager.py`. Every source has:

- **`api_sources`** table entry — `daily_limit`, `auth_type`, `min_delay`
- **`rate_budgets`** table — daily request count vs limit
- **`api_request_log`** table — per-request audit (latency, status, errors)

### Quick Status Check

```sql
-- Rate limit usage today
SELECT source_key, requests_used, daily_limit,
       ROUND(100.0 * requests_used / daily_limit, 1) as pct
FROM rate_budgets
WHERE date = date('now')
ORDER BY pct DESC;
```

---

## Database Operations

### Migrations (Alembic)

```bash
# Check current revision
alembic current

# Generate new migration
alembic revision --autogenerate -m "description"

# Apply all pending migrations
alembic upgrade head

# Rollback one step
alembic downgrade -1
```

Migration chain: `b6326fcb7067` → `28fbdf2816df` → `ed6b655457e5` → `ae445d02acad` (latest — SpiritPool tables)

### Metadata Population

```bash
# Register all tables, columns, and lineage (idempotent)
python scripts/one_shot/populate_metadata.py
```

### System Health

```bash
# Full health check — freshness SLAs, stale tables, job failures
python scripts/system_health_dashboard.py

# Detailed mode
python scripts/system_health_dashboard.py --detailed
```

---

## Monitoring Quick Reference

| I want to check... | Command |
|---------------------|---------|
| Service status | `sudo systemctl status helios helios-collector` |
| Web server logs | `journalctl -u helios -f` |
| Collector logs | `journalctl -u helios-collector -f` |
| Table freshness SLAs | `python scripts/system_health_dashboard.py` |
| Undocumented tables | `sqlite3 data/tracker.db "SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN (SELECT table_name FROM meta_table_catalog);"` |
| Recent job failures | `sqlite3 data/tracker.db "SELECT job_id, status, error_message FROM meta_job_runs WHERE status='failed' ORDER BY run_timestamp DESC LIMIT 10;"` |
| Rate limit usage | See SQL query above |
| Registered routes | `python -c "from server import app; print([r.rule for r in app.url_map.iter_rules()])"` |

---

## Local Development

### Setup

```bash
cd First-Helios
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Running Locally

Without `DATABASE_URL`, the app falls back to SQLite at `data/tracker.db`.

```bash
# Start web server
python server.py

# Start collector/scheduler
python collector_main.py
```

### Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `DATABASE_URL` | PostgreSQL connection string | SQLite fallback |
| `SERPAPI_KEY` | SerpAPI job search | None (disabled) |
| `TICKETMASTER_KEY` | Ticketmaster event search | None (disabled) |
| `EVENTBRITE_TOKEN` | Eventbrite event search | None (disabled) |

Full list in `.env` on the production host.

---

## Cross-Repo Infrastructure

| Repo | Scope |
|------|-------|
| **First-Helios** (this repo) | Backend API, pipeline, scoring |
| **First-Helios_Frontend** | Dashboard UI (plain HTML/CSS/JS) |
| **First-Helios_Orangepi_Host** | systemd units, nginx config, deploy scripts, SSH keys |

The host repo manages everything *around* the Flask app — systemd, nginx, deploy key, update timer. This repo manages the app itself.
