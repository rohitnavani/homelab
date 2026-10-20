#!/usr/bin/env python3
# steps-table: per fanstep phase, medians over the last LAST minutes from msample.csv (2 s sampler): CPU package temp,
# RAPL W, busy threads, fan rpm, DIMM/MB/card/NVMe; plus a fitted end value for the package temperature
# (T(t) = Tinf - (Tinf - T0) exp(-t / tau) over the whole phase, if it is still moving).
# usage: steps-table.py STEPS.csv [msample.csv] [last minutes, default 3]
import csv, math, statistics as st, sys

steps = list(csv.DictReader(open(sys.argv[1])))
ms = [r for r in csv.DictReader(open(sys.argv[2] if len(sys.argv) > 2 else
                                      '/home/rohit/lab-thermal-2026-10-19/data/msample.csv')) if r['fan1']]
LAST = float(sys.argv[3]) if len(sys.argv) > 3 else 3
phases = []
for r in steps:
    if not phases or phases[-1][0] != r['label']:
        phases.append([r['label'], int(r['epoch']), int(r['epoch']), r['f1'], r['f4'], r['workers']])
    phases[-1][2] = int(r['epoch'])


def fit(ts, ys):
    """least squares over tau on a grid; returns (Tinf, tau) or None"""
    best = None
    for tau in [20 * 1.15 ** i for i in range(40)]:
        x = [1 - math.exp(-t / tau) for t in ts]
        n, sx, sy = len(x), sum(x), sum(ys)
        sxx, sxy = sum(v * v for v in x), sum(a * b for a, b in zip(x, ys))
        den = n * sxx - sx * sx
        if abs(den) < 1e-9:
            continue
        b = (n * sxy - sx * sy) / den
        a = (sy - b * sx) / n
        err = sum((a + b * v - y) ** 2 for v, y in zip(x, ys))
        if best is None or err < best[0]:
            best = (err, a + b, tau)
    return best[1:] if best else None


print(f"{'phase':10s} {'f1/f4 %':>8s} {'w':>2s} {'min':>4s} | {'pkg':>4s} {'fit':>9s} {'W':>5s} {'busy':>4s} "
      f"{'rpm1':>5s} {'rpm4':>5s} | {'ddr':>3s} {'mb':>3s} {'card':>4s} {'nvme':>4s}")
for lab, t0, t1, f1, f4, w in phases:
    rows = [r for r in ms if t0 <= int(r['epoch']) <= t1]
    tail = [r for r in rows if int(r['epoch']) >= t1 - LAST * 60]
    if len(tail) < 5:
        continue
    med = lambda k: st.median(float(r[k]) for r in tail if r[k] not in ('', 'na'))
    f = fit([int(r['epoch']) - t0 for r in rows], [float(r['pkg']) for r in rows]) if len(rows) > 20 else None
    fs = f'{f[0]:5.1f}/{f[1]:3.0f}s' if f else ''
    print(f"{lab:10s} {f1:>3s}/{f4:<4s} {w:>2s} {(t1 - t0) / 60:4.1f} | {med('pkg'):4.0f} {fs:>9s} {med('rapl_w'):5.1f} "
          f"{med('busy'):4.1f} {med('fan1'):5.0f} {med('fan4'):5.0f} | {max(med('ddra'), med('ddrb')):3.0f} "
          f"{med('mb'):3.0f} {med('card'):4.0f} {med('nvme'):4.0f}")
