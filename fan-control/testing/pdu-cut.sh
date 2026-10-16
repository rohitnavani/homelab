#!/bin/bash
# pdu-cut (2026-10-13): companion of the combined full-load test. Every 15 s it reads the rack PDU's current from
# Prometheus (SNMP GET by futaba, 30 s); at LIMIT deciamps or more on 2 fresh samples in a row, or with no fresh sample
# (older than 3 min) for 2 checks, it kills this host's test load (stress-ng, fio) and stops the test units, then exits.
# Rohit 10-13: 20 A circuit, nothing else on it, but the PDU's NEMA 5-20 plug reaches a normal 15 A outlet through a
# cheap adapter, so the cut sits at 14.0 A, under the adapter's 15 A rating. Run as root, one per host:
#   systemd-run --unit=pdu-cut-<x> -p RuntimeMaxSec=<s> --setenv=UNITS='<unit globs>' bash /var/tmp/pdu-cut.sh
LIMIT=${LIMIT:-140}; LOG=${LOG:-/var/tmp/pdu-cut.log}; UNITS=${UNITS:-}
Q='http://10.0.0.3:9090/api/v1/query?query='$(python3 -I -c 'import urllib.parse; print(urllib.parse.quote("cyberpower_pdu_bank_load_deciamps{bank=\"1\"} and on() (time() - timestamp(cyberpower_pdu_bank_load_deciamps{bank=\"1\"}) < 180)"))')
cut() {
  echo "$(date '+%F %T') CUT: $1" >> "$LOG"
  for u in $(systemctl list-units --type=service --state=active --no-legend --plain $UNITS | awk '{print $1}'); do
    systemctl stop "$u" && echo "$(date '+%T') stopped $u" >> "$LOG"
  done
  pkill -x stress-ng-cpu; pkill -x stress-ng; pkill -x fio
  exit 0
}
echo "$(date '+%F %T') pdu-cut start, limit ${LIMIT} dA, units: ${UNITS}" >> "$LOG"
over=0; stale=0
while :; do
  v=$(curl -s -m 10 "$Q" | python3 -I -c 'import json,sys; r=json.load(sys.stdin)["data"]["result"]; print(r[0]["value"][1] if r else "")' 2>/dev/null)
  if [ -z "$v" ]; then
    stale=$((stale+1)); echo "$(date '+%T') no fresh PDU sample ($stale)" >> "$LOG"
    [ $stale -ge 2 ] && cut "no fresh PDU reading for 2 checks"
  else
    stale=0
    v=${v%.*}
    if [ "$v" -ge "$LIMIT" ]; then over=$((over+1)); else over=0; fi
    echo "$(date +%s),$(date '+%T'),$v,$over" >> "$LOG"
    [ $over -ge 2 ] && cut "PDU ${v} dA >= ${LIMIT} on 2 samples"
  fi
  sleep 15
done
