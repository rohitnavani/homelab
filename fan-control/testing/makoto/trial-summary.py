#!/usr/bin/env python3
# trial-summary: makoto-fan behaviour from msample.csv in BLOCK-minute blocks since FROM (epoch or HH:MM today):
# package W and temp (median/max), fan rpm and duty (min-max), card/DIMM/NVMe max, and how often the duty changed.
# usage: trial-summary.py FROM [block minutes, default 10]
import csv, statistics as st, sys, time

D = '/home/rohit/lab-thermal-2026-10-19/data/'
a = sys.argv[1]
t0 = int(a) if a.isdigit() else int(time.mktime(time.strptime(time.strftime('%Y-%m-%d ') + a, '%Y-%m-%d %H:%M')))
B = float(sys.argv[2]) * 60 if len(sys.argv) > 2 else 600
rows = [r for r in csv.DictReader(open(D + 'msample.csv')) if r['fan1'] and int(r['epoch']) >= t0]
print('block    W med/max  cpu med/max  rpm1       rpm4       duty1   duty4   card ddr nvme  changes')
blk = {}
for r in rows:
    blk.setdefault((int(r['epoch']) - t0) // B, []).append(r)
for k in sorted(blk):
    rs = blk[k]
    f = lambda c: [float(r[c]) for r in rs if r[c] not in ('', 'na')]
    sets = [r['set'] for r in rs]
    d1 = [int(s.split('/')[0]) for s in sets if '/' in s]
    d4 = [int(s.split('/')[1]) for s in sets if '/' in s]
    ch = sum(1 for x, y in zip(sets, sets[1:]) if x != y)
    print(f"{time.strftime('%H:%M', time.localtime(t0 + k * B))}  {st.median(f('rapl_w')):5.1f}/{max(f('rapl_w')):4.1f}  "
          f"{st.median(f('pkg')):5.0f}/{max(f('pkg')):3.0f}   {min(f('fan1')):4.0f}-{max(f('fan1')):4.0f}  "
          f"{min(f('fan4')):4.0f}-{max(f('fan4')):4.0f}  {min(d1):3d}-{max(d1):3d} {min(d4):3d}-{max(d4):3d}   "
          f"{max(f('card')):3.0f} {max(max(f('ddra')), max(f('ddrb'))):3.0f} {max(f('nvme')):4.0f}  {ch:3d}")
