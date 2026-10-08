#!/usr/bin/env python3
# prom-pdu-csv (2026-10-07): write the rack PDU current from Prometheus (cyberpower_pdu_bank_load_deciamps, scraped
# by futaba every 30 s, SNMP GET only) as pdu.csv ("YYYY-MM-DD HH:MM:SS,amps"), the format ac-verify.py,
# baseline_compare.py and window_compare.py read (pdu-log was removed 10-07). usage: prom-pdu-csv.py "YYYY-MM-DD HH:MM" out.csv
import datetime, json, sys, time, urllib.parse, urllib.request
start = datetime.datetime.strptime(sys.argv[1], '%Y-%m-%d %H:%M').timestamp()
rows, t0 = [], start
while t0 < time.time():
    t1 = min(time.time(), t0 + 10000 * 30)
    q = urllib.parse.urlencode({'query': 'cyberpower_pdu_bank_load_deciamps{bank="1"} / 10', 'start': t0, 'end': t1, 'step': 30})
    r = json.load(urllib.request.urlopen('http://10.0.0.3:9090/api/v1/query_range?' + q, timeout=60))['data']['result']
    if r:
        rows += [(float(t), float(v)) for t, v in r[0]['values']]
    t0 = t1 + 30
with open(sys.argv[2], 'w') as f:
    for t, a in rows:
        f.write(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t)) + f',{a:.1f}\n')
print(len(rows), 'rows')
