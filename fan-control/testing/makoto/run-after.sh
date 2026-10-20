#!/bin/sh
# run-after PREV NAME SCHEDULE [fanstep args]: like run-step, but the unit first waits for makoto-fanstep-PREV to end
set -e
D=$(cd "$(dirname "$0")/.." && pwd)
p=$1 n=$2 s=$3; shift 3
exec systemd-run --unit="makoto-fanstep-$n" --description="makoto fan test $n (after $p)" \
  --property=ExecStopPost="$D/tools/restore.sh" --property=TimeoutStopSec=30 \
  /bin/sh -c "while systemctl is-active -q makoto-fanstep-$p; do sleep 10; done; exec /usr/bin/python3 -I $D/tools/fanstep.py $D/tools/$s $D/data/$n.csv $*"
