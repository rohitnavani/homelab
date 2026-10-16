#!/bin/sh
# ExecStopPost for sojiro-floor: offset 0 (the BMC's default curve) whatever state the test ended in.
r=$(env BMC_USER=root BMC_PWFILE=/root/.bmc-pass python3 -W ignore /var/tmp/gbt-fan-offset.py 10.0.0.14 set 0 2>&1 | tail -1)
echo "$(date '+%F %T') restore: $r" >> /var/tmp/sojiro-floor-restore.log
