#!/bin/bash
# tinynas-cage-test (2026-10-06): which motherboard fan header (pwm1/3/4, no tach) cools the HDD cage?
# A/B/A against the room cycle: BIOS, then headers at full (255), then BIOS again (MODE all | each). Logs every 60 s:
# all pwm values/modes, fan2 rpm, Tctl, SYSTIN, NVMe, each HDD. More airflow only (never lowers a fan below BIOS).
# Hand-back: pwmN_enable back to its saved mode (5 = BIOS SmartFan); the unit's ExecStopPost does it too.
# The BIOS curve registers (pwm*_auto_point*) are hashed before and after.
LOG=/var/tmp/tinynas-cage-test.csv
H=$(for h in /sys/class/hwmon/hwmon*; do [ "$(cat $h/name)" = nct6799 ] && echo $h; done)
K=$(for h in /sys/class/hwmon/hwmon*; do [ "$(cat $h/name)" = k10temp ] && echo $h; done)
N=$(for h in /sys/class/hwmon/hwmon*; do [ "$(cat $h/name)" = nvme ] && echo $h; done | tail -1)
DISKS="a b c d e f g h"
hash() { cat $H/pwm*_auto_point* $H/pwm*_temp_sel $H/pwm*_floor 2>/dev/null | md5sum | cut -c1-12; }
snap() {
  local d=""; for x in $DISKS; do d="$d,$(smartctl -n standby -A /dev/sd$x 2>/dev/null | awk '$1==194{print $10}')"; done
  echo "$(date +%s),$(date +%T),$1,$(cat $H/pwm1),$(cat $H/pwm2),$(cat $H/pwm3),$(cat $H/pwm4),$(cat $H/pwm1_enable)$(cat $H/pwm3_enable)$(cat $H/pwm4_enable),$(cat $H/fan2_input),$(( $(cat $K/temp1_input)/1000 )),$(( $(cat $H/temp1_input)/1000 )),$(( $(cat $N/temp1_input)/1000 ))$d" >> $LOG
}
restore() { for n in 1 2 3 4; do echo 5 > $H/pwm${n}_enable; done; }
trap 'restore; snap restored; echo "# $(date "+%F %T") stopped; curve hash $(hash) (start $H0)" >> $LOG; exit 0' TERM INT
[ -s $LOG ] || echo "epoch,time,phase,pwm1,pwm2,pwm3,pwm4,en134,fan2,tctl,systin,nvme$(for x in $DISKS; do printf ',sd%s' $x; done)" > $LOG
H0=$(hash); echo "# $(date '+%F %T') start; enables $(cat $H/pwm1_enable)$(cat $H/pwm3_enable)$(cat $H/pwm4_enable); curve hash $H0" >> $LOG
hold() { local i; for i in $(seq 1 $2); do snap $1; sleep 60; done; }
MODE=${1:-all}   # all: pwm1+3+4 together 20 min vs BIOS 20 min (is there any effect?); each: one header at a time;
                 # pwm2: the CPU-fan header (fan2) at full 20 min vs BIOS 20 min (cage fans on a splitter with the CPU cooler?)
hold bios0 10
if [ "$MODE" = pwm2 ]; then
  echo 1 > $H/pwm2_enable; echo 255 > $H/pwm2
  hold pwm2_full 20
  restore
  hold bios_after2 20
elif [ "$MODE" = all ]; then
  for n in 1 3 4; do echo 1 > $H/pwm${n}_enable; echo 255 > $H/pwm${n}; done
  hold all_full 20
  restore
  hold bios_after 20
else
  for n in 1 3 4; do
    echo 1 > $H/pwm${n}_enable; echo 255 > $H/pwm${n}
    hold pwm${n}_full 20
    echo 5 > $H/pwm${n}_enable
    hold bios_after${n} 20
  done
fi
restore; snap done
echo "# $(date '+%F %T') done; enables $(cat $H/pwm1_enable)$(cat $H/pwm3_enable)$(cat $H/pwm4_enable); curve hash $(hash) (start $H0)" >> $LOG
