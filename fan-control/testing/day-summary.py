#!/usr/bin/env python3
# day-summary (2026-10-10): summarize a lab-watch style CSV (data/watch.csv or prom-range-csv output): per-column
# percentiles, time spent at each fan level, hourly medians of chosen columns, and the busiest disk periods.
# usage: day-summary.py <csv> [start "YYYY-MM-DD HH:MM"] [end]
import collections, csv, datetime, statistics as st, sys

rows = list(csv.DictReader(open(sys.argv[1])))
T = lambda s: datetime.datetime.strptime(s, '%Y-%m-%d %H:%M:%S')
if len(sys.argv) > 2:
    a = datetime.datetime.strptime(sys.argv[2], '%Y-%m-%d %H:%M')
    b = datetime.datetime.strptime(sys.argv[3], '%Y-%m-%d %H:%M') if len(sys.argv) > 3 else datetime.datetime.max
    rows = [r for r in rows if a <= T(r['time']) < b]
def col(c):
    return [(T(r['time']), float(r[c])) for r in rows if r.get(c) not in ('', None)]
def pct(vals, p):
    s = sorted(vals)
    return s[min(len(s) - 1, int(p / 100 * len(s)))]
print(f'{len(rows)} rows, {rows[0]["time"]} to {rows[-1]["time"]}')
print('\npercentiles (p1 / p50 / p99 / max):')
skip = ('time', 'window')
for c in rows[0]:
    if c in skip:
        continue
    v = [x for _, x in col(c)]
    if v:
        print(f'  {c:<15} {pct(v, 1):8.1f} {pct(v, 50):8.1f} {pct(v, 99):8.1f} {max(v):8.1f}   (n={len(v)})')
print('\ntime at each level (minutes):')
for c in ('r720_pct', 'shelf_pct', 'ryuji_off'):
    cnt = collections.Counter(round(x) for _, x in col(c))
    print(f'  {c:<10} ' + ', '.join(f'{k}: {n}' for k, n in sorted(cnt.items())))
HOURLY = ('inlet', 'nas_nvme0', 'rack_a', 'r720_cpu', 'r720_hdd', 'shelf_pct', 'shelf_drive', 'ryuji_sio1', 'sojiro_cpu',
          'sojiro_cpufan', 'nas_tctl', 'mementos_busy', 'shelf_rd', 'nas_rd', 'sojiro_wr')
print('\nhourly medians (max for disk MB/s and busy %):')
print('  hour         ' + ' '.join(f'{c[:11]:>11}' for c in HOURLY))
by = collections.defaultdict(lambda: collections.defaultdict(list))
for r in rows:
    h = T(r['time']).strftime('%m-%d %H:00')
    for c in HOURLY:
        if r.get(c) not in ('', None):
            by[h][c].append(float(r[c]))
for h in sorted(by):
    out = []
    for c in HOURLY:
        v = by[h][c]
        if not v:
            out.append(f'{"-":>11}')
        else:
            x = max(v) if c.endswith(('_rd', '_wr', '_busy')) else st.median(v)
            out.append(f'{x:11.1f}')
    print(f'  {h}  ' + ' '.join(out))
print('\ndisk activity spans (>= 50 MB/s, or sojiro writes >= 20):')
for c, lim in (('shelf_rd', 50), ('shelf_wr', 50), ('vm_rd', 50), ('nas_rd', 50), ('nas_wr', 50), ('sojiro_wr', 20)):
    spans, cur = [], None
    for t, x in col(c):
        if x >= lim:
            cur = [t, t, x] if cur is None else [cur[0], t, max(cur[2], x)]
        elif cur is not None:
            spans.append(cur); cur = None
    if cur:
        spans.append(cur)
    spans = [s for s in spans if (s[1] - s[0]).total_seconds() >= 120]
    if spans:
        print(f'  {c:<10} ' + '; '.join(f'{s[0]:%m-%d %H:%M}-{s[1]:%H:%M} (peak {s[2]:.0f})' for s in spans[:12]))
