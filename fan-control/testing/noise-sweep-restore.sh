#!/bin/sh
# ExecStopPost for noise-sweep: production fan control back on both boxes, whatever state the sweep ended in.
systemctl start md1200-fan
systemctl start fan-watchdog
echo "$(date +%s) $(date +%T) restore: md1200-fan $(systemctl is-active md1200-fan), fan-watchdog $(systemctl is-active fan-watchdog)" >> /var/tmp/noise-sweep-restore.log
