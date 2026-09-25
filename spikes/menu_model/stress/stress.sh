#!/usr/bin/env bash
# Stress test (PLAN.md): each candidate extracts the same 43 pages unattended (the 41 pages the
# out-of-fold page classifier passes, plus the 2 gold pages it drops, so the extractor is scored
# on all 24 gold pages). Candidates run one after another, cooled to <55 C first, with the
# monitor sampling temperatures/clocks/RAM throughout. llama-server is pinned to the A76 cores
# and bound to 127.0.0.1.
# usage: stress.sh "TAG MODEL NP" ["TAG MODEL NP" ...]
set -u
cd ~/menu-model-spike
export MENU_SPIKE_DATA=$HOME/menu-model-spike/data PYTHONPATH=. MENU_SPIKE_PROCESS=v2
PAGES=$(python3 -c "import json; print(' '.join(json.load(open('data/stress_pages.json'))))")
cool() { for i in $(seq 1 90); do [ "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 55000 ] && break; sleep 10; done; }
: > logs/stress.log
spikes/menu_model/stress/monitor.sh logs/stress-monitor.csv & MON=$!
for cand in "$@"; do
  read -r tag model np <<< "$cand"
  cool
  echo "$tag start $(date +%s) soc=$(cat /sys/class/thermal/thermal_zone0/temp)" >> logs/stress.log
  taskset -c 4-7 llama.cpp/build/bin/llama-server -m "gguf/$model" --host 127.0.0.1 --port 8080 -t 4 \
    -c $((np * 4096)) -np "$np" -fa on -ctk q8_0 -ctv q8_0 > "logs/server-$tag.log" 2>&1 &
  spid=$!
  for i in $(seq 1 90); do curl -sf 127.0.0.1:8080/health >/dev/null && break; sleep 2; done
  .venv/bin/python -m spikes.menu_model.extract run --tag "$tag" --workers "$np" $PAGES >> logs/stress.log 2>&1
  echo "$tag end $(date +%s) $(grep VmHWM /proc/$spid/status)" >> logs/stress.log
  kill $spid; wait $spid 2>/dev/null
done
kill $MON
echo STRESS-DONE >> logs/stress.log
