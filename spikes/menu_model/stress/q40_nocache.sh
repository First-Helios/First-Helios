#!/usr/bin/env bash
# After the stress run: Q4_0 peak RSS with the in-RAM prompt cache off (--cache-ram 0) and
# output determinism vs the stress run, on 3 stress pages (one small, one mid, one large).
set -u
cd ~/menu-model-spike
export MENU_SPIKE_DATA=$HOME/menu-model-spike/data PYTHONPATH=. MENU_SPIKE_PROCESS=v2
PAGES="0824dfcdd900 2bfd0cdf0f6e 4598f318ba72"

for i in $(seq 1 90); do [ "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 55000 ] && break; sleep 10; done
spikes/menu_model/stress/monitor.sh logs/q40check-monitor.csv & MON=$!
echo "st-q40-nocache start $(date +%s)" > logs/q40check.log
taskset -c 4-7 llama.cpp/build/bin/llama-server -m gguf/Qwen3-4B-Instruct-2507-Q4_0.gguf --host 127.0.0.1 --port 8080 \
  -t 4 -c 8192 -np 2 -fa on -ctk q8_0 -ctv q8_0 --cache-ram 0 > logs/server-st-q40-nocache.log 2>&1 &
SP=$!
for i in $(seq 1 90); do curl -sf 127.0.0.1:8080/health >/dev/null && break; sleep 2; done
rm -rf data/extract/st-q40-nocache
.venv/bin/python -m spikes.menu_model.extract run --tag st-q40-nocache --workers 2 $PAGES >> logs/q40check.log 2>&1
echo "st-q40-nocache end $(date +%s) $(grep VmHWM /proc/$SP/status)" >> logs/q40check.log
kill $SP; kill $MON
echo Q40CHECK-DONE >> logs/q40check.log
