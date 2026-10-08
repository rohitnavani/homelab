#!/bin/sh
# ExecStopPost for shelf-exp4: hand the shelf back to md1200-fan (the script does the same on exit). Never touches
# fan-watchdog (exp4 does not change its floor).
systemctl start md1200-fan
