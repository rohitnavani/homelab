#!/bin/bash
# hdd-temp-log: every 60 s, epoch + each rotating drive's temperature (smartctl -n standby: never wakes a drive).
# usage: hdd-temp-log.sh <csv>
OUT=${1:-/var/tmp/hdd-temp.csv}
D=$(lsblk -dno NAME,ROTA,TYPE | awk '$2==1 && $3=="disk"{print $1}')
[ -s "$OUT" ] || echo "epoch,$(echo $D | tr ' ' ',')" > "$OUT"
while :; do
  row=$(date +%s)
  for d in $D; do row="$row,$(smartctl -n standby -A /dev/$d 2>/dev/null | awk '$1==194{print $10}')"; done
  echo "$row" >> "$OUT"; sleep 60
done
