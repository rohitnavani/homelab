#!/bin/sh
# lab-loadoff-final (2026-10-13, ryuji): backstop at the end of each loud or medium window of the final rack run.
# Stops every ryuji test unit still running (its ExecStopPost hands the BMC offset back to ryuji-fan-guard), kills
# leftover stress-ng and fio, makes sure ryuji-fan-guard runs. Log: /var/tmp/lab-loadoff-final.log
L=/var/tmp/lab-loadoff-final.log
echo "$(date '+%F %T') backstop start" >> $L
for u in $(systemctl list-units --type=service --state=active --no-legend --plain 'ryuji-profile*' 'ryuji-floor*' \
           'ryuji-quiet*' 'pdu-cut*' | awk '{print $1}'); do
  systemctl stop "$u" && echo "$(date '+%T') stopped $u" >> $L
done
pkill -x stress-ng-cpu 2>/dev/null; pkill -x stress-ng 2>/dev/null && echo "$(date '+%T') killed stress-ng" >> $L
pkill -x fio 2>/dev/null && echo "$(date '+%T') killed fio" >> $L
systemctl is-active --quiet ryuji-fan-guard || { systemctl start ryuji-fan-guard; echo "$(date '+%T') started ryuji-fan-guard" >> $L; }
echo "$(date '+%T') done: ryuji-fan-guard $(systemctl is-active ryuji-fan-guard)" >> $L
