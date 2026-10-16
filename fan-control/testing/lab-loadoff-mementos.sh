#!/bin/sh
# lab-loadoff-final (2026-10-13, mementos): backstop at the end of each loud or medium window of the final rack run, in
# case a block overran or the session stalled. Stops every test unit still running (each unit's ExecStopPost hands the
# fans back to fan-watchdog / md1200-fan), kills leftover stress-ng and fio, makes sure both controllers run.
# No scrub is started by this run, so none is touched. Log: /var/tmp/lab-loadoff-final.log
L=/var/tmp/lab-loadoff-final.log
echo "$(date '+%F %T') backstop start" >> $L
for u in $(systemctl list-units --type=service --state=active --no-legend --plain 'mementos-fixedfan*' 'mementos-steps*' \
           'mic-shelf*' 'mic-r720*' 'noise-sweep*' 'scrub-quiet*' 'shelf-exp*' 'pdu-cut*' | awk '{print $1}'); do
  systemctl stop "$u" && echo "$(date '+%T') stopped $u" >> $L
done
pkill -x stress-ng-cpu 2>/dev/null; pkill -x stress-ng 2>/dev/null && echo "$(date '+%T') killed stress-ng" >> $L
pkill -x fio 2>/dev/null && echo "$(date '+%T') killed fio" >> $L
for u in fan-watchdog md1200-fan; do
  systemctl is-active --quiet $u || { systemctl start $u; echo "$(date '+%T') started $u" >> $L; }
done
echo "$(date '+%T') done: fan-watchdog $(systemctl is-active fan-watchdog), md1200-fan $(systemctl is-active md1200-fan)" >> $L
