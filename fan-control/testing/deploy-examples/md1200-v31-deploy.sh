#!/bin/bash
# md1200-v31-deploy: replace md1200-fan v3 with v3.1 (slower nudges, see its header), watch 45 min at idle, roll back
# to v3 automatically if it misbehaves (Rohit: "deploy after validating each one live at idle").
# Log: /var/tmp/md1200-v31-deploy.log
LOG=/var/tmp/md1200-v31-deploy.log; NEW=/var/tmp/md1200-fan.v3.1; CUR=/usr/local/bin/md1200-fan
BAK=/usr/local/bin/md1200-fan.bak-2026-10-06-v3
exec >>"$LOG" 2>&1
echo "$(date '+%F %T') start"
python3 -m py_compile "$NEW" || { echo "v3.1 does not compile; not deploying"; exit 1; }
cp -p "$CUR" "$BAK" && install -m 755 -o root -g root "$NEW" "$CUR" && systemctl restart md1200-fan \
  || { echo "$(date '+%F %T') install failed; restoring"; cp -p "$BAK" "$CUR"; systemctl restart md1200-fan; exit 1; }
echo "$(date '+%F %T') v3.1 installed and started (v3 saved as $BAK)"
start=$(date +%s); bad=""
while [ $(( $(date +%s) - start )) -lt 2700 ]; do
  sleep 60
  systemctl is-active --quiet md1200-fan || { bad="service not active"; break; }
  r=$(systemctl show -p NRestarts --value md1200-fan); [ "${r:-0}" -gt 2 ] && { bad="restarted $r times"; break; }
  j=$(journalctl -u md1200-fan --since "@$start" -o cat)
  grep -q 'not sending fan commands' <<<"$j" && { bad="the cabled EMM is not the primary"; break; }
  n_err=$(grep -cE 'serial error|^error' <<<"$j"); [ "$n_err" -gt 10 ] && { bad="$n_err errors"; break; }
  n_take=$(grep -c 'takeover' <<<"$j"); [ "$n_take" -gt 10 ] && { bad="$n_take takeovers"; break; }
  n_chg=$(grep -c '^fan ' <<<"$j"); [ "$n_chg" -gt 12 ] && { bad="$n_chg speed changes (hunting)"; break; }
  echo "$(date '+%T') $(cat /run/md1200-fan.state 2>/dev/null)"
done
if [ -n "$bad" ]; then
  echo "$(date '+%F %T') ROLLBACK: $bad"; cp -p "$BAK" "$CUR" && systemctl restart md1200-fan; exit 1; fi
echo "$(date '+%F %T') v3.1 OK after 45 min at idle; keeping it"
