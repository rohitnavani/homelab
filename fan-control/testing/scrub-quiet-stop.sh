#!/bin/sh
# ExecStopPost for scrub-quiet: never leave a test scrub running or paused behind.
if zpool status dataPool | grep -q -E 'scrub in progress|scrub paused'; then
  zpool scrub -s dataPool && echo "$(date +%s) $(date '+%F %T') unit stopped: scrub cancelled" >> /var/tmp/scrub-quiet-1007.log
fi
exit 0
