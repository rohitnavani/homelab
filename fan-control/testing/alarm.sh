#!/bin/bash
# alarm (2026-10-14): one pass over the final run's danger signs; prints one line per problem, nothing if all is well.
# Checks: failed units of the run, test aborts/load stops/sensor failures in the run CSVs (new lines since the last
# pass, tracked by line counts in $STATE), fan-watchdog in iDRAC auto, md1200-fan not primary or with takeovers,
# a production controller inactive, the guard at Performance/Full. Run in a loop by the session.
STATE=${STATE:-$HOME/lab-thermal-2026-10-14/data/.alarm-state}
touch "$STATE"
pat='ABORT|load stopped|failed|stopping|stopped \(|reached|STOP:|ended early'
check_host() {  # host, glob of run CSVs
  ssh -o ConnectTimeout=10 -o BatchMode=yes "$1" "
    systemctl list-units --failed --no-legend --plain | grep -E 'ryuji-floor|mementos-steps|scrub-quiet|mic-shelf|mic-r720|pdu-cut|lab-loadoff|bench-7zip|fin' | awk '{print \"FAILED \" \$1}'
    for f in $2; do [ -f \$f ] && echo \"LINES \$f \$(wc -l < \$f)\"; done
    for u in \$(systemctl list-units --type=service --state=activating --no-legend --plain 'ryuji-floor*' 'mementos-steps*' 'scrub-quiet*' 'mic-*' 'bench-7zip*' | awk '{print \$1}'); do
      t=\$(systemctl show -p StateChangeTimestamp --value \$u); a=\$(( \$(date +%s) - \$(date -d \"\$t\" +%s) )); [ \$a -gt 900 ] && echo \"STUCK \$u \$a\"
    done
  " 2>/dev/null || echo "UNREACHABLE $1"
}
out=""
for h in ryuji mementos; do
  globs='/var/tmp/ryuji-profile-fin*.csv /var/tmp/disk-soak-*.csv /var/tmp/ryuji-maxbench-*.txt'
  [ $h = mementos ] && globs='/var/tmp/mementos-steps-fin*.csv /var/tmp/disk-soak-*.csv /var/tmp/noise-sweep.csv /var/tmp/r720-notch.csv'
  while read -r kind a b; do
    case $kind in
      FAILED) out+="$h: failed unit $a"$'\n';;
      UNREACHABLE) n=$(( $(cat "$STATE.unreach.$h" 2>/dev/null || echo 0) + 1 )); echo $n > "$STATE.unreach.$h"
                   [ $n -ge 2 ] && out+="$h unreachable ($n passes)"$'\n';;
      STUCK) out+="$h: $a has waited $(( b / 60 )) min in its gate (activating)"$'\n';;
      LINES)
        prev=$(grep -F "$h:$a " "$STATE" | awk '{print $2}'); prev=${prev:-0}
        if [ "$b" -gt "$prev" ]; then
          new=$(ssh -n -o BatchMode=yes $h "tail -n +$((prev + 1)) $a | grep -E '^#' | grep -E '$pat'" 2>/dev/null)
          [ -n "$new" ] && out+="$h $a: $new"$'\n'
          grep -vF "$h:$a " "$STATE" > "$STATE.tmp"; echo "$h:$a $b" >> "$STATE.tmp"; mv "$STATE.tmp" "$STATE"
        fi;;
    esac
  done < <(check_host $h "$globs" || true)
  ssh -n -o ConnectTimeout=10 -o BatchMode=yes $h true 2>/dev/null && rm -f "$STATE.unreach.$h"
