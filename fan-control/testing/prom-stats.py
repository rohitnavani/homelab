#!/usr/bin/env python3
# prom-stats: min / p50 / max (and % of time at each value for small integer series) of Prometheus series over a window.
# usage: prom-stats.py "<start YYYY-MM-DD HH:MM>" "<end>" [label=promql ...]   (defaults: the lab thermal set)
import json, statistics as st, sys, time, urllib.parse, urllib.request
P = 'http://10.0.0.3:9090/api/v1/query_range'
a = int(time.mktime(time.strptime(sys.argv[1], '%Y-%m-%d %H:%M')))
b = int(time.mktime(time.strptime(sys.argv[2], '%Y-%m-%d %H:%M')))
Q = dict(x.split('=', 1) for x in sys.argv[3:]) or {
    'room_inlet': 'lab_r720_temp_celsius{sensor="inlet"}',
    'pdu_A': 'cyberpower_pdu_bank_load_deciamps{bank="1"}/10',
    'shelf_pct': 'lab_md1200_fan_percent',
    'shelf_drive': 'lab_md1200_temp_celsius{sensor="drive"}',
    'shelf_bp': 'lab_md1200_temp_celsius{sensor="backplane"}',
    'r720_pct': 'lab_r720_fan_percent',
    'r720_cpu': 'lab_r720_temp_celsius{sensor="cpu"}',
    'r720_hdd': 'lab_r720_temp_celsius{sensor="hdd"}',
    'ryuji_offset': 'lab_ryuji_fan_offset',
    'ryuji_sio1': 'lab_ryuji_temp_celsius{sensor="sio1"}',
    'ryuji_cpu': 'lab_ryuji_temp_celsius{sensor="cpu"}',
}
for k, q in Q.items():
    url = P + '?' + urllib.parse.urlencode({'query': q, 'start': a, 'end': b, 'step': 60})
    try:
        r = json.load(urllib.request.urlopen(url, timeout=30))['data']['result']
    except Exception as e:
        print(f'{k:<13} error {e}'); continue
    if not r:
        print(f'{k:<13} no data'); continue
    v = [float(x[1]) for x in r[0]['values']]
    s = f'{k:<13} n={len(v):<4} min {min(v):6.1f}  p50 {st.median(v):6.1f}  max {max(v):6.1f}'
    if all(x == int(x) for x in v) and len(set(v)) <= 6:
        s += '   ' + ', '.join(f'{int(x)}: {100 * v.count(x) / len(v):.0f}%' for x in sorted(set(v)))
    print(s)
