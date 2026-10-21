#!/bin/sh
# run-all (2026-10-20): every host-tool dry run with a shim PATH (fake ipmitool, stress-ng, fio, smartctl, systemctl,
# curl, nvidia-smi, zpool, lsblk, pkill, pgrep, turbostat, sensors, nvme, ssh that only log argv) and guard.py, which
# makes any real subprocess or network call from the code under test fail. Passes only if every test passes AND the
# shim log stays empty (nothing reached even a fake binary). Never run the tools on makoto any other way.
cd "$(dirname "$0")" || exit 1
SHIM_LOG=$(mktemp /tmp/host-tools-shim.XXXXXX); export SHIM_LOG
PATH="$(pwd)/shim:$PATH"; export PATH
rc=0
for t in test_*.py; do
  echo "=== $t"
  timeout 600 python3 -I -B "$t"      # -B: no __pycache__ in the repo || rc=1
done
if [ -s "$SHIM_LOG" ]; then echo "SHIM LOG NOT EMPTY:"; cat "$SHIM_LOG"; rc=1; else echo "shim log empty: no command reached even a fake binary"; fi
rm -f "$SHIM_LOG"
echo "overall rc=$rc"; exit $rc
