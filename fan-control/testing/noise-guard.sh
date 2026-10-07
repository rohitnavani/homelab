#!/bin/bash
# noise-guard (2026-10-07): Rohit is asleep, so no test may make the rack audibly louder. Every 20 s read the newest
# levels from morgana's mic logger (about 1 m in front of the rack; mic-level-log.py writes one row per 10 s clip)
# and, if the A-weighted level is more than RISE dB above the quiet reference REF for HOLD readings in a row
# (3 = 30 s), stop every test unit that makes heat or noise. Their ExecStopPost scripts restore production control
# (mementos-quiet: kill load, stock RAPL; ryuji-quiet: kill load, guard on; scrub-quiet: cancel the scrub).
# Scale (10-06, same mic spot): R720 10 -> 20% +1.4 dB(A), 10 -> 30% +3.7; shelf 17 -> 30% +3.2.
# Env: REF (dB(A), the quiet baseline median), RISE (default 2.5), HOLD (default 3), MIC (the mic logger's CSV on
# morgana), DATA (log folder). 2026-10-07 run: REF=-68.30 RISE=3.0 HOLD=3 MIC=/var/tmp/mic-levels-1007.csv.
REF=${REF:?quiet reference dB(A)}; RISE=${RISE:-2.5}; HOLD=${HOLD:-3}
MIC=${MIC:-/var/tmp/mic-levels.csv}
LOG=${LOG:-${DATA:-$HOME/fan-control-data}/noise-guard.log}
SSH="ssh -o BatchMode=yes -o ConnectTimeout=10"
LIMIT=$(python3 -c "print(round($REF + $RISE, 2))")
echo "$(date '+%F %T') start: ref $REF dB(A), trip above $LIMIT for $HOLD readings" >> $LOG
over=0; last=0; stale=0
while sleep 20; do
  row=$($SSH morgana "tail -1 $MIC" 2>/dev/null)
  t=${row%%,*}; a=$(cut -d, -f2 <<<"$row")
  if ! [[ "$t" =~ ^[0-9]+$ ]] || [ "$t" = "$last" ]; then
    stale=$((stale+1)); [ $stale -eq 9 ] && echo "$(date '+%F %T') no new mic reading for 3 min (logger stopped?)" >> $LOG
    continue
  fi
  stale=0; last=$t
  if python3 -c "import sys; sys.exit(0 if $a > $LIMIT else 1)"; then over=$((over+1)); else over=0; fi
  [ $over -ge 1 ] && echo "$(date '+%F %T') loud reading $a dB(A) (limit $LIMIT), $over in a row" >> $LOG
  if [ $over -ge $HOLD ]; then
    echo "$(date '+%F %T') TRIP at $a dB(A): stopping test units" >> $LOG
    $SSH mementos 'for u in mementos-quiet scrub-quiet; do systemctl is-active --quiet $u && sudo systemctl stop $u && echo "mementos: $u stopped"; done' >> $LOG 2>&1
    $SSH ryuji 'systemctl is-active --quiet ryuji-quiet && sudo systemctl stop ryuji-quiet && echo "ryuji: ryuji-quiet stopped"' >> $LOG 2>&1
    over=0
  fi
done
