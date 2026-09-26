#!/usr/bin/env bash
# Throughput micro-bench (step E, after the v1/v2 A/B): Qwen3-4B, process v2, 3 dev pages
# (8 chunks). One llama-server per config, pinned to the A76 cores; cooldown to <55 C first.
# Configs: parallel slots (-np), Q4_K_M vs Q4_0 (ARM repack), speculative decoding
# (prompt n-gram, and a Qwen3-0.6B draft model).
set -u
cd ~/menu-model-spike
export MENU_SPIKE_DATA=$HOME/menu-model-spike/data PYTHONPATH=. MENU_SPIKE_PROCESS=v2
PAGES="f298109dce7a 0580f923bc5e abefb3029e57"
KM=gguf/Qwen3-4B-Instruct-2507-Q4_K_M.gguf
Q0=gguf/Qwen3-4B-Instruct-2507-Q4_0.gguf
DRAFT=gguf/Qwen3-0.6B-Q8_0.gguf
NGRAM="--spec-type ngram-simple --spec-ngram-simple-size-n 3 --spec-ngram-simple-size-m 8"
SPECD="--spec-type draft-simple -md $DRAFT --spec-draft-n-max 8"
cool() { for i in $(seq 1 60); do [ "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 55000 ] && break; sleep 10; done; }
run() {  # NAME NP MODEL [extra server args...]
  local name=$1 np=$2 model=$3; shift 3
  local tag=tp-$name
  rm -rf "$MENU_SPIKE_DATA/extract/$tag"; cool
  taskset -c 4-7 llama.cpp/build/bin/llama-server -m "$model" --host 127.0.0.1 --port 8080 -t 4 \
    -c $((np * 4096)) -np "$np" -fa on -ctk q8_0 -ctv q8_0 "$@" > "logs/server-$tag.log" 2>&1 &
  local spid=$!
  for i in $(seq 1 90); do curl -sf 127.0.0.1:8080/health >/dev/null && break; sleep 2; done
  echo "$tag start soc=$(cat /sys/class/thermal/thermal_zone0/temp)" >> logs/tp.log
  .venv/bin/python -m spikes.menu_model.extract run --tag "$tag" --workers "$np" $PAGES >> logs/tp.log 2>&1
  echo "$tag $(grep VmHWM /proc/$spid/status) soc=$(cat /sys/class/thermal/thermal_zone0/temp)" >> logs/tp.log
  grep -iE "accept|draft" "logs/server-$tag.log" | tail -2 >> logs/tp.log
  kill $spid; wait $spid 2>/dev/null
}
for i in $(seq 1 1000); do grep -q AB-DONE logs/ab.log && break; sleep 15; done
spikes/menu_model/stress/monitor.sh logs/tp-monitor.csv & MON=$!
: > logs/tp.log
run np1 1 $KM
run np2 2 $KM
run np4 4 $KM
run np6 6 $KM
run np4-q40 4 $Q0
run np1-q40 1 $Q0
run np1-ngram 1 $KM $NGRAM
run np4-ngram 4 $KM $NGRAM
run np1-draft 1 $KM $SPECD
run np4-draft 4 $KM $SPECD
kill $MON; echo TP-DONE >> logs/tp.log
