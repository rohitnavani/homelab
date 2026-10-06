#!/bin/bash
# fan-watchdog-v42-deploy: replace fan-watchdog v4.1 with v4.2 (completes the last step to the idle floor), 10 min idle watch, roll back to v4.1 on
# a crash loop, a sensor/IPMI failure or any switch to iDRAC auto. A short load
# check: none needed (only the step to the idle floor changed). Log: /var/tmp/fan-watchdog-v42-deploy.log
LOG=/var/tmp/fan-watchdog-v42-deploy.log; NEW=/var/tmp/fan-watchdog.v4.2; CUR=/usr/local/sbin/fan-watchdog
BAK=/usr/local/sbin/fan-watchdog.bak-2026-10-06-v4.1
exec >>"$LOG" 2>&1
echo "$(date '+%F %T') start"
bash -n "$NEW" || { echo "v4.2 has a syntax error; not deploying"; exit 1; }
cp -p "$CUR" "$BAK" && install -m 755 -o root -g root "$NEW" "$CUR" && systemctl restart fan-watchdog \
  || { echo "$(date '+%F %T') install failed; restoring"; cp -p "$BAK" "$CUR"; systemctl restart fan-watchdog; exit 1; }
echo "$(date '+%F %T') v4.2 installed and started (v4.1 saved as $BAK)"
start=$(date +%s); bad=""
while [ $(( $(date +%s) - start )) -lt 600 ]; do
  sleep 30
  systemctl is-active --quiet fan-watchdog || { bad="service not active"; break; }
  r=$(systemctl show -p NRestarts --value fan-watchdog); [ "${r:-0}" -gt 2 ] && { bad="restarted $r times"; break; }
  j=$(journalctl -u fan-watchdog --since "@$start" -o cat)
  grep -qE 'failed|^hot .*: auto$' <<<"$j" && { bad="$(grep -E 'failed|^hot .*: auto$' <<<"$j" | head -1)"; break; }
  echo "$(date '+%T') $(cat /run/fan-watchdog.state 2>/dev/null)"
done
if [ -n "$bad" ]; then
  echo "$(date '+%F %T') ROLLBACK: $bad"; cp -p "$BAK" "$CUR" && systemctl restart fan-watchdog; exit 1; fi
echo "$(date '+%F %T') v4.2 OK after 10 min at idle; keeping it"
