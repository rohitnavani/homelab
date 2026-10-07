#!/bin/sh
# ExecStopPost for mic-r720: fan-watchdog takes the fans back (it starts at its curve).
systemctl start fan-watchdog
echo "$(date +%s) $(date +%T) restore: fan-watchdog $(systemctl is-active fan-watchdog)" >> /var/tmp/mic-r720.log
