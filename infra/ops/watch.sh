#!/usr/bin/env bash
# The Pi's watcher (ADR-0031 D5, Q21): four checks, each a healthchecks.io dead-man's switch.
#   bash infra/ops/watch.sh        # helios-watch.timer runs it every 5 minutes
# Run on the Pi from the deploy directory (DATA overrides it, as in pipeline-host/lib.sh). Each
# check pings its URL from hc.env on success, or /fail with the reason as the body. The Pi
# being off, the power, or the internet going away means no pings at all, and healthchecks.io
# alerts on the silence. Every check runs on every firing; the checks' periods (5 min to 1 day)
# only bound how long silence may last.
#   site             local /readyz, and https://firsthelios.com/healthz and /v1/venues?limit=1
#                    (out through Cloudflare and back through the tunnel) all answer 200
#   disk             / is under 85% full
#   run-progress     while helios-pipeline-loop is active, logs/progress.log (or the start, if
#                    newer) is under 8 h old: P8-23's slowest batch took 6.6 h
#   awaiting-reader  var/pipeline-host/AWAITING_SWAP, if present, is under 3 days old (a nudge)
# Always exits 0: one failing check must not stop the others' pings.
set -uo pipefail
cd "$(dirname "$(realpath "$0")")/../.."
DATA=${DATA:-.}
STATE=$DATA/var/pipeline-host
PING=(bash infra/ops/hc-ping.sh)
DISK_MAX=85
STALL_HOURS=8
READER_DAYS=3
SITE=(http://127.0.0.1:8000/readyz https://firsthelios.com/healthz "https://firsthelios.com/v1/venues?limit=1")

report() { # report <URL variable> <check> <failure lines, or empty for ok>
  if [ -z "$3" ]; then
    "${PING[@]}" "$1" ok "$2 ok"
    echo "$2 ok"
  else
    "${PING[@]}" "$1" fail "$3"
    printf '%s FAIL: %s\n' "$2" "$3"
  fi
}

check_site() {
  local u code bad=
  for u in "${SITE[@]}"; do
    code=$(curl -s -o /dev/null -m 15 -w '%{http_code}' "$u")
    [ "$code" = 200 ] || bad+="$u $code"$'\n'
  done
  report HC_SITE_URL site "$bad"
}

check_disk() {
  local used
  used=$(df --output=pcent / | tail -n 1 | tr -dc '0-9')
  if [ -z "$used" ]; then
    report HC_DISK_URL disk "df gave no figure for /"
  elif [ "$used" -ge "$DISK_MAX" ]; then
    report HC_DISK_URL disk "/ is ${used}% full (alert at ${DISK_MAX}%)"
  else
    report HC_DISK_URL disk ""
  fi
}

check_run_progress() {
  if ! systemctl is-active --quiet helios-pipeline-loop; then
    report HC_RUN_PROGRESS_URL run-progress ""
    return
  fi
  local started newest log=$STATE/logs/progress.log
  # --timestamp=unix: the Pi's local zone prints as "CST", which date(1) would read as US Central
  started=$(systemctl show helios-pipeline-loop -p ActiveEnterTimestamp --value --timestamp=unix | tr -d @)
  [[ "$started" =~ ^[0-9]+$ ]] || started=0
  newest=$(stat -c %Y "$log" 2>/dev/null || echo 0)
  [ "$started" -gt "$newest" ] && newest=$started
  local age=$(($(date +%s) - newest))
  if [ "$age" -ge $((STALL_HOURS * 3600)) ]; then
    report HC_RUN_PROGRESS_URL run-progress \
      "the loop is active and $log has not changed for $((age / 3600)) h (alert at ${STALL_HOURS} h)"
  else
    report HC_RUN_PROGRESS_URL run-progress ""
  fi
}

check_awaiting_reader() {
  local marker=$STATE/AWAITING_SWAP
  if [ ! -f "$marker" ]; then
    report HC_AWAITING_READER_URL awaiting-reader ""
    return
  fi
  local age=$(($(date +%s) - $(stat -c %Y "$marker")))
  if [ "$age" -ge $((READER_DAYS * 86400)) ]; then
    report HC_AWAITING_READER_URL awaiting-reader \
      "a run has waited $((age / 86400)) days for its reader: $(tr '\n' ' ' <"$marker")"
  else
    report HC_AWAITING_READER_URL awaiting-reader ""
  fi
}

check_site
check_disk
check_run_progress
check_awaiting_reader
exit 0
