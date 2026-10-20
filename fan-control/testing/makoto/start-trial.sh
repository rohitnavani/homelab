#!/bin/sh
# start-trial [hours]: run the working copy of makoto-fan as unit makoto-fan-test (restarts on a crash; any stop hands
# the fans to the BMC via restore.sh) and watch it with makoto-fan-watch (stops it on trouble)
set -e
D=$(cd "$(dirname "$0")/.." && pwd)
H=${1:-14}
systemd-run --unit=makoto-fan-test --description="makoto-fan trial (working copy)" \
  --property=ExecStopPost="$D/tools/restore.sh" --property=Restart=on-failure --property=RestartSec=30 \
  /usr/bin/python3 -W ignore "$D/makoto-fan/makoto-fan"
systemd-run --unit=makoto-fan-watch --description="watch makoto-fan-test" "$D/tools/fan-watch.sh" makoto-fan-test "$H"
