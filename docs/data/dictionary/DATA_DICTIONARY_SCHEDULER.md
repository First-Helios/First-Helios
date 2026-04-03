# Data Dictionary — Scheduler

Reference for reading, modifying, and debugging the APScheduler configuration in First-Helios.

---

## How the scheduler works

The scheduler is a standalone process (`collector_main.py`) separate from the Flask web server. It uses APScheduler with job definitions in `core/scheduler.py` and tunable settings in `config/scheduler.yaml`.

**Startup:** `systemd` starts `helios-collector` which runs `python collector_main.py`. Jobs register at startup and fire on their schedule. The process must stay alive — if it dies, no jobs run until it is restarted.

**Config layering:**
1. `core/scheduler.py` defines each job function and its hardcoded defaults
2. `config/scheduler.yaml` overrides schedule, description, and enabled flag
3. YAML keys must exactly match the job ID defined in `scheduler.py`

---

## config/scheduler.yaml — Field Reference

Each top-level key is a job ID.

```yaml
<job_id>:
  enabled: true | false
  description: "Human-readable description"
  trigger: cron | interval
  cron:                      # used when trigger: cron
    day_of_week: mon         # mon tue wed thu fri sat sun (omit = every day)
    day: 1                   # day of month 1-31 (omit = every day)
    hour: 4                  # 0-23 (required)
    minute: 0                # 0-59 (required)
  interval_hours: 3          # used when trigger: interval
```

**`enabled`** — `false` stops the job from running without removing it. Use this for temporarily disabling a job, or for jobs waiting on an API key.

**`trigger: cron`** — fires once at the given wall-clock time. All times are server-local (US Central, Austin). If `day_of_week` is omitted the job fires every day. If `day` is set, fires on that calendar day each month.

**`trigger: interval`** — fires every `interval_hours` hours from the time the scheduler process started. Not synchronized to wall-clock — can drift on restart.

**`description`** — informational only. Shown in `python collector_main.py --list-jobs` output.

---

## Job Registry

### Job Postings

| Job ID | Trigger | Schedule | Source Key | Budget |
|---|---|---|---|---|
| `jobspy` | cron | Daily 4:00 AM | `jobspy` | No key — rate-limited by sites |
| `reddit` | interval | Every 6h | `reddit` | No key — public |
| `austin_gov` | cron | Daily 5:30 AM | `workday_gov` | No key — public scrape |
| `usajobs` | cron | Daily 6:00 AM | `usajobs` | `USAJOBS_API_KEY` required |
| `serpapi_jobs` | interval | Every 3h | `serpapi_google_jobs` | `SERPAPI_KEY` — 250/month |
| `theirstack` | interval | Every 4h | `theirstack` | `THEIRSTACK_API_KEY` — ~200/month |

### Labor Market / Regulatory

| Job ID | Trigger | Schedule | Source Key | Skip Guard |
|---|---|---|---|---|
| `bls` | cron | Monday 6:00 AM | `bls` | None |
| `qcew` | cron | 1st of month 7:00 AM | `qcew` | **Months 1, 4, 7, 10 only** |
| `cbp` | cron | Monday 8:00 AM | `cbp` | **Month 4 only** |
| `nlrb` | cron | Wednesday 7:00 AM | `nlrb` | None |
| `warn_tx` | cron | Tuesday 7:00 AM | `warn_tx` | None |
| `baseline_recompute` | cron | Sunday 4:00 AM | — | None |

### Store / Employer Discovery

| Job ID | Trigger | Schedule | Source | Notes |
|---|---|---|---|---|
| `atp_starbucks_austin` | cron | Sunday 2:00 AM | AllThePlaces | Starbucks, Dutch Bros, McDonald's GeoJSON |
| `overture_starbucks_austin` | cron | Sunday 2:15 AM | Overture Maps | Chain cross-validation |
| `osm_starbucks_austin` | cron | Sunday 2:30 AM | OSM Overpass | Fallback if Overture misses |
| `overture_local_austin` | cron | Sunday 3:00 AM | Overture Maps | All Austin-area POIs |

> Sunday employer jobs are staggered 15 min apart to avoid concurrent DB writes.

### Maintenance

| Job ID | Trigger | Schedule | What it does |
|---|---|---|---|
| `google_maps` | cron | Monday 5:00 AM | Scrapes reviews for tracked chain locations |
| `posting_expiry` | cron | Daily 3:00 AM | Sets `is_active=False` on postings past `expires_at` |
| `posting_purge` | cron | Sunday 3:30 AM | Hard-deletes inactive postings older than 90 days |

---

## Skip Guards

Some jobs have built-in skip logic that fires *before* any HTTP request. These are not scheduler settings — they are coded inside the adapter or job function.

| Job | Guard | Reason |
|---|---|---|
| `qcew` | Runs only in months 1, 4, 7, 10 | QCEW data is released quarterly |
| `cbp` | Runs only in month 4 | CBP annual release is in April |
| `jobicy` | Skips if last run < 60 min ago | ToS — once per hour |
| `theirstack` | Skips if last run < 240 min ago | Budget — 200/month cap |
| `serpapi_jobs` | Skips if last run < 180 min ago | Budget — 250/month cap |
| `activejobs` | Skips if last run < 24h ago | Budget — 25 requests/month |
| `google_maps` | Skips if `GOOGLE_MAPS_API_KEY` not set | Requires paid key |
| `reddit` | Degrades to public rate if `REDDIT_CLIENT_ID` not set | |
| `juju` | Skips if `JUJU_PARTNER_ID` not set | Requires partner agreement |

