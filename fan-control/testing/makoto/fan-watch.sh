#!/bin/bash
# fan-watch UNIT [hours]: watch a running makoto-fan (UNIT = makoto-fan-test or makoto-fan) once a minute and stop it,
# which hands the fans to the BMC, on a crash loop, an emergency, a failed fan write, a dead state file or a
# temperature past the watch's own limits (above the controller's curves, under its emergency levels).
# Log: /var/tmp/makoto-fan-watch.log (root)
U=${1:-makoto-fan-test}; H=${2:-14}
LOG=/var/tmp/makoto-fan-watch.log; S=/run/makoto-fan.state
exec >>"$LOG" 2>&1
echo "$(date '+%F %T') watching $U for $H h"
start=$(date +%s); bad=""; hot=0
while [ $(( $(date +%s) - start )) -lt $(( H * 3600 )) ]; do
  sleep 60
  systemctl is-active --quiet "$U" || { echo "$(date '+%T') $U not active: watch ends"; exit 0; }
  r=$(systemctl show -p NRestarts --value "$U"); [ "${r:-0}" -gt 2 ] && { bad="restarted $r times"; break; }
  j=$(journalctl -u "$U" --since "@$start" -o cat)
  grep -qE 'crashed|unreadable|failed writes' <<<"$j" && { bad="$(grep -E 'crashed|unreadable|failed writes' <<<"$j" | head -1)"; break; }
  [ "$(grep -c 'fan write failed' <<<"$j")" -ge 3 ] && { bad="3 failed fan writes"; break; }
  age=$(( $(date +%s) - $(stat -c %Y "$S" 2>/dev/null || echo 0) ))
  [ "$age" -gt 120 ] && { bad="state file $age s old"; break; }
  line=$(python3 -c "import json; d=json.load(open('$S')); print(d['cpu_smooth'], d.get('card') or 0, d.get('ddr') or 0, d.get('nvme') or 0, d.get('fan1'), d.get('fan4'), d.get('rpm1'), d.get('rpm4'))")
  read -r cpu card ddr nvme f1 f4 r1 r4 <<<"$line"
  echo "$(date '+%T') cpu~ $cpu card $card ddr $ddr nvme $nvme fans $f1/$f4% $r1/$r4 rpm"
  # stop when the controller is not answering heat (hot with its fan not near full), or past what full fans should allow
  if awk -v c="$cpu" -v k="$card" -v d="$ddr" -v n="$nvme" -v a="$f1" -v b="$f4" \
      'BEGIN{exit !((c>=86 && a+0<90) || (k>=57 && b+0<90) || c>=96 || d>=78 || n>=72)}'; then
    hot=$((hot + 1)); if [ "$hot" -ge 2 ]; then bad="too hot: $line"; break; fi
  else
    hot=0
  fi
  awk -v a="$f1" -v b="$r1" 'BEGIN{exit !(a>=1 && b!="None" && b+0<600)}' && { bad="FAN1 at $f1% reads $r1 rpm"; break; }
  awk -v a="$f4" -v b="$r4" 'BEGIN{exit !(a>=1 && b!="None" && b+0<600)}' && { bad="FAN4 at $f4% reads $r4 rpm"; break; }
done
if [ -n "$bad" ]; then
  echo "$(date '+%F %T') STOP $U: $bad"; systemctl stop "$U"; exit 1; fi
echo "$(date '+%F %T') $U fine for $H h"
