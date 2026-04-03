# Missed Schedule Recovery Guide

When the machine is off during a scheduled window, APScheduler does not catch up
automatically — it simply skips the missed run. This guide explains how to identify
what was missed and manually trigger each job.

---

## 1. Determine What Was Missed

Cross the current date/time against the schedule table below. Any job whose window
passed while the machine was off needs a manual run.

| Job ID | Normal Schedule | Skip Guard |
|--------|----------------|------------|
| `posting_expiry` | Daily 3:00 AM | — |
| `jobspy` | Daily 4:00 AM | — |
| `austin_gov` | Daily 5:30 AM | — |
| `usajobs` | Daily 6:00 AM | — |
| `serpapi_jobs` | Daily 7:00 AM | — |
| `rapidapi_activejobs` | Daily 8:00 AM | — |
| `juju` | Daily 8:30 AM | — |
| `theirstack` | Daily 9:00 AM | — |
| `jobicy` | Every 1 hour | — |
| `reddit` | Every 6 hours | — |
| `google_maps` | Monday 5:00 AM | — |
| `bls` | Monday 6:00 AM | — |
| `cbp` | Monday 8:00 AM | **April only** |
| `warn_tx` | Tuesday 7:00 AM | — |
| `nlrb` | Wednesday 7:00 AM | — |
| `atp_starbucks_austin` | Sunday 2:00 AM | — |
| `overture_starbucks_austin` | Sunday 2:15 AM | — |
| `osm_starbucks_austin` | Sunday 2:30 AM | — |
| `overture_local_austin` | Sunday 3:00 AM | — |
| `posting_purge` | Sunday 3:30 AM | — |
| `event_expiry` | Daily 3:30 AM | — |
| `event_purge` | Sunday 4:00 AM | — |
| `baseline_recompute` | Sunday 4:00 AM | — |
| `log_purge` | 1st of month 2:00 AM | — |
| `snapshot_purge` | 1st of month 2:30 AM | — |
| `qcew` | 1st of month 7:00 AM | **Jan/Apr/Jul/Oct only** |

> **Skip-guarded jobs:** Even if you run them manually, they will no-op silently
> unless the current date satisfies their guard. You can safely skip them unless
> you are in the guarded window.

---

## 2. Run Missed Jobs Manually

All scheduler job functions can be called directly from a Python shell inside the
project root. Start the shell with the environment loaded:

```bash
cd /home/fortune/CodeProjects/First-Helios
source .env   # or: export $(cat .env | xargs)
python
```

Then import and call the private scheduler functions directly:

```python
# One-time import for all jobs
import sys
sys.path.insert(0, ".")

# ── Daily job postings ────────────────────────────────────────────────────────
from core.scheduler import _run_posting_expiry; _run_posting_expiry()
from core.scheduler import _run_jobspy;         _run_jobspy()
from core.scheduler import _run_austin_gov;     _run_austin_gov()
from core.scheduler import _run_usajobs;        _run_usajobs()
from core.scheduler import _run_serpapi_jobs;   _run_serpapi_jobs()
from core.scheduler import _run_activejobs;     _run_activejobs()
from core.scheduler import _run_juju;           _run_juju()
from core.scheduler import _run_theirstack;     _run_theirstack()
from core.scheduler import _run_jobicy;         _run_jobicy()
from core.scheduler import _run_reddit;         _run_reddit()

# ── Weekly labor/regulatory (run only if their day was missed) ────────────────
from core.scheduler import _run_reviews;        _run_reviews()    # Monday
from core.scheduler import _run_bls;            _run_bls()        # Monday
from core.scheduler import _run_warn;           _run_warn()       # Tuesday
from core.scheduler import _run_nlrb;           _run_nlrb()       # Wednesday

# ── Sunday employer discovery ─────────────────────────────────────────────────
from core.scheduler import _run_alltheplaces;   _run_alltheplaces()
from core.scheduler import _run_overture_chain; _run_overture_chain()
from core.scheduler import _run_osm;            _run_osm()
from core.scheduler import _run_overture_local; _run_overture_local()
from core.scheduler import _run_posting_purge;  _run_posting_purge()
from core.scheduler import _run_baseline_recompute; _run_baseline_recompute()

# ── Events maintenance ────────────────────────────────────────────────────────
from core.scheduler import _run_event_expiry;   _run_event_expiry()   # Daily
from core.scheduler import _run_event_purge;    _run_event_purge()    # Sunday

# ── Data hygiene ──────────────────────────────────────────────────────────────
from core.scheduler import _run_log_purge;      _run_log_purge()      # 1st of month
from core.scheduler import _run_snapshot_purge; _run_snapshot_purge() # 1st of month

# ── Monthly / quarterly (skip-guarded — only effective in right month) ────────
from core.scheduler import _run_qcew;           _run_qcew()   # Jan/Apr/Jul/Oct
from core.scheduler import _run_cbp;            _run_cbp()    # April only
```

Each function logs its own output. Errors are caught internally and logged —
a function returning `None` without an exception means it completed (or was
skip-guarded).

---

## 3. Verify Runs Landed in the DB

After running, spot-check the metadata tables to confirm the jobs registered:

```sql
-- Recent job runs
SELECT job_id, job_type, status, started_at, rows_written
FROM meta_job_runs
ORDER BY started_at DESC
LIMIT 30;

-- Check for errors
SELECT job_id, status, error_message, started_at
FROM meta_job_runs
WHERE status = 'error'
ORDER BY started_at DESC
LIMIT 10;
```

Or use the health dashboard:

```bash
python scripts/system_health_dashboard.py
```

---

## 4. Recommended Recovery Order (Machine Off Sunday Night / Monday Morning)

If the machine was off over a Sunday-into-Monday window, run in this order to
respect data dependencies (employer discovery → expiry → scoring):

1. **Employer discovery** — `_run_alltheplaces`, `_run_overture_chain`, `_run_osm`, `_run_overture_local`
2. **Posting expiry + purge** — `_run_posting_expiry`, `_run_posting_purge`
3. **Job boards** — `_run_jobspy`, `_run_austin_gov`, `_run_usajobs`, `_run_serpapi_jobs`, `_run_activejobs`, `_run_juju`, `_run_theirstack`, `_run_jobicy`, `_run_reddit`
4. **Labor/regulatory** — `_run_bls`, `_run_reviews`
5. **Baseline recompute** — `_run_baseline_recompute` (depends on BLS + QCEW being fresh)

---

## 5. Prevent Future Missed Runs

The scheduler runs **inside the Flask process** (`core/scheduler.py` via APScheduler
`BackgroundScheduler`). It only runs while the server is up. Options to make it
more resilient:

- **System cron** — Add `@reboot` entries in `crontab -e` to restart the Flask
  server on boot, so it resumes scheduling as soon as the machine powers on.
- **systemd service** — Create a service unit so the server auto-restarts after
  crashes or reboots.
- **Detach scheduler** — Move APScheduler jobs to a separate long-running process
  so they are independent of the web server lifecycle.

None of these are currently implemented. The manual recovery steps above are the
expected path until one of these is in place.
