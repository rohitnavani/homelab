#!/bin/bash
# install-units (2026-10-20, run on makoto): installs the 10-20/21 thermal run on its hosts. For each host given (or all):
# copies that host's scripts to /var/tmp (names as the units use them), copies units/<host>/* to /etc/systemd/system,
# daemon-reload, and enables (starts) every timer. Prints each host's md5s and `systemctl list-timers` for the run.
# usage: install-units.sh [--dry] [host ...]
# Never touches makoto. Scripts come from ~/lab-thermal-2026-10-20/scripts (working copies, md5s logged).
S=~/lab-thermal-2026-10-20/scripts
U=~/lab-thermal-2026-10-20/units
DRY=0; [ "$1" = --dry ] && { DRY=1; shift; }
HOSTS=${*:-mementos ryuji sojiro futaba morgana yusuke tinynas tinypc}
# source in scripts/ : name in /var/tmp
declare -A COMMON=( [fin-gate.py]=fin-gate-1020.py [lab-loadoff-1020.sh]=lab-loadoff-1020.sh [restore-guard.sh]=restore-guard.sh [units-prune.sh]=units-prune.sh )
files_for() {
  local LL="lab-load.py:lab-load-1020.py lab-load/lab-load-profile.json:lab-load-profile.json" DS=disk-soak.py:disk-soak-1020.py
  local P3=lab-load/lab-load-plan-t3.json:lab-load-plan-t3.json P4=lab-load/lab-load-plan-t4.json:lab-load-plan-t4.json
  local PW=lab-load/lab-load-plan-w1.json:lab-load-plan-w1.json
  case $1 in
    mementos) echo "mementos-steps.py:mementos-steps-1020.py mementos-steps-restore-fin.sh:mementos-steps-restore-fin.sh
      $DS pdu-cut.sh:pdu-cut.sh wait-no-backup.sh:wait-no-backup.sh noise-sweep.py:noise-sweep-1020.py
      noise-sweep-restore.sh:noise-sweep-restore.sh r720-notch-sweep.py:r720-notch-sweep-1020.py r720-notch-restore.sh:r720-notch-restore.sh" ;;
    ryuji) echo "ryuji-floor.py:ryuji-floor-1020.py ryuji-profile-restore.sh:ryuji-profile-restore.sh
      room-feed-local.sh:room-feed-local.sh lr-cut.py:lr-cut-1020.py $DS" ;;
    sojiro) echo "sojiro-floor-1020.py:sojiro-floor-1020.py sojiro-floor-restore.sh:sojiro-floor-restore.sh
      gbt-fan-offset.py:gbt-fan-offset.py $DS pdu-cut.sh:pdu-cut.sh wait-no-backup.sh:wait-no-backup.sh $LL $P3 $PW" ;;
    futaba|morgana|yusuke) echo "$LL $P3 $PW" ;;
    tinynas) echo "$LL $P3 $PW $DS" ;;
    tinypc) echo "$LL $P4 $PW" ;;
  esac
}
for h in $HOSTS; do
  [ "$h" = makoto ] && { echo "refusing makoto"; continue; }
  echo "== $h"
  list="$(for k in "${!COMMON[@]}"; do echo "$k:${COMMON[$k]}"; done) $(files_for $h)"
  stage=$(mktemp -d /home/rohit/.claude/jobs/a97f44b1/tmp/stage-$h.XXXX)
  ok=1
  for pair in $list; do
    src=${pair%%:*}; dst=${pair##*:}
    [ -f "$S/$src" ] || { echo "  MISSING $S/$src"; ok=0; continue; }
    cp "$S/$src" "$stage/$dst"
  done
  [ $ok = 1 ] || { echo "  $h: not installed (missing files)"; continue; }
  chmod 755 "$stage"/*.sh "$stage"/*.py 2>/dev/null; chmod 644 "$stage"/*.json 2>/dev/null   # tar carries the modes
  units=$(ls "$U/$h" 2>/dev/null)
  ( cd "$stage" && md5sum * | sed 's/^/  /' | cut -c1-12,34- )
  if [ $DRY = 1 ]; then echo "  dry: would install $(ls $stage | wc -l) files, $(echo $units | wc -w) unit files"; continue; fi
  timers=$(ls "$U/$h" | command grep '\.timer$' | tr '\n' ' ')
  # file names only, never ".": extracting "./" would reset /var/tmp's (1777) or /etc/systemd/system's mode
  tar -C "$stage" -cf - $(ls "$stage") | ssh -o BatchMode=yes "$h" "sudo -n tar -C /var/tmp --no-same-owner --no-overwrite-dir -xf -"
  # units this run no longer generates come off the host first (an older install had left E2 armed)
  ssh -o BatchMode=yes "$h" "sudo -n sh /var/tmp/units-prune.sh $(echo $units)" | sed 's/^/  /'
  tar -C "$U/$h" -cf - $units | ssh -o BatchMode=yes "$h" "sudo -n tar -C /etc/systemd/system --no-same-owner --no-overwrite-dir -xf - && sudo -n systemctl daemon-reload && sudo -n systemctl enable --now $timers >/dev/null 2>&1; systemctl list-timers --all --no-pager | command grep -F $(for t in $timers; do printf -- ' -e %s' $t; done) | sed 's/^/  /'"
done
