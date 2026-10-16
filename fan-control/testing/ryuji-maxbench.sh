#!/bin/bash
# ryuji-maxbench (2026-10-15, for Fri 10-16 12:10). Rohit: "get some maxed out ryuji numbers, i wanna know what those
# cores can do". ryuji: 2x Xeon E5-2696 v4 (22 cores / 44 threads each, BIOS PL1 150 W / PL2 180 W per package, left as
# is), 8x 16 GB DDR4-2133, one FSP800-20ERM. Phases (about 65 min):
#   idle      3 min idle, guard in control (reference for the mic and the sensors)
#   scale     7-Zip 23.01 `7z b` at 1, 2, 4, 8, 11, 22, 33, 44, 66 and 88 threads, 20 s apart, turbostat beside it
#   sustain   15 min of back-to-back `7z b -mmt88` under the guard (it holds -80 at full load)
#   fullfan   8 min of the same at Full Speed (offset 127; guard stopped), then -80 and the guard again
#   memory    stress-ng stream (44 instances, 60 s); sysbench memory read and write (88 threads, 1 MiB blocks)
#   crypto    openssl speed: AES-256-GCM (1 thread and 88), SHA-256 (88), RSA-2048 (88)
#   sysbench  sysbench cpu (primes to 20,000) at 1 and 88 threads, 30 s each
#   cool      10 min idle, guard in control
# Results: /var/tmp/ryuji-maxbench-<label>.txt (raw outputs and "# <epoch> <time> <note>" lines for the mic join),
# sensors every 15 s: /var/tmp/ryuji-maxbench-<label>.csv. Turbostat summaries every 5 s: /var/tmp/ryuji-maxbench-<label>.ts.
# Safety: every 15 s, a CPU >= 82C (the BMC's warning), a VR >= 95C, SIO1 >= 82C or a DIMM >= 80C ends the run (load
# killed). ExecStopPost ryuji-maxbench-restore.sh kills any load, puts -80 back and starts the guard.
# usage (root): ryuji-maxbench.sh <label> [dry]   (dry: 1 thread, seconds-long steps, no fan change)
L=${1:-run}; DRY=${2:-}
Z=/home/rohit/bench7z/usr/lib/7zip/7z
OUT=/var/tmp/ryuji-maxbench-$L.txt; CSV=/var/tmp/ryuji-maxbench-$L.csv; TS=/var/tmp/ryuji-maxbench-$L.ts
STOPF=/run/ryuji-maxbench.stop; rm -f $STOPF
BMC="python3 -W ignore /var/tmp/gbt-fan-offset.py 10.0.0.118"; export BMC_PWFILE=/root/.bmc-pass BMC_USER=root
note() { echo "# $(date +%s) $(date '+%F %T %Z') $*" >> $OUT; }
alive() { [ ! -f $STOPF ]; }
if [ -n "$DRY" ]; then THREADS="1"; SUSTAIN=20; FULLFAN=0; IDLE=5; COOL=5; MEMT=3; CPUT=3; OSL=1
else THREADS="1 2 4 8 11 22 33 44 66 88"; SUSTAIN=900; FULLFAN=480; IDLE=180; COOL=600; MEMT=60; CPUT=30; OSL=5; fi

