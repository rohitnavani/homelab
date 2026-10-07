#!/bin/bash
# scrub-quiet (2026-10-07): a dataPool scrub as the MD1200 shelf's real-workload test in a hot room, kept quiet
# (Rohit asleep). md1200-fan v3.1 stays in control (it nudges +1% per 10 min while the smoothed hottest drive is
# above its 48.5C target; on 10-06 the scrub took it 17 -> 22% in 46 min at a 26-27C room). The scrub is cancelled
# if the shelf fans reach PCT_STOP % or a shelf temperature reaches one below the level where v3.1 goes urgent
# (+5% per check: drive 52, backplane 48, SIM 61, expander 90). makoto's inlet guard may pause the scrub (room above
# its limit twice); a scrub paused for 20 min is cancelled. ExecStopPost (scrub-quiet-stop.sh) cancels a scrub that
# is still running or paused, so stopping the unit always ends it. Log: LOG (epoch, local time, event).
PCT_STOP=25; LIM_DRIVE=51; LIM_BP=47; LIM_SIM=60; LIM_EXP=89
LOG=/var/tmp/scrub-quiet-1007.log
note() { echo "$(date +%s) $(date '+%F %T') $*" >> $LOG; }
state() { python3 -c "import json;d=json.load(open('/run/md1200-fan.state'));t=d['temps'];print(d['pct'],t['drive'],t['backplane'],t['SIM'],t['expander'])"; }
if zpool status dataPool | grep -q -E 'scrub in progress|scrub paused'; then note "a scrub is already running or paused; not starting another"; exit 1; fi
read pct drv bp sim exp < <(state)
note "start: shelf ${pct}% drive $drv bp $bp sim $sim exp $exp"
zpool scrub dataPool && note "scrub started"
paused=0
while sleep 60; do
  st=$(zpool status dataPool)
  if ! grep -q -E 'scrub in progress|scrub paused' <<<"$st"; then
    note "scrub ended: $(grep -oE 'scrub (repaired|canceled).*' <<<"$st" | head -1)"; exit 0; fi
  read pct drv bp sim exp < <(state)
  prog=$(grep -oP '[0-9.]+% done' <<<"$st" | head -1)
  note "progress ${prog:-paused}: shelf ${pct}% drive $drv bp $bp sim $sim exp $exp"
  if [ "$pct" -ge $PCT_STOP ] || [ "$drv" -ge $LIM_DRIVE ] || [ "$bp" -ge $LIM_BP ] || [ "$sim" -ge $LIM_SIM ] || [ "$exp" -ge $LIM_EXP ]; then
    zpool scrub -s dataPool; note "CANCELLED at ${prog:-?}: shelf ${pct}% drive $drv bp $bp sim $sim exp $exp"; exit 0; fi
  if grep -q 'scrub paused' <<<"$st"; then
    paused=$((paused+1))
    if [ $paused -ge 20 ]; then zpool scrub -s dataPool; note "paused 20 min (room guard): cancelled"; exit 0; fi
  else paused=0; fi
done
