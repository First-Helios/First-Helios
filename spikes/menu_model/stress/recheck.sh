#!/usr/bin/env bash
# v2.1 quality re-check on the micro-bench dev pages: Q4_K_M and Q4_0, 2 slots.
set -u
cd ~/menu-model-spike
export MENU_SPIKE_DATA=$HOME/menu-model-spike/data PYTHONPATH=. MENU_SPIKE_PROCESS=v2
PAGES="f298109dce7a 0580f923bc5e abefb3029e57"
cool() { for i in $(seq 1 60); do [ "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 55000 ] && break; sleep 10; done; }
run() {  # TAG MODEL
  rm -rf "$MENU_SPIKE_DATA/extract/$1"; cool
  taskset -c 4-7 llama.cpp/build/bin/llama-server -m "$2" --host 127.0.0.1 --port 8080 -t 4 \
    -c 8192 -np 2 -fa on -ctk q8_0 -ctv q8_0 > "logs/server-$1.log" 2>&1 &
  local spid=$!
  for i in $(seq 1 90); do curl -sf 127.0.0.1:8080/health >/dev/null && break; sleep 2; done
  .venv/bin/python -m spikes.menu_model.extract run --tag "$1" --workers 2 $PAGES >> logs/recheck.log 2>&1
  echo "$1 $(grep VmHWM /proc/$spid/status)" >> logs/recheck.log
  kill $spid; wait $spid 2>/dev/null
}
: > logs/recheck.log
run v21-km gguf/Qwen3-4B-Instruct-2507-Q4_K_M.gguf
run v21-q40 gguf/Qwen3-4B-Instruct-2507-Q4_0.gguf
echo RECHECK-DONE >> logs/recheck.log
