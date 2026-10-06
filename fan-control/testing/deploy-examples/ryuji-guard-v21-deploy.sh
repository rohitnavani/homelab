#!/bin/bash
# ryuji-guard-v21-deploy: replace ryuji-fan-guard v2 with v2.1 (SIO_BACK_HOT 68 -> 71), watch 20 min,
# roll back to v2 automatically on a crash loop, repeated BMC errors or flapping. Log: /var/tmp/ryuji-guard-v21-deploy.log
LOG=/var/tmp/ryuji-guard-v21-deploy.log; NEW=/var/tmp/ryuji-fan-guard.v2.1; CUR=/usr/local/sbin/ryuji-fan-guard
BAK=/usr/local/sbin/ryuji-fan-guard.bak-2026-10-06-v2
exec >>"$LOG" 2>&1
echo "$(date '+%F %T') start"
python3 -m py_compile "$NEW" || { echo "v2.1 does not compile; not deploying"; exit 1; }
cp -p "$CUR" "$BAK" && install -m 755 -o root -g root "$NEW" "$CUR" && systemctl restart ryuji-fan-guard \
  || { echo "$(date '+%F %T') install failed; restoring"; cp -p "$BAK" "$CUR"; systemctl restart ryuji-fan-guard; exit 1; }
echo "$(date '+%F %T') v2.1 installed and started (v2 saved as $BAK)"
start=$(date +%s); bad=""
while [ $(( $(date +%s) - start )) -lt 1200 ]; do
  sleep 60
  systemctl is-active --quiet ryuji-fan-guard || { bad="service not active"; break; }
  r=$(systemctl show -p NRestarts --value ryuji-fan-guard); [ "${r:-0}" -gt 2 ] && { bad="restarted $r times"; break; }
  j=$(journalctl -u ryuji-fan-guard --since "@$start" -o cat)
  n_err=$(grep -cE 'failed|Traceback|Error' <<<"$j"); [ "$n_err" -gt 3 ] && { bad="$n_err errors"; break; }
  n_chg=$(grep -cE '^offset .* -> ' <<<"$j"); [ "$n_chg" -gt 6 ] && { bad="$n_chg offset changes (flapping)"; break; }
  echo "$(date '+%T') $(cat /run/ryuji-fan-guard.state 2>/dev/null)"
done
if [ -n "$bad" ]; then
  echo "$(date '+%F %T') ROLLBACK: $bad"; cp -p "$BAK" "$CUR" && systemctl restart ryuji-fan-guard; exit 1; fi
echo "$(date '+%F %T') v2.1 OK after 20 min; keeping it"
