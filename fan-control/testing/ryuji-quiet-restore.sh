#!/bin/sh
# ExecStopPost for ryuji-quiet (copy of ryuji-profile-restore.sh): stop any leftover load and hand control back to ryuji-fan-guard. The guard puts
# -80 back by itself on its first check if the BMC is at a non-guard offset (-61, -31), holds Full (127) or
# Performance (0) until things have been cool for its hold time, so no BMC call is needed here.
pkill -x stress-ng-cpu 2>/dev/null; pkill -x stress-ng 2>/dev/null
systemctl start ryuji-fan-guard
echo "$(date '+%F %T %Z') restore: load killed, guard $(systemctl is-active ryuji-fan-guard)" >> /var/tmp/ryuji-quiet-restore.log
