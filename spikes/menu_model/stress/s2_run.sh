#!/usr/bin/env bash
# Usable-price session: one extraction run over a page list, stress-test style (PLAN.md):
# llama-server pinned to the A76 cores on 127.0.0.1, cooled to <55 C first, monitor on, every
# log appended (a power outage already cut one run; a re-run resumes: finished pages are kept).
# usage: s2_run.sh TAG MODEL NP CTX PAGES_FILE   (env: MENU_SPIKE_PROMPT, MENU_SPIKE_CHUNK, ...)
set -u
cd ~/menu-model-spike
export MENU_SPIKE_DATA=$HOME/menu-model-spike/data PYTHONPATH=. MENU_SPIKE_PROCESS=v2
tag=$1 model=$2 np=$3 ctx=$4 pages_file=$5
PAGES=$(python3 -c "import json,sys; print(' '.join(json.load(open(sys.argv[1]))))" "$pages_file")
cool() { for i in $(seq 1 90); do [ "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 55000 ] && break; sleep 10; done; }
spikes/menu_model/stress/monitor.sh "logs/s2-monitor-$tag.csv" & MON=$!
cool
echo "$tag start $(date +%s) soc=$(cat /sys/class/thermal/thermal_zone0/temp) prompt=${MENU_SPIKE_PROMPT:-v22} chunk=${MENU_SPIKE_CHUNK:-1500}" >> logs/s2.log
taskset -c 4-7 llama.cpp/build/bin/llama-server -m "gguf/$model" --host 127.0.0.1 --port 8080 -t 4 \
  -c "$ctx" -np "$np" -fa on -ctk q8_0 -ctv q8_0 >> "logs/server-$tag.log" 2>&1 &
spid=$!
for i in $(seq 1 120); do curl -sf 127.0.0.1:8080/health >/dev/null && break; sleep 2; done
.venv/bin/python -m spikes.menu_model.extract run --tag "$tag" --workers "$np" $PAGES >> logs/s2.log 2>&1
echo "$tag end $(date +%s) $(grep VmHWM /proc/$spid/status)" >> logs/s2.log
kill $spid; wait $spid 2>/dev/null
kill $MON
echo "S2-DONE $tag" >> logs/s2.log
