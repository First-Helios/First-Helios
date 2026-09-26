#!/usr/bin/env bash
# After the stress run: re-run Q4_K_M on the 12 pages it processed before the room fan came on
# (~07:45 CDT), with the in-RAM prompt cache disabled (--cache-ram 0, default 8192 MiB). Checks
# fan-on timing, peak RSS without the prompt cache, and that outputs are byte-identical.
set -u
cd ~/menu-model-spike
export MENU_SPIKE_DATA=$HOME/menu-model-spike/data PYTHONPATH=. MENU_SPIKE_PROCESS=v2
PAGES="04cea9ccc03e 0580f923bc5e 07a94b267993 0824dfcdd900 0bf6f5017a83 19b79ff22898 14fb3f6b00e4 1b6233a80694 1cf69aeeae45 200000724aa0 295dac75322d 2bfd0cdf0f6e"
for i in $(seq 1 1000); do grep -q STRESS-DONE logs/stress.log && break; sleep 20; done
for i in $(seq 1 90); do [ "$(cat /sys/class/thermal/thermal_zone0/temp)" -lt 55000 ] && break; sleep 10; done
spikes/menu_model/stress/monitor.sh logs/rerun-monitor.csv & MON=$!
echo "st-km-fan start $(date +%s)" > logs/rerun.log
taskset -c 4-7 llama.cpp/build/bin/llama-server -m gguf/Qwen3-4B-Instruct-2507-Q4_K_M.gguf --host 127.0.0.1 --port 8080 \
  -t 4 -c 8192 -np 2 -fa on -ctk q8_0 -ctv q8_0 --cache-ram 0 > logs/server-st-km-fan.log 2>&1 &
SP=$!
for i in $(seq 1 90); do curl -sf 127.0.0.1:8080/health >/dev/null && break; sleep 2; done
rm -rf data/extract/st-km-fan
.venv/bin/python -m spikes.menu_model.extract run --tag st-km-fan --workers 2 $PAGES >> logs/rerun.log 2>&1
echo "st-km-fan end $(date +%s) $(grep VmHWM /proc/$SP/status)" >> logs/rerun.log
kill $SP; kill $MON
echo RERUN-DONE >> logs/rerun.log
