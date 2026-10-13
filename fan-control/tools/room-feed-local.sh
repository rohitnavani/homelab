#!/bin/bash
# room-feed-local (2026-10-13): room-feed.sh run on ryuji itself, so a reboot of the host that runs the Claude session
# (makoto, 10-12 20:33) cannot stop it. Every 60 s it takes the room reference (the R720 inlet that fan-watchdog
# publishes through lab-thermal-textfile) from Prometheus on futaba, writes "<epoch> <inlet>" to /run/room-inlet for
# ryuji-floor.py's room gate, logs it, and kills ryuji's stress-ng if the inlet is above LIMIT on two readings in a row.
# No fresh value -> the file is not refreshed, so ryuji-floor.py drops its load after 3 minutes. Run as root on ryuji:
#   systemd-run --unit=room-feed-1013 -p RuntimeMaxSec=13h bash /var/tmp/room-feed-local.sh
LIMIT=${LIMIT:-27}; LOG=${LOG:-/var/tmp/room-feed-1013.csv}
Q='http://10.0.0.3:9090/api/v1/query?query=lab_r720_temp_celsius%7Bsensor%3D%22inlet%22%7D%20and%20on%28instance%29%20%28lab_controller_state_age_seconds%7Bcontroller%3D%22fan-watchdog%22%7D%20%3C%20120%29'
over=0
echo "# $(date '+%F %T %Z') room-feed-local start, limit ${LIMIT}C" >> "$LOG"
while :; do
  now=$(date +%s)
  inlet=$(curl -s -m 10 "$Q" | python3 -I -c 'import json,sys; r=json.load(sys.stdin)["data"]["result"]; print(int(float(r[0]["value"][1])) if r else "")' 2>/dev/null)
  echo "$now,$(date '+%F %T'),${inlet}" >> "$LOG"
  if [ -n "$inlet" ]; then
    echo "$now $inlet" > /run/room-inlet
    if [ "$inlet" -gt "$LIMIT" ]; then over=$((over+1)); else over=0; fi
    if [ $over -ge 2 ]; then
      echo "# $(date '+%F %T') inlet ${inlet}C > ${LIMIT}C twice: test load off" >> "$LOG"
      pkill -x stress-ng-cpu; pkill -x stress-ng && echo "# $(date '+%T') stress-ng killed" >> "$LOG"
      over=0
    fi
  fi
  sleep 60
done
