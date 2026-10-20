#!/bin/sh
# run-step NAME SCHEDULE [fanstep args]: one schedule as the transient unit makoto-fanstep-NAME, data in ../data/NAME.csv
set -e
D=$(cd "$(dirname "$0")/.." && pwd)
n=$1 s=$2; shift 2
exec systemd-run --unit="makoto-fanstep-$n" --description="makoto fan test $n" \
  --property=ExecStopPost="$D/tools/restore.sh" --property=TimeoutStopSec=30 \
  /usr/bin/python3 -I "$D/tools/fanstep.py" "$D/tools/$s" "$D/data/$n.csv" "$@"
