#!/bin/sh
# ExecStopPost for mic-r720-notch: fan-watchdog takes the R720 fans back (it starts at its curve).
systemctl start fan-watchdog
echo "$(date +%s) $(date +%T) restore: fan-watchdog $(systemctl is-active fan-watchdog)" >> /var/tmp/r720-notch-restore.log
