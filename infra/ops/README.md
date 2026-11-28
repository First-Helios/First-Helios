# Alerting: runbook (ADR-0031 D5)

Decisions: [ADR-0031](../../docs/adr/0031-phase8-operations-basics.md) D5, Q18–Q21 and Q26.
The Pi pings [healthchecks.io](https://healthchecks.io) (Hobbyist plan, free), and **silence is
an alert**: a Pi that is off, a power cut and a dead internet link all alert, with nothing to
run off the Pi. Alerts go by **email only** (Q19).

| Piece | What it does |
|---|---|
| `watch.sh` | Four checks every 5 minutes: `site`, `disk`, `run-progress`, `awaiting-reader` |
| `helios-watch.service`, `.timer` | Runs it every 5 minutes, as `orangepi`, with `hc.env` |
| `hc-ping.sh` | One ping; never fails, never logs the URL. Also used by the loop unit |
| `hc.env.example` | The six variable names, no values |
| `../pipeline-host/helios-pipeline-loop.service` | `ExecStartPre=-` pings `monthly-run` `/start`; `ExecStopPost=-` pings `/$EXIT_STATUS` |
| `../backup/backup.sh` | Pings `backup` `/start`, then `/<exit status>` (D1) |

## The six checks (create them in healthchecks.io)

| Check | Schedule | Grace | Fails when |
|---|---|---|---|
| `site` | Simple, period 5 min | 10 min | Local `/readyz`, `https://firsthelios.com/healthz` or `https://firsthelios.com/v1/venues?limit=1` is not 200. The failing lines are the ping body |
| `disk` | Simple, period 1 h | 1 h | `/` at or above 85% |
| `backup` | Simple, period 1 day | 6 h | restic or `pg_dump` fails, or the backup doesn't run |
| `monthly-run` | Cron `0 18 10 * *`, time zone UTC | 4 days | The loop exits non-zero or is refused (`AWAITING_SWAP`: exit 2), the timer didn't fire, or the run hasn't ended 4 days after the 10th |
| `run-progress` | Simple, period 1 h | 1 h | The loop is active and `var/pipeline-host/logs/progress.log` (or the unit's start, if newer) is 8 h old or more |
| `awaiting-reader` | Simple, period 1 day | 1 day | `var/pipeline-host/AWAITING_SWAP` is 3 days old or more (a nudge, not an outage) |

`watch.sh` runs every check on every firing, so the periods only bound how long silence may
last. A `monthly-run` "start" with no "end" for longer than the grace also alerts. In each
check's settings, set the email integration on.

A second channel, independent of the Pi: **Cloudflare → Notifications → Add → Tunnel Health
Alert** (email), which fires when the tunnel's connectors go down.

## Setup on the Pi (after the 2026-12-10 run's swap, with the owner's go-ahead)

After a deploy that contains this directory:

```bash
install -d -m 0700 ~/.config ~/.config/helios-ops
install -m 0600 infra/ops/hc.env.example ~/.config/helios-ops/hc.env
nano ~/.config/helios-ops/hc.env                 # the six ping URLs from healthchecks.io
sudo cp infra/ops/helios-watch.service infra/ops/helios-watch.timer /etc/systemd/system/
sudo cp infra/pipeline-host/helios-pipeline-loop.service /etc/systemd/system/   # the two pings
sudo systemctl daemon-reload
sudo systemctl start helios-watch                # once by hand:
journalctl -u helios-watch -n 10                 # four "ok" lines; the checks turn green
sudo systemctl enable --now helios-watch.timer
```

Copying the loop unit in place is safe while the loop is stopped, which is the case between the
swap and the next 10th. The timer starts the new unit then.

**Test an alert once:** `sudo systemctl stop helios-watch.timer`, wait past `site`'s period plus
grace (15 minutes), confirm the email arrives, then `sudo systemctl start helios-watch.timer`
and confirm the "back up" email.
