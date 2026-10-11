#!/usr/bin/env python3
# prom-range-csv (2026-10-10): pull lab-watch's columns from Prometheus as one CSV over any window (for history before
# lab-watch started, or to re-sample). Uses lab-watch.py's own query table, so the columns match data/watch.csv.
# usage: prom-range-csv.py "YYYY-MM-DD HH:MM" "YYYY-MM-DD HH:MM"|now <step s> <out.csv>
import csv, datetime, importlib.util, json, os, sys, time, urllib.parse, urllib.request

def load_queries():
    # read the Q table out of lab-watch.py without running its loop
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lab-watch.py')).read()
    head = src[:src.index('def window(ts):')]
    head = head.replace("DATA, STOP = sys.argv[1], datetime.datetime.strptime(sys.argv[2], '%Y-%m-%d %H:%M').timestamp()", '')
    head = head.replace("CSV, EVENTS = os.path.join(DATA, 'watch.csv'), os.path.join(DATA, 'watch-events.log')", '')
    ns = {}
    exec(compile(head, 'lab-watch-head', 'exec'), ns)
    return ns['Q']

def ts(s):
    return time.time() if s == 'now' else datetime.datetime.strptime(s, '%Y-%m-%d %H:%M').timestamp()

Q = load_queries()
start, end, step, out = ts(sys.argv[1]), ts(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
cols, data = list(Q), {}
for k, q in Q.items():
    vals = {}
    t = start
    while t < end:   # Prometheus caps points per query; fetch in chunks of 10,000 steps
        t2 = min(end, t + step * 10000)
        u = 'http://10.0.0.3:9090/api/v1/query_range?' + urllib.parse.urlencode({'query': q, 'start': t, 'end': t2, 'step': step})
        r = json.load(urllib.request.urlopen(u, timeout=120))['data']['result']
        if r:
            vals.update({int(float(a)): float(b) for a, b in r[0]['values']})
        t = t2 + step
    data[k] = vals
times = sorted(set(t for v in data.values() for t in v))
with open(out, 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['time'] + cols)
    for t in times:
        w.writerow([datetime.datetime.fromtimestamp(t).strftime('%F %T')] + [round(data[k][t], 2) if t in data[k] else '' for k in cols])
print(f'{len(times)} rows x {len(cols)} columns -> {out}')
