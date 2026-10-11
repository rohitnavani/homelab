#!/usr/bin/env python3
# lab-status (2026-10-10): a compact summary of lab-watch's CSV for a check-in: min / median / max of the key columns
# over the last N minutes (default 60), the latest row, and the events logged in that time.
# usage: lab-status.py [minutes] [data dir]
import csv, datetime, os, statistics as st, sys

mins = float(sys.argv[1]) if len(sys.argv) > 1 else 60
data = sys.argv[2] if len(sys.argv) > 2 else os.path.expanduser('~/lab-thermal-2026-10-10/data')
since = datetime.datetime.now() - datetime.timedelta(minutes=mins)
rows = [r for r in csv.DictReader(open(os.path.join(data, 'watch.csv')))
        if datetime.datetime.strptime(r['time'], '%Y-%m-%d %H:%M:%S') >= since]
GROUPS = [
    ('room', ['inlet', 'nas_nvme0', 'nas_systin', 'sojiro_mb', 'makoto_mb', 'rack_a']),
    ('mementos', ['r720_pct', 'r720_cpu', 'r720_exh', 'r720_hdd', 'r720_ssd', 'r720_dimm', 'mementos_busy']),
    ('shelf', ['shelf_pct', 'shelf_drive', 'shelf_bp', 'shelf_sim', 'shelf_exp']),
    ('ryuji', ['ryuji_off', 'ryuji_sio1', 'ryuji_cpu', 'ryuji_vr', 'ryuji_dimm', 'ryuji_cpufan', 'ryuji_sysfan', 'ryuji_busy']),
    ('sojiro', ['sojiro_cpu', 'sojiro_cpufan', 'sojiro_sysfan', 'sojiro_busy']),
    ('makoto', ['makoto_cpu', 'makoto_fan1', 'makoto_fan4']),
    ('tinynas', ['nas_tctl', 'nas_fan2', 'tinynas_busy']),
    ('disks MB/s', ['shelf_rd', 'shelf_wr', 'vm_rd', 'nas_rd', 'nas_wr', 'sojiro_wr']),
]
def f(x):
    return f'{x:.0f}' if abs(x) >= 100 else f'{x:.1f}'
print(f'{len(rows)} rows since {since:%H:%M}' + (f', last {rows[-1]["time"]} ({rows[-1]["window"]})' if rows else ''))
for g, cols in GROUPS:
    parts = []
    for c in cols:
        vals = [float(r[c]) for r in rows if r.get(c) not in ('', None)]
        if vals:
            lo, md, hi = min(vals), st.median(vals), max(vals)
            parts.append(f'{c} {f(md)}' if lo == hi else f'{c} {f(md)} ({f(lo)}-{f(hi)})')
    print(f'  {g:<10} ' + '; '.join(parts))
ev = os.path.join(data, 'watch-events.log')
if os.path.exists(ev):
    lines = [l.rstrip() for l in open(ev) if l[:19] >= since.strftime('%Y-%m-%d %H:%M:%S')]
    print(f'events ({len(lines)}):')
    for l in lines[-25:]:
        print('  ' + l)
