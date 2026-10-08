#!/bin/sh
# lab-loadoff-1600 (2026-10-08, ryuji; this clock is UTC, so the timer is 20:00 UTC = 16:00 EDT): backstop for Rohit's
# "all test load off by 16:00". Stops any ryuji test unit still running (its ExecStopPost hands the BMC offset back
# to ryuji-fan-guard), kills leftover stress-ng, makes sure ryuji-fan-guard is active. Log: /var/tmp/lab-loadoff-1600.log
L=/var/tmp/lab-loadoff-1600.log
echo "$(date '+%F %T') backstop start" >> $L
for u in $(systemctl list-units --type=service --state=active --no-legend --plain 'ryuji-profile*' 'ryuji-floor*' \
           'ryuji-quiet*' | awk '{print $1}'); do
  systemctl stop "$u" && echo "$(date '+%T') stopped $u" >> $L
done
pkill -x stress-ng-cpu 2>/dev/null; pkill -x stress-ng 2>/dev/null && echo "$(date '+%T') killed stress-ng" >> $L
systemctl is-active --quiet ryuji-fan-guard || { systemctl start ryuji-fan-guard; echo "$(date '+%T') started ryuji-fan-guard" >> $L; }
echo "$(date '+%T') done: ryuji-fan-guard $(systemctl is-active ryuji-fan-guard)" >> $L
