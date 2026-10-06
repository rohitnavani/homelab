#!/usr/bin/env python3
# analyze_ryuji_profile: per-phase settled values for a ryuji-profile run, joined with the room reference.
# usage: analyze_ryuji_profile.py <profile.csv> <room.csv> [hdd.csv]
#   profile.csv  /var/tmp/ryuji-profile-<label>.csv from ryuji (epoch column)
#   room.csv     makoto data/room.csv (epoch, local time, mementos inlet; 1C resolution)
#   hdd.csv      optional /var/tmp/ryuji-hdd-<label>.csv (epoch, one column per drive)
# "settled" = mean of the last min(4 min, half the phase). Room: mean over the same window, and a 30 min EMA for the
# slow board sensors (SIO/PCH). cpu_K/W = (hottest CPU - room) / package W of that socket.
import math, sys

def read_csv(p):
    rows, notes = [], []
    lines = open(p).read().splitlines()
    hdr = None
    for l in lines:
        if l.startswith('#'):
            notes.append(l); continue
        if hdr is None:
            hdr = l.split(','); continue
        rows.append(dict(zip(hdr, l.split(','))))
    return rows, notes

def f(r, k):
    try:
        return float(r[k])
    except (KeyError, ValueError, TypeError):
        return None

prof, notes = read_csv(sys.argv[1])
room = []
for l in open(sys.argv[2]):
    p = l.strip().split(',')
    try:
        room.append((int(p[0]), float(p[2])))
    except (ValueError, IndexError):
        pass
hdd = read_csv(sys.argv[3])[0] if len(sys.argv) > 3 else []

# room EMA (30 min) evaluated at each room sample
ema, prev, room_ema = None, None, []
for t, v in room:
    if ema is None:
        ema = v
    else:
        ema += (1 - math.exp(-(t - prev) / 1800)) * (v - ema)
    prev = t
    room_ema.append((t, ema))

def window_mean(series, a, b):
    v = [x for t, x in series if a <= t <= b]
    return sum(v) / len(v) if v else None

phases = []
for r in prof:
    if not phases or phases[-1][0] != r['phase']:
        phases.append((r['phase'], []))
    phases[-1][1].append(r)

for n in notes:
    if 'stopped' in n or 'ABORT' in n or 'failed' in n or 'start' in n or 'done' in n:
        print(n)
print()
hdr = ('phase      off   load  pkgW  cpu0 cpu1 cpuK/W  cfan0 cfan1 sysf  sio1 s1-r30  sio2  pch  vr dimm  hdd   W   room  r30')
print(hdr)
for name, rs in phases:
    t_end = int(rs[-1]['epoch']); t_start = int(rs[0]['epoch'])
    win = min(240, max(60, (t_end - t_start) / 2))
    last = [r for r in rs if int(r['epoch']) >= t_end - win]
    def m(k):
        v = [f(r, k) for r in last if f(r, k) is not None]
        return sum(v) / len(v) if v else float('nan')
    a, b = t_end - win, t_end
    rm = window_mean(room, a, b) or float('nan')
    r30 = window_mean(room_ema, a, b) or float('nan')
    pk0, pk1 = m('pkg0_w'), m('pkg1_w')
    c0, c1 = m('cpu0'), m('cpu1')
    kw = max((c0 - rm) / pk0 if pk0 > 3 else float('nan'), (c1 - rm) / pk1 if pk1 > 3 else float('nan'))
    hv = []
    for r in hdd:
        if a <= int(r['epoch']) <= b:
            hv += [float(x) for k, x in r.items() if k != 'epoch' and x]
    hmax = max(hv) if hv else float('nan')
    print(f'{name:<10} {rs[0]["offset"]:>4} {m("load"):5.0f} {pk0 + pk1:5.0f} {c0:5.1f} {c1:4.1f} {kw:6.2f}  '
          f'{m("cpu_fan0"):5.0f} {m("cpu_fan1"):5.0f} {m("sys_fan"):4.0f}  {m("sio1"):4.1f} {m("sio1") - r30:6.1f}  '
          f'{m("sio2"):4.1f} {m("pch"):4.1f} {m("vr"):3.0f} {m("dimm"):4.1f} {hmax:4.0f} {m("dcmi_w"):4.0f}  {rm:4.1f} {r30:4.1f}')
print('\nBMC CPU-fan curve points (all samples): CPU temp -> CPU fan rpm, by offset')
pts = {}
for r in prof:
    c, fan = f(r, 'cpu1'), f(r, 'cpu_fan1')
    if c is not None and fan is not None:
        pts.setdefault(r['offset'].lstrip('g'), {}).setdefault(int(c // 5 * 5), []).append(fan)
for off, d in sorted(pts.items()):
    print(f'  offset {off:>4}: ' + '  '.join(f'{k}-{k+4}C {sum(v)/len(v):.0f}' for k, v in sorted(d.items())))
