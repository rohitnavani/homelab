#!/bin/bash
# pdu-cut (2026-10-13): companion of the combined full-load test. Every 15 s it reads the rack PDU's current from
# Prometheus (SNMP GET by futaba, 30 s); at LIMIT deciamps or more on 2 fresh samples in a row, or with no fresh sample
# (older than 3 min) for 2 checks, it kills this host's test load (stress-ng, fio) and stops the test units (since 10-20 it latches and keeps running, below).
# Rohit 10-13: 20 A circuit, nothing else on it, but the PDU's NEMA 5-20 plug reaches a normal 15 A outlet through a
# cheap adapter, so the cut sits at 14.0 A, under the adapter's 15 A rating. Run as root, one per host:
#   systemd-run --unit=pdu-cut-<x> -p RuntimeMaxSec=<s> --setenv=UNITS='<unit globs>' bash /var/tmp/pdu-cut.sh
LIMIT=${LIMIT:-140}; LIMIT12=${LIMIT12:-120}; LOG=${LOG:-/var/tmp/pdu-cut.log}; UNITS=${UNITS:-}
# 2026-10-20 04:20 (REVIEW-PLAN-1 B1): an over-current cut latches (LOG's .tripped file keeps it across a restart) and the loop
# keeps running, stopping every matching unit that is active or still starting on each check, so a gated unit that
# starts later cannot run; and LIMIT12 (12.0 A, the circuit's continuous ceiling) held for 5 min also cuts.
# 2026-10-20: an empty UNITS would make the list below every active service on the host: refuse to run.
[ -n "$UNITS" ] || { echo "$(date '+%F %T') pdu-cut: UNITS empty, refusing to run" >> "$LOG"; exit 2; }
Q='http://10.0.0.3:9090/api/v1/query?query='$(python3 -I -c 'import urllib.parse; print(urllib.parse.quote("cyberpower_pdu_bank_load_deciamps{bank=\"1\"} and on() (time() - timestamp(cyberpower_pdu_bank_load_deciamps{bank=\"1\"}) < 180)"))')
stop_all() {   # $1: the unit states to stop (active = loading; active,activating = also units waiting in their gates)
  for u in $(systemctl list-units --type=service --state=$1 --no-legend --plain $UNITS | awk '{print $1}'); do
    systemctl stop --no-block "$u" && echo "$(date '+%T') stopped $u" >> "$LOG"
  done
}
cut() {   # over-current: latched for the rest of the window; the host-wide load kill runs once, at the trip, so a
          # latched cut does not keep killing a later window's load on this host (REVIEW-WED-1)
  if [ $tripped = 0 ]; then
    echo "$(date '+%F %T') CUT: $1" >> "$LOG"; touch "$TRIP"; tripped=1
    stop_all active,activating; pkill -x stress-ng-cpu; pkill -x stress-ng; pkill -x fio
  else
    stop_all active,activating
  fi
}
TRIP=${LOG%.log}.tripped; tripped=0; [ -e "$TRIP" ] && tripped=1
echo "$(date '+%F %T') pdu-cut start, limit ${LIMIT} dA (${LIMIT12} dA for 5 min), tripped=$tripped, units: ${UNITS}" >> "$LOG"
over=0; over12=0; stale=0
while :; do
  v=$(curl -s -m 10 "$Q" | python3 -I -c 'import json,sys; r=json.load(sys.stdin)["data"]["result"]; print(r[0]["value"][1] if r else "")' 2>/dev/null)
  if [ -z "$v" ]; then
    stale=$((stale+1)); echo "$(date '+%T') no fresh PDU sample ($stale)" >> "$LOG"
    # blind: loading units stop while no reading is fresh, without latching (REVIEW-CHAIN-2); units still waiting in
    # their gates are left alone (REVIEW-WED-1), and any that starts loading while still blind is stopped at the next check
    if [ $stale -ge 2 ]; then [ $stale = 2 ] && echo "$(date '+%F %T') BLIND: no fresh PDU reading for 2 checks, load stopped" >> "$LOG"; stop_all active; fi
  else
    stale=0
    v=${v%.*}
    if [ "$v" -ge "$LIMIT" ]; then over=$((over+1)); else over=0; fi
    if [ "$v" -ge "$LIMIT12" ]; then over12=$((over12+1)); else over12=0; fi
    echo "$(date +%s),$(date '+%T'),$v,$over,$over12" >> "$LOG"
    [ $over -ge 2 ] && cut "PDU ${v} dA >= ${LIMIT} on 2 samples"
    [ $over12 -ge 20 ] && cut "PDU >= ${LIMIT12} dA for 20 checks (5 min)"
  fi
  [ $tripped = 1 ] && cut latched
  sleep 15
done
