#!/bin/bash
# lab-inlet-guard (2026-10-06): stop test load if the room (mementos inlet) gets too warm. Env: LIMIT, HARD, DATA.
# Every 60 s: read the mementos inlet (iDRAC sensor via ipmitool on mementos, 1C resolution), log it to data/room.csv,
# and publish it to ryuji and mementos as /run/room-inlet ("<epoch> <inlet>") so test scripts can wait for the room
# to come down before adding heat. If the inlet is above LIMIT on two readings in a row: switch off every source of
# test heat (ryuji: kill stress-ng, the profile script waits for the room before the next load step; mementos: stop
# mementos-steps, pause a dataPool scrub). At HARD (29C) or more twice in a row, also stop the ryuji-profile unit.
# tinynas-cage only raises fan speeds (adds no heat), so it is left alone. Production controllers are never touched.
LIMIT=${LIMIT:-27}; HARD=${HARD:-29}
DATA=${DATA:-$HOME/fan-control-data}; mkdir -p "$DATA"
LOG=$DATA/inlet-guard.log
ROOM=$DATA/room.csv   # epoch,local time,mementos inlet (room reference for all tests)
SSH="ssh -o BatchMode=yes -o ConnectTimeout=10"
over=0; hard=0
echo "$(date '+%F %T') start, limit ${LIMIT}C (heat off), hard ${HARD}C (stop tests)" >> $LOG
while :; do
  now=$(date +%s)
  # read the iDRAC inlet sensor directly (fan-watchdog's state file goes stale whenever a test stops fan-watchdog)
  inlet=$($SSH mementos "sudo ipmitool sdr type Temperature | awk -F'|' '/Inlet/{print \$5+0}'" 2>/dev/null)
  echo "$now,$(date '+%F %T'),${inlet}" >> $ROOM
  if [ -n "$inlet" ]; then
    for h in ryuji mementos; do $SSH $h "echo $now $inlet | sudo tee /run/room-inlet >/dev/null" 2>/dev/null; done
    if [ "$inlet" -gt "$LIMIT" ]; then over=$((over+1)); else over=0; fi
    if [ "$inlet" -ge "$HARD" ]; then hard=$((hard+1)); else hard=0; fi
  fi
  if [ $over -ge 2 ]; then
    echo "$(date '+%F %T') inlet ${inlet}C > ${LIMIT}C twice: test heat off" >> $LOG
    $SSH ryuji "pgrep -x stress-ng >/dev/null && sudo pkill -x stress-ng && echo ryuji: stress-ng killed" >> $LOG 2>&1
    $SSH mementos "systemctl is-active --quiet mementos-steps && sudo systemctl stop mementos-steps && echo mementos-steps stopped; zpool status dataPool | grep -q 'scrub in progress' && sudo zpool scrub -p dataPool && echo dataPool scrub paused" >> $LOG 2>&1
    over=0
  fi
  if [ $hard -ge 2 ]; then
    echo "$(date '+%F %T') inlet ${inlet}C >= ${HARD}C twice: stopping test units" >> $LOG
    $SSH ryuji "systemctl is-active --quiet ryuji-profile && sudo systemctl stop ryuji-profile && echo ryuji-profile stopped" >> $LOG 2>&1
    hard=0
  fi
  sleep 60
done
