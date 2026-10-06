#!/bin/sh
# ExecStopPost for mementos-steps: no leftover load, stock RAPL limits (PL1 130 W, PL2 156 W per socket).
pkill -x stress-ng-cpu 2>/dev/null; pkill -x stress-ng 2>/dev/null
for z in /sys/class/powercap/intel-rapl:0 /sys/class/powercap/intel-rapl:1; do
  echo 130000000 > $z/constraint_0_power_limit_uw; echo 156000000 > $z/constraint_1_power_limit_uw
done
echo "$(date '+%F %T') restored: PL1 $(cat /sys/class/powercap/intel-rapl:0/constraint_0_power_limit_uw) / $(cat /sys/class/powercap/intel-rapl:1/constraint_0_power_limit_uw)" >> /var/tmp/mementos-steps-restore.log
