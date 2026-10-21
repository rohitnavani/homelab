#!/bin/sh
# restore-guard (2026-10-20): ExecStopPost wrapper for the test units. Runs the restore unless another unit of the same
# family is still running on this host (state active: its main process runs, so it owns the fans and runs its own
# restore when it ends). Covers a unit whose gate refused while the one before it overran (REVIEW-PLAN-1 minor 1). A
# unit only waiting in its gate (activating) does not count, so a normal end always restores.
# usage: restore-guard.sh <this unit> <family regex> <restore script>
me=$1; fam=$2; shift 2
# 2026-10-20 04:45: only a unit that carries this same restore counts (ryuji's disk soak has none; REVIEW-CHAIN-2)
others=
for u in $(systemctl list-units --type=service --state=active --no-legend --plain | awk '{print $1}' | grep -E "^($fam)[.]service\$" | grep -vxF "$me"); do
  systemctl show -p ExecStopPost --value "$u" | grep -qF "$1" && others="$others $u"
done
if [ -n "$others" ]; then
  echo "$(date '+%F %T') restore-guard: $me ended while $(echo $others) still runs: restore skipped" >> /var/tmp/restore-guard.log
  exit 0
fi
exec /bin/sh "$@"
