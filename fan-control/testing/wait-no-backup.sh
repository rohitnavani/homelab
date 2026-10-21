#!/bin/sh
# wait-no-backup (2026-10-20): ExecStartPre of the N1b read soaks. sojiro pulls its nightly backups from mementos and
# tinynas at 03:00 (syncoid over ssh, zfs send on the source, zfs recv on sojiro; ~8 min on 10-19). Waits while any of
# that runs on this host, up to 30 min, then refuses (exit 1) so a soak never competes with a backup.
for i in $(seq 60); do
  pgrep -f "[s]yncoid|[z]fs send|[z]fs recv|[z]fs receive" >/dev/null || exit 0
  [ "$i" = 1 ] && echo "backup running, waiting"
  sleep 30
done
echo "backup still running after 30 min: refusing"; exit 1