done
m=$(ssh -n -o BatchMode=yes mementos 'head -1 /run/fan-watchdog.state; head -1 /run/md1200-fan.state; echo; systemctl is-active fan-watchdog md1200-fan | paste -sd" "; systemctl list-units --type=service --state=active --no-legend --plain "mementos-fixedfan*" "mic-shelf*" "mic-r720*" | wc -l' 2>/dev/null)
# iDRAC auto only counts while fan-watchdog runs (a test that stops it leaves "stopped: auto" in the state file)
if echo "$m" | head -1 | grep -qi auto && ! echo "$m" | head -1 | grep -q stopped; then out+="mementos: fan-watchdog in iDRAC auto: $(echo "$m" | head -1)"$'\n'; fi
echo "$m" | sed -n 2p | grep -qE '"role": "primary"' || out+="mementos: md1200-fan state not primary: $(echo "$m" | sed -n 2p | cut -c1-120)"$'\n'
# md1200-fan re-sends after a firmware ramp ("takeover"); one is handled. Flag 2+ new ones between passes (a fight).
tk=$(echo "$m" | sed -n 2p | grep -oP '"takeovers": \K\d+'); tkp=$(cat "$STATE.takeovers" 2>/dev/null || echo "${tk:-0}")
[ -n "$tk" ] && [ $(( tk - tkp )) -ge 2 ] && out+="mementos: md1200-fan takeovers $tkp -> $tk since the last pass"$'\n'
[ -n "$tk" ] && echo "$tk" > "$STATE.takeovers"
if [ "$(echo "$m" | sed -n 4p)" = 0 ] && [ "$(echo "$m" | sed -n 3p)" != "active active" ]; then out+="mementos: a controller is not active ($(echo "$m" | sed -n 3p)) and no test holds the fans"$'\n'; fi
r=$(ssh -n -o BatchMode=yes ryuji 'head -1 /run/ryuji-fan-guard.state; echo; systemctl is-active ryuji-fan-guard; systemctl list-units --type=service --state=active --no-legend --plain "ryuji-floor-fin*" | wc -l' 2>/dev/null)
off=$(echo "$r" | head -1 | grep -oP '"offset": \K-?\d+')
drv=$(echo "$r" | head -1 | grep -oP '"drive": \K\d+')
# v2.8 goes to Performance for hot drives (>= 49C) by design; flag Full always, Performance only for another reason
# a drive-triggered Performance holds 10 min after the disks are <= 46C: flag it only if it lasts 15 min past that
PF=${STATE}.perf
if [ -n "$off" ] && [ "$off" -ge 100 ]; then out+="ryuji: guard at Full Speed (drive ${drv:-?}C)"$'\n'
elif [ -n "$off" ] && [ "$off" -ge 0 ] && [ "${drv:-0}" -lt 47 ]; then
  [ -f "$PF" ] || date +%s > "$PF"
  [ $(( $(date +%s) - $(cat "$PF") )) -gt 1500 ] && out+="ryuji: guard at offset $off for 25+ min with the drives cool (${drv:-?}C)"$'\n'
else rm -f "$PF"; fi
[ "$(echo "$r" | sed -n 3p)" = 0 ] && [ "$(echo "$r" | sed -n 2p)" != active ] && out+="ryuji: guard not active and no test unit runs"$'\n'
# sojiro (from 10-15 evening, once its BMC offset is set by hand; flag file): BMC sensors via futaba's Prometheus
if [ -f "$STATE.sojiro" ]; then
  sj=$(python3 -I - <<'PY' 2>/dev/null
import json, urllib.parse, urllib.request
def q(e):
    u = 'http://10.0.0.3:9090/api/v1/query?' + urllib.parse.urlencode({'query': e})
    r = json.load(urllib.request.urlopen(u, timeout=10))['data']['result']
    return float(r[0]['value'][1]) if r else None
up = q('up{instance="10.0.0.8",job="node"}')
if up == 1:
    c = q('node_ipmi_temperature_celsius{instance="10.0.0.8",sensor="CPU0_TEMP"}')
    mb = q('node_ipmi_temperature_celsius{instance="10.0.0.8",sensor="MB_TEMP1"}')
    f = q('node_ipmi_speed_rpm{instance="10.0.0.8",sensor="CPU0_FAN"}')
    d = q('max(drivecheck_temperature_celsius{instance="10.0.0.8",class="sata"})')
    bad = []
    if c is not None and c >= 85: bad.append(f'CPU0_TEMP {c:.0f}C')
    if mb is not None and mb >= 75: bad.append(f'MB_TEMP1 {mb:.0f}C')
    if f is not None and f < 1000: bad.append(f'CPU0_FAN {f:.0f} rpm')
    if d is not None and d >= 50: bad.append(f'hottest drive {d:.0f}C')
    if bad: print('sojiro: ' + ', '.join(bad))
PY
)
  [ -n "$sj" ] && out+="$sj"$'\n'
fi
printf '%s' "$out"
