#!/bin/bash
# bench-7zip (2026-10-13, ryuji): 7-Zip 23.01's built-in benchmark (LZMA compress/decompress, the same version as
# tinynas's) with the guard in control, so the result is what ryuji does with its normal fan control. One thread, then
# 44 (one per core), then every thread (the default). Each run's summary lines go to $O (default
# /var/tmp/bench-7zip.txt). ryuji-floor.py (plan v4bench) logs the sensors alongside; this script only adds the load.
O=${O:-/var/tmp/bench-7zip.txt}
run() {
  echo "## $(date '+%F %T %Z') 7z b $*" >> $O
  /usr/lib/7zip/7z b "$@" 2>&1 | grep -E "^(Tot|Avr|CPU Freq|7-Zip|Intel|[0-9]+:)" >> $O
  echo "## $(date '+%T') end" >> $O
}
run -mmt1
sleep 60
run -mmt44
sleep 60
run
