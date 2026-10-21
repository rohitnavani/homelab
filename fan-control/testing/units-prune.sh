#!/bin/sh
# units-prune (2026-10-20): run by install-units.sh on each host before it installs that host's units. Removes this
# run's units (Description "lab thermal run 10-20") that are not in the new set given as arguments: stale timers are
# disabled and removed, stale services removed unless running (then only a warning). An older install had left E2
# armed after make-units dropped it (REVIEW-CHAIN-2).
# usage: units-prune.sh <unit file name> ...
cd /etc/systemd/system || exit 1
keep=" $* "
for f in $(grep -l '^Description=lab thermal run 10-20' *.service *.timer 2>/dev/null); do
  case "$keep" in *" $f "*) continue ;; esac
  case $f in
    *.timer) systemctl disable --now "$f" >/dev/null 2>&1; rm -f "$f"; echo "pruned $f" ;;
    *.service) if systemctl is-active --quiet "$f"; then echo "STALE BUT RUNNING, kept: $f"; else rm -f "$f"; echo "pruned $f"; fi ;;
  esac
done
systemctl daemon-reload
