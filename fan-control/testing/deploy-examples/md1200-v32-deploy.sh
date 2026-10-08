#!/bin/bash
# md1200-v32-deploy (2026-10-08): replace md1200-fan v3.1 with v3.2 (50C target, paced urgent steps, faster easing when
# far below target, SES device by type), watch 45 min, roll back to v3.1 automatically if it misbehaves.
# Log: /var/tmp/md1200-v32-deploy.log
LOG=/var/tmp/md1200-v32-deploy.log; NEW=/var/tmp/md1200-fan.v3.2; CUR=/usr/local/bin/md1200-fan
BAK=/usr/local/bin/md1200-fan.bak-2026-10-08-v3.1
exec >>"$LOG" 2>&1
echo "$(date '+%F %T') start"
python3 -m py_compile "$NEW" || { echo "v3.2 does not compile; not deploying"; exit 1; }
cp -p "$CUR" "$BAK" && install -m 755 -o root -g root "$NEW" "$CUR" && systemctl restart md1200-fan \
  || { echo "$(date '+%F %T') install failed; restoring"; cp -p "$BAK" "$CUR"; systemctl restart md1200-fan; exit 1; }
echo "$(date '+%F %T') v3.2 installed and started (v3.1 saved as $BAK)"
start=$(date +%s); bad=""
while [ $(( $(date +%s) - start )) -lt 2700 ]; do
  sleep 60
  systemctl is-active --quiet md1200-fan || { bad="service not active"; break; }
  r=$(systemctl show -p NRestarts --value md1200-fan); [ "${r:-0}" -gt 2 ] && { bad="restarted $r times"; break; }
  j=$(journalctl -u md1200-fan --since "@$start" -o cat)
  grep -q 'starting (v3.2, SES /dev/sg' <<<"$j" || { bad="no v3.2 start line"; break; }
  grep -q 'not sending fan commands' <<<"$j" && { bad="the cabled EMM is not the primary"; break; }
  n_err=$(grep -cE 'serial error|^error' <<<"$j"); [ "$n_err" -gt 10 ] && { bad="$n_err errors"; break; }
  n_take=$(grep -c 'takeover' <<<"$j"); [ "$n_take" -gt 10 ] && { bad="$n_take takeovers"; break; }
  n_chg=$(grep -c '^fan ' <<<"$j"); [ "$n_chg" -gt 12 ] && { bad="$n_chg speed changes (hunting)"; break; }
  grep -q 'urgent' <<<"$j" && { bad="an urgent step at idle"; break; }
  echo "$(date '+%T') $(cat /run/md1200-fan.state 2>/dev/null)"
done
if [ -n "$bad" ]; then
  echo "$(date '+%F %T') ROLLBACK: $bad"; cp -p "$BAK" "$CUR" && systemctl restart md1200-fan; exit 1; fi
echo "$(date '+%F %T') v3.2 OK after 45 min at idle; keeping it"
