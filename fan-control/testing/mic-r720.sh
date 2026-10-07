#!/bin/sh
# mic-r720 (2026-10-06 mic test): hold mementos's R720 fans at fixed % steps at idle, no load, so a microphone can
# be checked against known changes. Same Dell commands as fan-watchdog. fan-watchdog takes the fans back afterwards
# (the unit's ExecStopPost runs mic-r720-restore.sh). A CPU at 75C or more, or a failed read or command -> iDRAC auto.
LOG=/var/tmp/mic-r720.log
note() { echo "$(date +%s) $(date +%T) $*" >> $LOG; }
cpu() { ipmitool sdr type Temperature 2>/dev/null | awk -F'|' '/^Temp /{v=$5+0; if (v>m) m=v} END{print m+0}'; }
systemctl stop fan-watchdog
note "fan-watchdog stopped"
for step in "10 60" "20 75" "10 60" "30 75" "10 60"; do
  set -- $step
  if ! ipmitool raw 0x30 0x30 0x01 0x00 >/dev/null || ! ipmitool raw 0x30 0x30 0x02 0xff $(printf '0x%02x' $1) >/dev/null; then
    ipmitool raw 0x30 0x30 0x01 0x01 >/dev/null; note "fan command failed: iDRAC auto"; exit 1
  fi
  note "fans $1%"
  t=0
  while [ $t -lt $2 ]; do
    c=$(cpu)
    if [ -z "$c" ] || [ "$c" -eq 0 ] || [ "$c" -ge 75 ]; then
      ipmitool raw 0x30 0x30 0x01 0x01 >/dev/null; note "cpu '$c': iDRAC auto"; exit 1
    fi
    sleep 15; t=$((t + 15))
  done
done
note "done"
