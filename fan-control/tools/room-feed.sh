#!/bin/bash
# room-feed (2026-10-10): lab-inlet-guard without the extra IPMI reader. Every 60 s it takes the room reference (the
# R720 inlet, which fan-watchdog already reads; published by lab-thermal-textfile) from Prometheus on futaba instead of
# running a second in-band ipmitool on mementos (that can make fan-watchdog's own read fail and hand the fans to the
# loud iDRAC auto mode). Writes "<epoch> <inlet>" to /run/room-inlet on ryuji for ryuji-floor.py's room gate, logs it
# to $DATA/room.csv, and kills ryuji's stress-ng if the inlet is above LIMIT on two readings in a row.
# If Prometheus has no fresh value the file is not refreshed, so ryuji-floor.py drops its load after 3 minutes.
# Run it as you (ssh to ryuji with your key), e.g.
#   sudo systemd-run --uid=$USER --unit=room-feed -p RuntimeMaxSec=10h --setenv=DATA=$DATA $PWD/tools/room-feed.sh
LIMIT=${LIMIT:-27}; DATA=${DATA:-$HOME/fan-control-data}; mkdir -p "$DATA"
SSH="ssh -o BatchMode=yes -o ConnectTimeout=10"
Q='http://10.0.0.3:9090/api/v1/query?query=lab_r720_temp_celsius%7Bsensor%3D%22inlet%22%7D%20and%20on%28instance%29%20%28lab_controller_state_age_seconds%7Bcontroller%3D%22fan-watchdog%22%7D%20%3C%20120%29'
over=0
echo "$(date '+%F %T') room-feed start, limit ${LIMIT}C" >> $DATA/room-feed.log
while :; do
  now=$(date +%s)
  inlet=$(curl -s -m 10 "$Q" | python3 -I -c 'import json,sys; r=json.load(sys.stdin)["data"]["result"]; print(int(float(r[0]["value"][1])) if r else "")' 2>/dev/null)
  echo "$now,$(date '+%F %T'),${inlet}" >> $DATA/room.csv
  if [ -n "$inlet" ]; then
    $SSH ryuji "echo $now $inlet | sudo tee /run/room-inlet >/dev/null" 2>/dev/null
    if [ "$inlet" -gt "$LIMIT" ]; then over=$((over+1)); else over=0; fi
    if [ $over -ge 2 ]; then
      echo "$(date '+%F %T') inlet ${inlet}C > ${LIMIT}C twice: ryuji test load off" >> $DATA/room-feed.log
      $SSH ryuji "pgrep -x stress-ng >/dev/null && sudo pkill -x stress-ng && echo ryuji: stress-ng killed" >> $DATA/room-feed.log 2>&1
      over=0
    fi
  fi
  sleep 60
done
