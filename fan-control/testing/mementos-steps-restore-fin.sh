#!/bin/sh
# ExecStopPost for mementos-steps (2026-10-13 version, which never writes RAPL limits): no leftover load.
pkill -x stress-ng-cpu 2>/dev/null; pkill -x stress-ng 2>/dev/null
echo "$(date '+%F %T') restore: stress-ng gone, fan-watchdog $(systemctl is-active fan-watchdog)" >> /var/tmp/mementos-steps-restore.log
