#!/bin/bash
# ryuji-guard-v22-deploy (2026-10-08): install ryuji-fan-guard v2.2 (unit: Wants=network-online.target so the guard's
# first BMC read at boot finds the network; script: see its header), watch 20 min, roll back script and unit to v2.1
# automatically on a crash loop, repeated BMC errors or flapping. Log: /var/tmp/ryuji-guard-v22-deploy.log
LOG=/var/tmp/ryuji-guard-v22-deploy.log; NEW=/var/tmp/ryuji-fan-guard.v2.2; NEWU=/var/tmp/ryuji-fan-guard.service.v2.2
CUR=/usr/local/sbin/ryuji-fan-guard; CURU=/etc/systemd/system/ryuji-fan-guard.service
BAK=/usr/local/sbin/ryuji-fan-guard.bak-2026-10-08-v2.1; BAKU=/etc/systemd/system/ryuji-fan-guard.service.bak-2026-10-08-v2.1
exec >>"$LOG" 2>&1
echo "$(date '+%F %T') start"
python3 -m py_compile "$NEW" || { echo "v2.2 does not compile; not deploying"; exit 1; }
rollback() { cp -p "$BAK" "$CUR"; cp -p "$BAKU" "$CURU"; systemctl daemon-reload; systemctl restart ryuji-fan-guard; }
cp -p "$CUR" "$BAK" && cp -p "$CURU" "$BAKU" && install -m 755 -o root -g root "$NEW" "$CUR" \
  && install -m 644 -o root -g root "$NEWU" "$CURU" && systemctl daemon-reload && systemctl restart ryuji-fan-guard \
  || { echo "$(date '+%F %T') install failed; restoring"; rollback; exit 1; }
echo "$(date '+%F %T') v2.2 installed and started (v2.1 saved as $BAK, unit as $BAKU)"
systemctl show -p Wants -p After --value ryuji-fan-guard | tr '\n' ' '; echo
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
  echo "$(date '+%F %T') ROLLBACK: $bad"; rollback; exit 1; fi
echo "$(date '+%F %T') v2.2 OK after 20 min; keeping it"
