#!/usr/bin/env python3
# analyze_fixedfan: per step of /var/tmp/mementos-fixedfan.csv: last 3 min means, peaks, CPU slope over the last 3 min
# (C/min; ~0 = settled), C per package W, and the notes. usage: analyze_fixedfan.py <csv>
import csv, sys
lines = open(sys.argv[1]).read().splitlines()
for l in lines:
    if l.startswith('#') and ('phase' in l or 'load off' in l or 'auto' in l or 'fans 60' in l or 'done' in l):
        print(l)
rows = [r for r in csv.DictReader(l for l in lines if not l.startswith('#'))]
def f(r, k):
    try:
        return float(r[k])
    except (KeyError, ValueError, TypeError):
        return None
ph = {}
for r in rows:
    ph.setdefault(r['phase'], []).append(r)
print(f'\n{"step":<9} {"fan%":>4} {"rpm":>6} {"load":>4} {"pkgW":>5} {"wallW":>5} {"cpu0":>5} {"cpu1":>5} {"max":>4} {"slope":>6} '
      f'{"C/W":>5} {"exh":>4} {"dimm":>4} {"room":>4}')
for name, rs in ph.items():
    t1 = int(rs[-1]['epoch']); last = [r for r in rs if int(r['epoch']) >= t1 - 180]
    def m(k):
        v = [f(r, k) for r in last if f(r, k) is not None]
        return sum(v) / len(v) if v else float('nan')
    hot = [max(f(r, 'cpu0'), f(r, 'cpu1')) for r in last]
    ts = [(int(r['epoch']) - t1) / 60 for r in last]
    n = len(ts); mt = sum(ts) / n; mh = sum(hot) / n
    den = sum((t - mt) ** 2 for t in ts)
    slope = sum((t - mt) * (h - mh) for t, h in zip(ts, hot)) / den if den else 0
    peak = max(max(f(r, 'cpu0'), f(r, 'cpu1')) for r in rs)
    pk = m('pkg_w'); cw = (mh - m('room')) / (pk / 2) if pk and pk > 20 else float('nan')
    print(f'{name:<9} {m("fan_pct"):4.0f} {m("rpm"):6.0f} {m("workers"):4.0f} {pk:5.0f} {m("w"):5.0f} {m("cpu0"):5.1f} {m("cpu1"):5.1f} '
          f'{peak:4.0f} {slope:+6.2f} {cw:5.2f} {m("exh"):4.0f} {m("dimm"):4.0f} {m("room"):4.0f}')
