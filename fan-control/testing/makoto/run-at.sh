#!/bin/sh
# run-at 'YYYY-MM-DD HH:MM' STOPUNIT NAME SCHEDULE [fanstep args]: a unit makoto-fanstep-NAME that waits for the time,
# then stops STOPUNIT (a full unit name, e.g. makoto-fan-test.service, or '-'), waits for it to end and runs the schedule
set -e
D=$(cd "$(dirname "$0")/.." && pwd)
at=$1 stop=$2 n=$3 s=$4; shift 4
when=$(date -d "$at" +%s)
exec systemd-run --unit="makoto-fanstep-$n" --description="makoto fan test $n (from $at)" \
  --property=ExecStopPost="$D/tools/restore.sh" --property=TimeoutStopSec=30 \
  /bin/sh -c "while [ \$(date +%s) -lt $when ]; do sleep 15; done; [ '$stop' = - ] || systemctl stop '$stop'; while [ '$stop' != - ] && systemctl is-active -q '$stop'; do sleep 5; done; exec /usr/bin/python3 -I $D/tools/fanstep.py $D/tools/$s $D/data/$n.csv $*"