To force a job past its skip guard, clear the relevant cache file:

```bash
# jobicy
rm data/jobicy_cache.json

# activejobs
rm data/rapidapi_activejobs_cache.json
```

For rate_manager-gated jobs (theirstack, serpapi), there is no local cache file — the gate reads from the `rate_budget` DB table. Restarting the collector does not bypass these gates.

---

## Rate Manager Integration

All jobs that call external APIs must go through `core/rate_manager.py`. The scheduler job wrapper calls `check_budget(source_key)` before each adapter call. The adapter calls `log_request(source_key, ...)` after each HTTP call (even on failure).

**`check_budget(source_key)`** — returns `True` if the daily/monthly request count is below the configured limit. Returns `False` (skip, do not call API) if the budget is exhausted.

**`log_request(source_key, ...)`** — writes a row to the `rate_log` DB table and increments the rolling counter. Must be called even when the request fails.

Rate manager source keys match `source` in `ScraperSignal`:

| Adapter | source_key |
|---|---|
| TheirStack | `theirstack` |
| SerpAPI | `serpapi_google_jobs` |
| Active Jobs DB | `rapidapi_activejobs` |
| Jobicy | `jobicy` |
| BLS | `bls` |
| USAJobs | `usajobs` |

---

## CLI Commands

```bash
# List all registered jobs (* = included in --run-now)
python collector_main.py --list-jobs

# Fire all daily jobs sequentially
python collector_main.py --run-now

# Fire one specific job
python collector_main.py --job theirstack
python collector_main.py --job serpapi_jobs
python collector_main.py --job jobicy
python collector_main.py --job activejobs
python collector_main.py --job bls
python collector_main.py --job qcew
python collector_main.py --job warn_tx
python collector_main.py --job posting_expiry
python collector_main.py --job posting_purge
```

`--run-now` only fires jobs marked `*` in `--list-jobs` output (typically the daily/interval job-board jobs). It skips maintenance and quarterly jobs.

---

## Reading Scheduler Status

Live job status via API (server must be running):

```bash
curl http://localhost:8765/api/scheduler/status | python3 -m json.tool
```

Returns each job's `next_run_time`, last run status, and signal count from the most recent execution.

Rate budget check:

```bash
curl http://localhost:8765/api/rate-budget | python3 -m json.tool
```

Returns `{source_key: {used_today, daily_limit, remaining, last_request_at}}` for every registered source.

---

## Disabling a Job

1. Edit `config/scheduler.yaml`
2. Set `enabled: false` under the job ID
3. Restart `helios-collector` for the change to take effect:
   ```bash
   sudo systemctl restart helios-collector
   ```

The job remains registered and visible in `--list-jobs` output, but will not fire.

---

## Adding a New Scheduled Job

1. Create adapter in `collectors/<subcategory>/<source>_adapter.py`
2. Add source to `API_SOURCE_REGISTRY` in `core/rate_manager.py`
3. Add job function in `core/scheduler.py`:
   ```python
   def _run_mysource() -> None:
       try:
           from collectors.job_boards.mysource_adapter import MySourceAdapter
           signals = MySourceAdapter().scrape("austin_tx")
           logger.info("[Scheduler] mysource: %d signals", len(signals))
       except Exception as e:
           logger.error("[Scheduler] mysource failed: %s", e)
   ```
4. Wire with `scheduler.add_job(_run_mysource, ...)` inside `core/scheduler.py`
5. Add YAML entry in `config/scheduler.yaml`:
   ```yaml
   mysource:
     enabled: true
     description: "My source — what it does"
     trigger: cron
     cron:
       hour: 10
       minute: 0
   ```

Key rule: **every job function must wrap its body in `try/except Exception`**. An uncaught exception inside a job silently kills that job for the rest of the scheduler's lifetime.

---

## Troubleshooting

**Job fired but returned 0 signals:**

```bash
# Check rate budget
curl http://localhost:8765/api/rate-budget | python3 -m json.tool

# Check for skip guard (look for "gate active" or "budget exhausted" log lines)
sudo journalctl -u helios-collector -n 100 | grep -i "gate\|budget\|skip"

# Fire manually to see output
python collector_main.py --job <job_id>
```

**Scheduler not running:**

```bash
sudo systemctl status helios-collector
sudo journalctl -u helios-collector -n 50
```

If stopped, check for Python import errors or a missing `.env`. The collector will fail to start if any adapter import fails at module load time.

**Job running but not writing to DB:**

Verify the ingest path is being called. All job-board adapters call `ingest_job_posting(signal, region, session=session)` — if this returns `None`, the posting was skipped (likely a dedup hit or missing required fields). Check for `[skipped]` counts in the log:

```bash
sudo journalctl -u helios-collector -n 50 | grep -i "skipped\|ingested"
```