rapl() { local s=0; for z in /sys/class/powercap/intel-rapl:0 /sys/class/powercap/intel-rapl:1; do s=$((s + $(cat $z/energy_uj))); done; echo $s; }
sensors_loop() {   # every 15 s: sensors to CSV, safety limits
  echo "epoch,time,phase,cpu0,cpu1,vr0,vr1,dimm,sio1,cpu_fan,sys_fan,dcmi_w,pkg_w,mhz" > $CSV
  local e0 t0 e1 t1 pkg
  e0=$(rapl); t0=$(date +%s.%N)
  while alive; do
    sleep 15
    local s; s=$(ipmitool sdr 2>/dev/null)
    v() { awk -F'|' -v k="$1" '$1 ~ "^"k {gsub(/ /,"",$2); split($2,a,"[^0-9.]"); print a[1]+0; exit}' <<<"$s"; }
    local c0 c1 r0 r1 dm si cf sf dw mhz
    c0=$(v CPU0_TEMP); c1=$(v CPU1_TEMP); r0=$(v VR_P0_TEMP); r1=$(v VR_P1_TEMP); si=$(v "SIO Temp 1")
    dm=$(awk -F'|' '$1 ~ /^DIMM/ {gsub(/ /,"",$2); split($2,a,"[^0-9.]"); if (a[1]+0>m) m=a[1]+0} END{print m+0}' <<<"$s")
    cf=$(v CPU0_FAN); sf=$(v SYS_FAN1)
    dw=$(ipmitool dcmi power reading 2>/dev/null | awk '/Instantaneous power reading/{print $4}')
    e1=$(rapl); t1=$(date +%s.%N); pkg=$(awk -v a=$e0 -v b=$e1 -v s=$t0 -v t=$t1 'BEGIN{d=b-a; if(d<0)d=0; printf "%.1f", d/1e6/(t-s)}'); e0=$e1; t0=$t1
    mhz=$(awk '/^cpu MHz/{s+=$4; n++} END{printf "%.0f", s/n}' /proc/cpuinfo)
    echo "$(date +%s),$(date +%T),$(cat /run/ryuji-maxbench.phase 2>/dev/null),$c0,$c1,$r0,$r1,$dm,$si,$cf,$sf,$dw,$pkg,$mhz" >> $CSV
    local bad=""
    [ "${c0:-0}" -ge 82 ] || [ "${c1:-0}" -ge 82 ] && bad="CPU ${c0}/${c1}C"
    [ "${r0:-0}" -ge 95 ] || [ "${r1:-0}" -ge 95 ] && bad="$bad VR ${r0}/${r1}C"
    [ "${si:-0}" -ge 82 ] && bad="$bad SIO1 ${si}C"
    [ "${dm:-0}" -ge 80 ] && bad="$bad DIMM ${dm}C"
    if [ -n "$bad" ]; then note "STOP: $bad"; touch $STOPF; pkill -f "[7]z b" ; pkill -x stress-ng; pkill -x openssl; pkill -x sysbench; fi
  done
}
phase() { echo "$1" > /run/ryuji-maxbench.phase; note "phase $1"; }
z7() { echo "## $(date '+%T') 7z b $*" >> $OUT; $Z b "$@" 2>&1 | grep -E "^(Tot|Avr|CPU Freq|7-Zip|Intel|[0-9]+:)" >> $OUT; }
rest() { local n=$1; while [ $n -gt 0 ] && alive; do sleep 1; n=$((n - 1)); done; }

echo "# ryuji-maxbench $L on $(hostname): $(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2-), $(nproc) threads, kernel $(uname -r)" > $OUT
note "start${DRY:+ (dry)}"
sensors_loop & SL=$!
turbostat --quiet --Summary --interval 5 --show Time_Of_Day_Seconds,Busy%,Bzy_MHz,PkgTmp,PkgWatt,RAMWatt --out $TS & TB=$!
trap 'kill $SL $TB 2>/dev/null' EXIT

phase idle; rest $IDLE
phase scale
for n in $THREADS; do alive || break; note "7z threads $n"; z7 -mmt$n; rest 20; done
alive && { phase sustain; end=$(( $(date +%s) + SUSTAIN )); while alive && [ "$(date +%s)" -lt "$end" ]; do z7 -mmt$([ -n "$DRY" ] && echo 1 || echo 88); done; }
if alive && [ "$FULLFAN" -gt 0 ]; then
  phase fullfan
  systemctl stop ryuji-fan-guard; note "guard stopped"
  if $BMC set 127 >> $OUT 2>&1; then
    note "offset 127 (Full Speed)"; end=$(( $(date +%s) + FULLFAN )); while alive && [ "$(date +%s)" -lt "$end" ]; do z7 -mmt88; done
  else note "BMC set 127 failed: skipping the Full Speed phase"; fi
  $BMC set -80 >> $OUT 2>&1 && note "offset -80"; systemctl start ryuji-fan-guard; note "guard started"
fi
if alive; then
  phase memory
  n=$([ -n "$DRY" ] && echo 1 || echo 44); note "stress-ng stream $n x ${MEMT}s"; stress-ng --stream $n -t ${MEMT}s --metrics 2>&1 | grep -E "stream|metrc" >> $OUT
  for op in read write; do alive || break
    note "sysbench memory $op"; sysbench memory --threads=$([ -n "$DRY" ] && echo 1 || echo 88) --memory-block-size=1M --memory-total-size=10000G \
      --memory-oper=$op --time=$MEMT run 2>&1 | grep -E "transferred|events/s|total time" >> $OUT
  done
fi
if alive; then
  phase crypto
  note "openssl aes-256-gcm 1 thread"; openssl speed -seconds $OSL -evp aes-256-gcm 2>/dev/null | tail -2 >> $OUT
  for a in "-evp aes-256-gcm" "sha256" "rsa2048"; do alive || break
    note "openssl $a, $([ -n "$DRY" ] && echo 1 || echo 88) processes"
    openssl speed -multi $([ -n "$DRY" ] && echo 1 || echo 88) -seconds $OSL $a 2>/dev/null | tail -3 >> $OUT
  done
fi
if alive; then
  phase sysbench
  for t in 1 $([ -n "$DRY" ] || echo 88); do alive || break
    note "sysbench cpu $t threads"; sysbench cpu --cpu-max-prime=20000 --threads=$t --time=$CPUT run 2>&1 | grep -E "events per second|total number of events" >> $OUT
  done
fi
phase cool; rest $COOL
alive && note "done" || note "ended early"
