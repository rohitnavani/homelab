#!/bin/sh
# Put production fan control back after shelf-exp2 (also done by the script itself on exit).
grep -q '^MIN_PCT=10;' /usr/local/sbin/fan-watchdog || { sed -i 's/^MIN_PCT=[0-9]*;/MIN_PCT=10;/' /usr/local/sbin/fan-watchdog; systemctl restart fan-watchdog; }
systemctl start md1200-fan
