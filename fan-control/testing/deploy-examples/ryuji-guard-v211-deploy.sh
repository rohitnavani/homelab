#!/bin/bash
# ryuji-guard-v211-deploy (2026-10-16): install ryuji-fan-guard v2.11 (md5 a3e517a3: HEAVY from 220 W, out under 200 W;
# one supply, plan fin_heavy1). Watch 20 min, roll back to
# v2.10 (8ecd2777) on a crash loop or errors. Log: /var/tmp/ryuji-guard-v211-deploy.log
LOG=/var/tmp/ryuji-guard-v211-deploy.log; NEW=/var/tmp/ryuji-fan-guard.v2.11
CUR=/usr/local/sbin/ryuji-fan-guard; BAK=/usr/local/sbin/ryuji-fan-guard.bak-2026-10-16-v2.10
exec >>"$LOG" 2>&1
echo "$(date '+%F %T') start"
[ "$(md5sum < "$NEW" | cut -c1-8)" = a3e517a3 ] || { echo "unexpected md5; not deploying"; exit 1; }
python3 -m py_compile "$NEW" || { echo "does not compile; not deploying"; exit 1; }
rm -rf /var/tmp/__pycache__
rollback() { cp -p "$BAK" "$CUR"; systemctl restart ryuji-fan-guard; }
cp -p "$CUR" "$BAK" && install -m 755 -o root -g root "$NEW" "$CUR" && systemctl restart ryuji-fan-guard \
  || { echo "$(date '+%F %T') install failed; restoring"; rollback; exit 1; }
echo "$(date '+%F %T') installed and started ($(md5sum $CUR | cut -c1-8); previous saved as $BAK)"
start=$(date +%s); bad=""
while [ $(( $(date +%s) - start )) -lt 1200 ]; do
  sleep 60
  systemctl is-active --quiet ryuji-fan-guard || { bad="service not active"; break; }
  r=$(systemctl show -p NRestarts --value ryuji-fan-guard); [ "${r:-0}" -gt 2 ] && { bad="restarted $r times"; break; }
  j=$(journalctl -u ryuji-fan-guard --since "@$start" -o cat)
  n_err=$(grep -cE 'failed|Traceback|Error' <<<"$j"); [ "$n_err" -gt 3 ] && { bad="$n_err errors"; break; }
  echo "$(date '+%T') $(cat /run/ryuji-fan-guard.state 2>/dev/null)"
done
if [ -n "$bad" ]; then echo "$(date '+%F %T') ROLLBACK: $bad"; rollback; exit 1; fi
echo "$(date '+%F %T') v2.11 OK after 20 min; keeping it"
