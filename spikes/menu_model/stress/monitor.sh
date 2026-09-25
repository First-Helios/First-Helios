#!/usr/bin/env bash
# Samples SoC temperatures, CPU/NPU clocks, memory and load every 10 s to a CSV,
# so a long run can show thermal throttling and memory growth. Read-only sysfs.
# usage: monitor.sh OUT.csv
out=$1
zones=(/sys/class/thermal/thermal_zone*)
{
  printf 'ts'
  for z in "${zones[@]}"; do printf ',%s_c' "$(cat "$z/type")"; done
  printf ',little_mhz,big0_mhz,big1_mhz,npu_mhz,mem_avail_mb,load1\n'
} > "$out"
while true; do
  {
    printf '%s' "$(date +%s)"
    for z in "${zones[@]}"; do printf ',%s' "$(( $(cat "$z/temp") / 1000 ))"; done
    for p in 0 4 6; do printf ',%s' "$(( $(cat /sys/devices/system/cpu/cpufreq/policy$p/scaling_cur_freq) / 1000 ))"; done
    printf ',%s' "$(( $(cat /sys/class/devfreq/fdab0000.npu/cur_freq) / 1000000 ))"
    printf ',%s' "$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)"
    printf ',%s\n' "$(cut -d' ' -f1 /proc/loadavg)"
  } >> "$out"
  sleep 10
done
