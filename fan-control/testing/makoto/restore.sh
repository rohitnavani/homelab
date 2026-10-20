#!/bin/sh
# restore: hand makoto's fans back to the BMC (ExecStopPost backstop for every test unit), unless another fanstep
# run or makoto-fan is driving them right now (a waiting unit's shell does not count: only the running python)
pgrep -f '^/usr/bin/python3 -I .*/fanstep[.]py' >/dev/null && exit 0
pgrep -f '^/usr/bin/python3 .*makoto-fan$' >/dev/null && exit 0
ipmitool raw 0x3a 0x01 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00 >/dev/null 2>&1
rm -f /run/makoto-fantest.phase
exit 0
