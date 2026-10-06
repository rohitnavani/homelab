#!/bin/sh
# ExecStopPost for mementos-fixedfan: no leftover load; fan-watchdog takes the fans back (it starts at its curve).
pkill -x stress-ng-cpu 2>/dev/null; pkill -x stress-ng 2>/dev/null
systemctl start fan-watchdog
echo "$(date '+%F %T') restore: load killed, fan-watchdog $(systemctl is-active fan-watchdog)" >> /var/tmp/mementos-fixedfan-restore.log
