#!/bin/sh
# lab-loadoff-1600 (2026-10-08, mementos): backstop for Rohit's "all test load off by 16:00", armed as a transient
# timer in case the test session stalls. Stops any test unit still running (each unit's ExecStopPost hands the fans
# back to fan-watchdog or md1200-fan), kills leftover stress-ng, pauses a dataPool scrub that is still running, and
# makes sure fan-watchdog and md1200-fan are active. Log: /var/tmp/lab-loadoff-1600.log
L=/var/tmp/lab-loadoff-1600.log
echo "$(date '+%F %T') backstop start" >> $L
for u in $(systemctl list-units --type=service --state=active --no-legend --plain 'mementos-fixedfan*' 'mementos-steps*' \
           'mic-shelf*' 'mic-r720*' 'noise-sweep*' 'scrub-quiet*' 'shelf-exp*' 'md1200-v32-deploy*' | awk '{print $1}'); do
  systemctl stop "$u" && echo "$(date '+%T') stopped $u" >> $L
done
pkill -x stress-ng-cpu 2>/dev/null; pkill -x stress-ng 2>/dev/null && echo "$(date '+%T') killed stress-ng" >> $L
if zpool status dataPool 2>/dev/null | grep -q 'scrub in progress'; then
  zpool scrub -p dataPool && echo "$(date '+%T') paused the dataPool scrub (resume: zpool scrub dataPool)" >> $L
fi
for u in fan-watchdog md1200-fan; do
  systemctl is-active --quiet $u || { systemctl start $u; echo "$(date '+%T') started $u" >> $L; }
done
echo "$(date '+%T') done: fan-watchdog $(systemctl is-active fan-watchdog), md1200-fan $(systemctl is-active md1200-fan)" >> $L
