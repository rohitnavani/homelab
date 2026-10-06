#!/bin/bash
# Offline tests for fan-watchdog: runs a fast-clock copy (0.2 s loop, 2 s cool-down) against stubbed ipmitool,
# smartctl, setpci, lspci and lsblk (tests/bin), and prints the fan commands it sent in each scenario.
# drive.py: idle, high and full load, emergency, DIMM, sensor failure, stop. drive_flip.py: CPU reading flipping
# 81/82C at full load (should hold one speed). drive_floor.py: long enough to reach the 10% idle floor.
# usage: tests/run-tests.sh [path to fan-watchdog]   (default: ../fan-watchdog). Takes about 2 minutes.
set -e
D=$(cd "$(dirname "$0")" && pwd); SRC=${1:-$D/../fan-watchdog}
export WD_DIR=$D
sed -e 's/^\(MIN_PCT=[0-9]*; MAX_PCT=[0-9]*; \)INTERVAL=30;/\1INTERVAL=0.2;/' -e 's/COOL_SECS=300/COOL_SECS=2/' \
    -e "s#/run/fan-watchdog.state#$D/state#g" "$SRC" > "$D/fw-test"
chmod +x "$D/fw-test"
for t in drive drive_flip drive_floor; do echo "## $t"; python3 -I "$D/$t.py" "$D"; done
