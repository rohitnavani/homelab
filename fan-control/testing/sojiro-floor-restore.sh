#!/bin/sh
# ExecStopPost for sojiro-floor: back to production, offset -80 (since 2026-10-15), whatever state the test ended in,
# checked by the BMC's read-back ("now -80"). The address comes from sojiro-bmc-ip (lan print now, checked by MAC and
# ARP; 3 tries). With no checked address, or after a failed BMC login (/run/sojiro-bmc-login-failed), nothing is sent
# and it exits 1. Log: /var/tmp/sojiro-floor-restore.log
PROD=-80 LOG=/var/tmp/sojiro-floor-restore.log FAILED=/run/sojiro-bmc-login-failed
log(){ echo "$(date '+%F %T') restore: $*" >> "$LOG"; }
[ -e "$FAILED" ] && { log "skipped: a BMC login failed earlier ($FAILED); offset NOT restored"; exit 1; }
for try in 1 2 3; do
  ip=$(/usr/local/sbin/sojiro-bmc-ip 2>>"$LOG") && break
  ip=; [ "$try" -lt 3 ] && sleep 5
done
case $ip in ''|*[!0-9.]*) log "no checked BMC address after 3 tries; offset NOT restored"; exit 1 ;; esac
r=$(env BMC_USER=root BMC_PWFILE=/root/.bmc-pass python3 -W ignore /var/tmp/gbt-fan-offset.py "$ip" set $PROD 2>&1 | tail -1)
case $r in *"login failed"*) echo "$(date '+%F %T') sojiro-floor-restore: $r" > "$FAILED" ;; esac
case $r in *"now $PROD "*) log "$ip: $r"; exit 0 ;; esac
log "$ip: FAILED: $r"; exit 1
