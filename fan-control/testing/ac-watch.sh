#!/bin/bash
# ac-watch: every 5 min, log room-temperature proxies and flag when the AC looks to be back.
# Proxies: mementos R720 "Inlet Temp" (AC on: ~23-25C; AC out 2026-10-06: ~26C) and tinynas nvme0
# idle temp (AC on before 10-04 16:00: ~31C; since: ~33-35C). AC_BACK is written once the
# last 6 samples (30 min) of either proxy are at or below its threshold.
O=${DATA:-$HOME/fan-control-data}; mkdir -p "$O"
LOG=$O/ac-watch.csv; FLAG=$O/AC_BACK
[ -f $LOG ] || echo "time,mementos_inlet,tinynas_nvme0,ryuji_sio1" > $LOG
inlet=$(ssh -o BatchMode=yes -o ConnectTimeout=5 mementos 'sudo ipmitool sdr type Temperature 2>/dev/null' | awk -F'|' '/Inlet/{print $5+0}')
nvme=$(ssh -o BatchMode=yes -o ConnectTimeout=5 tinynas 'for h in /sys/class/hwmon/hwmon*; do [ "$(cat $h/name)" = nvme ] && { cat $h/temp1_input; break; }; done' 2>/dev/null)
sio=$(ssh -o BatchMode=yes -o ConnectTimeout=5 ryuji 'sudo -n ipmitool sdr type Temperature 2>/dev/null' | awk -F'|' '/SIO Temp 1/{print $5+0}')
echo "$(date '+%F %T'),${inlet},$([ -n "$nvme" ] && echo $((nvme/1000))),${sio}" >> $LOG
[ -f $FLAG ] && exit 0
tail -6 $LOG | awk -F, -v n=$(tail -n +2 $LOG | wc -l) 'n>=6 { if ($2!="" && $2<=24) a++; if ($3!="" && $3<=31) b++ } END { exit !(a==6 || b==6) }' \
  && echo "AC looks back since about $(date -d '-30 min' '+%F %T') (inlet<=24 or nvme0<=31 for 30 min)" > $FLAG
exit 0
