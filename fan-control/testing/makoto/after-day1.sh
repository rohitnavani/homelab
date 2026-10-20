#!/bin/sh
# after-day1: once makoto-fanstep-day1 has ended (it hands the fans to the BMC), put the makoto-fan trial back, so the
# fans are under control again within a minute and FanControllerStale stays quiet, then run day1b (the same loads
# with makoto-fan in control). Does nothing if production makoto-fan is active; day1b only if it can start by 15:00
# (it takes 50 min, and the 16:00 backstop stops makoto-fanstep-* units).
D=$(cd "$(dirname "$0")/.." && pwd)
while systemctl is-active -q makoto-fanstep-day1; do sleep 15; done
systemctl is-active -q makoto-fan && exit 0
if ! systemctl is-active -q makoto-fan-test; then
  systemctl stop makoto-fan-watch 2>/dev/null
  systemctl reset-failed makoto-fan-test makoto-fan-watch 2>/dev/null
  "$D/tools/start-trial.sh" 3 || exit 1
fi
[ "$(date +%s)" -lt "$(date -d '2026-10-20 15:00' +%s)" ] || exit 0
sleep 60
exec "$D/tools/run-step.sh" day1b day1b.sched --load-off 95 --abort 98 --card-max 57
