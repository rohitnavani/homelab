#!/bin/bash
# map-test: which 0x3a 0x01 byte drives which fan, and does all-zeros give the fans back to the BMC. Attended, ~75 s.
set -uo pipefail
M=$(dirname "$0")/mfan
OUT=${1:-/dev/null}
trap '$M auto >/dev/null; echo "restored: $($M get)"' EXIT
rd() {  # epoch phase FAN1 FAN4 coretemp
  local r t
  r=$(ipmitool sensor reading FAN1 FAN4 2>/dev/null | awk -F'|' '{gsub(/ /,"",$2); printf "%s ", $2}')
  t=$(( $(cat /sys/class/hwmon/hwmon1/temp1_input) / 1000 ))
  echo "$(date +%s) $1 $r$t" | tee -a "$OUT"
  [ "$t" -lt 85 ] || { echo "CPU $t C, stopping"; exit 1; }
}
step() { local n=$1 ph=$2; for _ in $(seq "$n"); do rd "$ph"; sleep 0.6; done; }
step 5 base
echo "set: $($M set8 0 0 0 40 0 0 0 0)"; step 14 b4_40
echo "auto: $($M auto)"; step 14 auto1
echo "set: $($M set8 40 0 0 0 0 0 0 0)"; step 14 b1_40
echo "auto: $($M auto)"; step 16 auto2
