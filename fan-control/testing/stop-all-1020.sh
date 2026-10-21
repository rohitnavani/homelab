#!/bin/bash
# stop-all-1020 (run on makoto): stops the whole 10-20/21 thermal run. On every host the run uses it disables and stops
# every timer the run installed (they come from ~/lab-thermal-2026-10-20/units/<host>/), then runs that host's
# lab-loadoff-1020.sh backstop (stops test units, kills stress-ng/fio, production control back). Then stops the
# makoto-side samplers only with --samplers. Usage: stop-all-1020.sh [--samplers]
U=~/lab-thermal-2026-10-20/units
for h in mementos ryuji sojiro futaba morgana yusuke tinynas tinypc; do
  t=$(ls "$U/$h" 2>/dev/null | command grep '\.timer$' | tr '\n' ' ')
  echo "== $h: timers: ${t:-none}"
  ssh -o ConnectTimeout=10 -o BatchMode=yes "$h" "sudo -n systemctl disable --now $t 2>/dev/null; sudo -n sh /var/tmp/lab-loadoff-1020.sh; tail -3 /var/tmp/lab-loadoff-1020.log" || echo "!! $h unreachable"
done
if [ "$1" = --samplers ]; then
  sudo -n systemctl stop lab-thermal-miclevels lab-thermal-pisoc 2>/dev/null && echo "makoto samplers stopped"
fi
