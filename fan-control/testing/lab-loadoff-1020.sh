#!/bin/sh
# lab-loadoff-1020 (2026-10-20): backstop at the end of each loud or medium window of the 10-20/21 thermal run, on every
# host the run loads, in case a block overran or the session stalled. Stops every test unit of the run that is still
# running or still waiting in its gate (each unit's ExecStopPost hands control back), kills leftover stress-ng and fio,
# and makes sure the host's production control is back: fan-watchdog + md1200-fan (mementos), ryuji-fan-guard (ryuji),
# BMC fan offset -80 (sojiro, through sojiro-floor-restore). Never used on makoto. Log: /var/tmp/lab-loadoff-1020.log
L=/var/tmp/lab-loadoff-1020.log
H=$(hostname -s | tr 'A-Z' 'a-z')
echo "$(date '+%F %T') backstop start on $H" >> $L
case "$H" in
  mementos) G="mementos-steps* mementos-fixedfan* mic-shelf* mic-r720* noise-sweep* scrub-quiet* shelf-exp* pdu-cut* lab-load* lab-soak*" ;;
  ryuji)    G="ryuji-floor* ryuji-profile* ryuji-quiet* lr-cut* pdu-cut* lab-load* lab-soak*" ;;
  sojiro)   G="sojiro-floor* lab-load* lab-soak* pdu-cut*" ;;
  *)        G="lab-load* lab-soak*" ;;
esac
for u in $(systemctl list-units --type=service --state=active,activating --no-legend --plain $G | awk '$1 !~ /^lab-loadoff/ {print $1}'); do   # 10-20 16:05: never itself (lab-load* matched it: SIGTERM at 16:00)
  systemctl stop "$u" && echo "$(date '+%T') stopped $u" >> $L
done
pkill -x stress-ng-cpu 2>/dev/null; pkill -x stress-ng 2>/dev/null && echo "$(date '+%T') killed stress-ng" >> $L
pkill -x fio 2>/dev/null && echo "$(date '+%T') killed fio" >> $L
case "$H" in
  mementos)
    for u in fan-watchdog md1200-fan; do
      systemctl is-active --quiet $u || { systemctl start $u; echo "$(date '+%T') started $u" >> $L; }
    done
    echo "$(date '+%T') done: fan-watchdog $(systemctl is-active fan-watchdog), md1200-fan $(systemctl is-active md1200-fan)" >> $L ;;
  ryuji)
    systemctl is-active --quiet ryuji-fan-guard || { systemctl start ryuji-fan-guard; echo "$(date '+%T') started ryuji-fan-guard" >> $L; }
    echo "$(date '+%T') done: ryuji-fan-guard $(systemctl is-active ryuji-fan-guard)" >> $L ;;
  sojiro)
    if [ -x /var/tmp/sojiro-floor-restore.sh ]; then
      /var/tmp/sojiro-floor-restore.sh >> $L 2>&1 && echo "$(date '+%T') sojiro offset restore ran" >> $L
    fi
    echo "$(date '+%T') done" >> $L ;;
  *) echo "$(date '+%T') done" >> $L ;;
esac
