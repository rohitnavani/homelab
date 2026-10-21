#!/bin/bash
# pi-soc-sampler: room-reference proxy. Every 60 s reads the mirror Pi's SoC temperature, load average and CPU
# busy share (from /proc/stat deltas) over ssh, and appends a CSV line. Read-only on the Pi. Runs until UNTIL (epoch).
# usage: pi-soc-sampler.sh OUT.csv UNTIL_EPOCH
out=$1; until=$2
[ -s "$out" ] || echo "epoch,soc_c,load1,busy_pct,arm_mhz" > "$out"
prev=""
while [ "$(date +%s)" -lt "$until" ]; do
  t0=$(date +%s)
  r=$(timeout 20 ssh -o BatchMode=yes -o ConnectTimeout=8 rohit@10.0.0.32 \
      'echo $(cat /sys/class/thermal/thermal_zone0/temp) $(cut -d" " -f1 /proc/loadavg) $(head -1 /proc/stat | cut -d" " -f2-) $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq 2>/dev/null || echo 0)' 2>/dev/null)
  if [ -n "$r" ]; then
    set -- $r
    soc=$1; l1=$2; shift 2
    cpu=("$@"); n=${#cpu[@]}; freq=${cpu[$((n-1))]}; unset 'cpu[$((n-1))]'
    tot=0; for v in "${cpu[@]}"; do tot=$((tot+v)); done
    idle=$(( ${cpu[3]} + ${cpu[4]} ))
    busy=""
    if [ -n "$prev" ]; then
      set -- $prev; dt=$((tot-$1)); di=$((idle-$2))
      [ "$dt" -gt 0 ] && busy=$(awk -v a=$dt -v b=$di 'BEGIN{printf "%.1f", 100*(a-b)/a}')
    fi
    prev="$tot $idle"
    echo "$t0,$(awk -v s=$soc 'BEGIN{printf "%.1f", s/1000}'),$l1,$busy,$((freq/1000))" >> "$out"
  fi
  sleep $(( 60 - ($(date +%s) - t0) % 60 ))
done
