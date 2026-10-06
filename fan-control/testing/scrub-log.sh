#!/bin/bash
# scrub-log (2026-10-06): during a dataPool scrub, every 60 s log scrub progress, md1200-fan v3 state (its JSON holds
# the shelf temps, so the EMM serial port is not touched), fan-watchdog state, and each shelf drive's temperature.
# usage: scrub-log.sh [csv]   (stop the unit when done)
OUT=${1:-/var/tmp/scrub-log.csv}
DISKS=$(zpool list -vHP dataPool | awk 'NR>1 && $1 ~ /^\/dev\// {print $1}' | sed 's/-part[0-9]*$//')
[ -s "$OUT" ] || echo "epoch,time,scrub,shelf_pct,shelf_rpm,drive,bp,sim,exp,r720_pct,cpu,exh,inlet,hdd,ssd,dimm,$(for d in $DISKS; do basename $d; done | paste -sd,)" > "$OUT"
while :; do
  s=$(zpool status dataPool | grep -oP '[0-9.]+% done' | head -1); s=${s:-$(zpool status dataPool | grep -oE 'scrub (paused|repaired|canceled)' | head -1)}
  v=$(python3 -c "import json;d=json.load(open('/run/md1200-fan.state'));t=d['temps'];print(d['pct'],round(d['rpm']),t['drive'],t['backplane'],t['SIM'],t['expander'],sep=',')" 2>/dev/null)
  f=$(sed -E 's/.* ([0-9]+)% \(cpu=([0-9]+) exh=([0-9]+) inlet=([0-9]+) hdd=([0-9]+) ssd=([0-9]+)\) \(dimm=([0-9]+)\).*/\1,\2,\3,\4,\5,\6,\7/' /run/fan-watchdog.state)
  t=""; for d in $DISKS; do t="$t,$(smartctl -n standby -A $d 2>/dev/null | grep -oP 'Current Drive Temperature:\s+\K\d+')"; done
  echo "$(date +%s),$(date +%T),${s// /_},${v:-,,,,,},${f}${t}" >> "$OUT"
  sleep 60
done
