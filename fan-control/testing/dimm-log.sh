#!/bin/bash
# Log populated DIMM temps (Xeon E5 v2 iMC DIMMTEMPSTAT registers, read-only) once a minute.
LOG=/var/tmp/dimm-log.csv
regs=()
for dev in $(lspci -D | awk '/Thermal Control/{print $1}'); do
  for off in 0x150 0x154 0x158; do
    v=$((16#$(setpci -s $dev $off.L)))
    [ $((v >> 24)) -eq 7 ] && [ $((v & 0xff)) -ge 10 ] && regs+=("$dev:$off")
  done
done
[ -f $LOG ] || echo "time,n,max,avg,all" > $LOG
while :; do
  vals=()
  for r in "${regs[@]}"; do vals+=($(( 16#$(setpci -s ${r%:*} ${r##*:}.L) & 0xff ))); done
  printf '%s,%d,%s,%s,%s\n' "$(date +%T)" ${#vals[@]} "$(printf '%s\n' "${vals[@]}" | sort -n | tail -1)" \
    "$(printf '%s\n' "${vals[@]}" | awk '{s+=$1}END{printf "%.1f", s/NR}')" "$(IFS=/; echo "${vals[*]}")" >> $LOG
  sleep 60
done
