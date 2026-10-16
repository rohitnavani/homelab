#!/bin/sh
# sojiro-gate (2026-10-14): ExecStartPre of sojiro-floor-fin. Waits until sojiro has been up 5 min (it may have just come
# back from its drive swap), refuses (exit 1) once past the not-after epoch ($1).
na=$1
while :; do
  now=$(date +%s); [ "$now" -gt "$na" ] && { echo "past not-after $(date -d @$na +%T): refusing"; exit 1; }
  up=$(cut -d. -f1 /proc/uptime); [ "$up" -ge 300 ] && { echo "go at $(date +%T) (up ${up}s)"; exit 0; }
  sleep 10
done
