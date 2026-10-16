#!/bin/sh
# mic-r720-listen (2026-10-13 for Thu 10-15 20:00): Rohit's listening test, block 1. mementos's fans at fixed levels in
# 90 s slots on a fixed timetable (he listens blind from the couch, then the kitchen, and notes what he hears per slot);
# everything else idle. Same Dell commands and safety as mic-r720.sh (CPU 75C or a failed read/command -> iDRAC auto).
# ExecStopPost mic-r720-restore.sh starts fan-watchdog again. Log /var/tmp/mic-r720-listen.log
LOG=/var/tmp/mic-r720-listen.log
note() { echo "$(date +%s) $(date +%T) $*" >> $LOG; }
cpu() { ipmitool sdr type Temperature 2>/dev/null | awk -F"|" "/^Temp /{v=\$5+0; if (v>m) m=v} END{print m+0}"; }
at() { date -d "2026-10-15 $1" +%s; }
# slot start, fan %  (A = couch, 20:07:30 walk, B = kitchen; ends 20:16:00)
SLOTS="20:00:00 20  20:01:30 10  20:03:00 30  20:04:30 15  20:06:00 25  20:07:30 10  20:08:30 30  20:10:00 15  20:11:30 10  20:13:00 25  20:14:30 20  20:16:00 end"
set -- $SLOTS
first=$(at $1)
while [ "$(date +%s)" -lt "$first" ]; do sleep 1; done
systemctl stop fan-watchdog
note "fan-watchdog stopped"
while [ $# -ge 2 ]; do
  t=$(at $1); p=$2; shift 2
  while [ "$(date +%s)" -lt "$t" ]; do sleep 1; done
  [ "$p" = end ] && { note "done"; exit 0; }
  if ! ipmitool raw 0x30 0x30 0x01 0x00 >/dev/null || ! ipmitool raw 0x30 0x30 0x02 0xff $(printf '0x%02x' $p) >/dev/null; then
    ipmitool raw 0x30 0x30 0x01 0x01 >/dev/null; note "fan command failed: iDRAC auto"; exit 1
  fi
  note "fans $p%"
  c=$(cpu)
  if [ -z "$c" ] || [ "$c" -eq 0 ] || [ "$c" -ge 75 ]; then ipmitool raw 0x30 0x30 0x01 0x01 >/dev/null; note "cpu '$c': iDRAC auto"; exit 1; fi
done
