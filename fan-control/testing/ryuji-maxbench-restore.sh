#!/bin/sh
# ExecStopPost of ryuji-floor-fin-maxbench: kill any benchmark load; if the guard is not running (a stop during the Full
# Speed phase), put -80 back on the BMC and start the guard.
pkill -f "[7]z b" 2>/dev/null; pkill -x stress-ng 2>/dev/null; pkill -x openssl 2>/dev/null; pkill -x sysbench 2>/dev/null
pkill -f "[t]urbostat --quiet --Summary --interval 5" 2>/dev/null
rm -f /run/ryuji-maxbench.phase
if ! systemctl is-active --quiet ryuji-fan-guard; then
  BMC_PWFILE=/root/.bmc-pass BMC_USER=root python3 -W ignore /var/tmp/gbt-fan-offset.py 10.0.0.118 set -80 >/dev/null 2>&1
  systemctl start ryuji-fan-guard
fi
echo "$(date '+%F %T %Z') maxbench restore: load killed, guard $(systemctl is-active ryuji-fan-guard)" >> /var/tmp/ryuji-maxbench-restore.log
