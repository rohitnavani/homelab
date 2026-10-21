#!/bin/bash
# prove-fallbacks (2026-10-20, run on makoto after install-units.sh): proves once per unit type that stopping a test
# unit puts production back. Quiet before 07:00: only each tool's first phase runs (R720 or shelf 10%, ryuji -80, no
# load); lab-load gets 1 worker. Real units where the first phase is quiet; transient units (systemd-run) for lab-load,
# lr-cut, pdu-cut and the backstop, against a dummy sleep unit. Each proof's CSV/phase files are renamed *.proof.
# usage: [HOLD=s] prove-fallbacks.sh <name> ...   names: r720 shelf notch ryuji msteps soak-sojiro soak-shelf soak-int
#                                                 labload lrcut pducut backstop
HOLD=${HOLD:-40}; LH=${LH:-futaba}   # LH: the lab-load proof host
r() { ssh -o BatchMode=yes "$1" "$2"; }
proof() {   # host unit 'check' 'files to set aside (globs in /var/tmp)' [start command] [hold]
  local h=$1 u=$2 chk=$3 files=$4 start=${5:-"sudo -n systemctl start --no-block $2"} hold=${6:-$HOLD}
  echo "== $(date +%T) $h $u: start"
  r $h "$start" >/dev/null
  sleep "$hold"
  echo "-- running: $(r $h "systemctl is-active $u; $chk" 2>&1 | tr '\n' ' ')"
  r $h "sudo -n systemctl stop $u"; sleep 8
  echo "-- stopped: $(r $h "systemctl is-active $u; $chk" 2>&1 | tr '\n' ' ')"
  [ -n "$files" ] && echo "-- set aside: $(r $h "cd /var/tmp && for f in $files; do [ -e \"\$f\" ] && sudo -n mv \"\$f\" \"\$f.proof\"; done; ls -d $files.proof 2>/dev/null" | tr '\n' ' ')"
}
FW='echo fw=$(systemctl is-active fan-watchdog) md=$(systemctl is-active md1200-fan); tail -c 100 /run/fan-watchdog.state'
DUMMY='sudo -n systemd-run --collect --unit=%s -p RuntimeMaxSec=600 /bin/sleep 600'
for p in "$@"; do case $p in
  r720)  proof mementos mic-r720-proof-1020.service "$FW; tail -1 /var/tmp/noise-sweep-restore.log" 'noise-sweep-t1a1020*' ;;
  shelf) proof mementos mic-shelf-sweep-1020.service "$FW; tail -1 /var/tmp/noise-sweep-restore.log" 'noise-sweep-t1bshelf1020*' ;;
  notch) proof mementos mic-r720-notch-1020.service "$FW; tail -1 /var/tmp/r720-notch-restore.log" 'r720-notch-t1bnotch1020*' ;;
  ryuji) proof ryuji ryuji-floor-idleoff-1020.service 'echo guard=$(systemctl is-active ryuji-fan-guard); tail -c 120 /run/ryuji-fan-guard.state' 'ryuji-profile-idleoff1020*' ;;
  msteps) proof mementos mementos-steps-t4-1020.service "$FW; echo stress=\$(pgrep -c -x stress-ng)" 'mementos-steps-t41020*' ;;
  soak-sojiro) proof sojiro lab-soak-n1b-sojiro.service 'echo fio=$(pgrep -c -x fio)' '*n1bsojiro*' ;;
  soak-shelf) proof mementos scrub-quiet-soak-n1b-shelf.service 'echo fio=$(pgrep -c -x fio)' '*n1bshelf*' ;;
  soak-int) proof mementos scrub-quiet-soak-n1b-int.service 'echo fio=$(pgrep -c -x fio)' '*n1bint*' ;;
  labload)
    until=$(date -d '+5 min' '+%F %H:%M')
    r $LH "printf '%s\n' '{\"$LH\": [{\"name\": \"proof\", \"cpu\": 1, \"min\": 3, \"until\": \"$until\"}]}' > /tmp/lab-load-plan-proof.json && sudo -n install -m 644 /tmp/lab-load-plan-proof.json /var/tmp/lab-load-plan-proof.json"
    proof $LH lab-load-proof-1020.service 'echo stress=$(pgrep -c -x stress-ng)' 'lab-load*proof*' \
      "sudo -n systemd-run --collect --unit=lab-load-proof-1020 -p RuntimeMaxSec=300 -E LOAD_UNTIL=$(date -d '+5 min' +%s) /usr/bin/python3 -I /var/tmp/lab-load-1020.py proof /var/tmp/lab-load-profile.json /var/tmp/lab-load-plan-proof.json" ;;
  lrcut)
    r ryuji "$(printf "$DUMMY" ryuji-floor-proofdummy)" >/dev/null
    proof ryuji lr-cut-proof-1020.service 'echo dummy=$(systemctl is-active ryuji-floor-proofdummy); tail -2 /var/tmp/lr-cut-proof-1020.csv' 'lr-cut-proof-1020*' \
      "sudo -n systemd-run --collect --unit=lr-cut-proof-1020 -p RuntimeMaxSec=300 -E LIMIT=1.0 -E LOG=/var/tmp/lr-cut-proof-1020.csv -E UNITS=ryuji-floor-proofdummy.service /usr/bin/python3 -I /var/tmp/lr-cut-1020.py" 90
    r ryuji 'sudo -n systemctl stop ryuji-floor-proofdummy 2>/dev/null' ;;
  pducut)
    r sojiro "$(printf "$DUMMY" pdu-cut-proof-dummy)" >/dev/null
    proof sojiro pdu-cut-proof-1020.service 'echo dummy=$(systemctl is-active pdu-cut-proof-dummy); tail -2 /var/tmp/pdu-cut-proof-1020.log' 'pdu-cut-proof-1020*' \
      "sudo -n systemd-run --collect --unit=pdu-cut-proof-1020 -p RuntimeMaxSec=300 -E LIMIT=10 -E LOG=/var/tmp/pdu-cut-proof-1020.log -E UNITS=pdu-cut-proof-dummy.service /bin/bash /var/tmp/pdu-cut.sh" 150
    r sojiro 'sudo -n systemctl stop pdu-cut-proof-dummy 2>/dev/null' ;;
  backstop)
    r futaba "$(printf "$DUMMY" lab-load-proofdummy)" >/dev/null
    echo "== $(date +%T) futaba backstop: $(r futaba 'sudo -n /bin/sh /var/tmp/lab-loadoff-1020.sh; echo dummy=$(systemctl is-active lab-load-proofdummy); tail -2 /var/tmp/lab-loadoff-1020.log' | tr '\n' ' ')"
    echo "== $(date +%T) mementos backstop: $(r mementos 'sudo -n /bin/sh /var/tmp/lab-loadoff-1020.sh; tail -2 /var/tmp/lab-loadoff-1020.log' | tr '\n' ' ')" ;;
  *) echo "unknown proof $p" ;;
esac; done
