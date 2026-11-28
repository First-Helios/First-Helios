#!/usr/bin/env bash
# One healthchecks.io ping (ADR-0031 D5). The ping URL comes from a variable that hc.env sets.
#   bash infra/ops/hc-ping.sh <URL variable> <start|ok|fail|exit> [body]
# `exit` sends /$EXIT_STATUS (systemd sets it for ExecStopPost=): healthchecks.io reads 0 as
# success and 1-255 as failure; a signal name (a kill) is sent as /fail. An unset variable is no
# ping (alerting not set up yet), and a failed ping exits 0: a ping must never fail what it
# watches. Anyone holding a ping URL could report "all well", so it is never logged.
set -uo pipefail
VAR=${1:?usage: hc-ping.sh <URL variable> <start|ok|fail|exit> [body]}
KIND=${2:?usage: hc-ping.sh <URL variable> <start|ok|fail|exit> [body]}
[[ "$VAR" =~ ^HC_[A-Z_]+_URL$ ]] || {
  echo "error: not a ping variable: '$VAR'" >&2
  exit 2
}
URL=${!VAR:-}
[ -n "$URL" ] || exit 0
case "$KIND" in
  start) SUFFIX=/start ;;
  ok) SUFFIX= ;;
  fail) SUFFIX=/fail ;;
  exit)
    case "${EXIT_STATUS:-}" in
      [0-9] | [1-9][0-9] | 1[0-9][0-9] | 2[0-4][0-9] | 25[0-5]) SUFFIX=/$EXIT_STATUS ;;
      *) SUFFIX=/fail ;;
    esac
    ;;
  *)
    echo "error: not a ping kind: '$KIND'" >&2
    exit 2
    ;;
esac
curl -fsS -m 10 --retry 3 -o /dev/null --data-binary "${3:-}" "$URL$SUFFIX" ||
  echo "hc-ping: $VAR$SUFFIX failed (ignored)" >&2
exit 0
