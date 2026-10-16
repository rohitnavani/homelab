#!/usr/bin/env python3
# mementos-phase-table (2026-10-14): one row per phase of a mementos-steps run (the 2026-10-13 CSV format), joined with
# morgana's mic on epoch. Settled = the last LAST minutes of each phase (default 10; the whole phase if shorter).
# Per phase: medians of fan %, CPU (fan-watchdog's), both coretemp packages, DIMM, exhaust, HDD, SSD, package W per
# socket; the hottest CPU and the highest fan % over the whole phase; throttle events during it; dB(A), the 500 Hz and
# 1 kHz octaves, and the strongest tone between 300 and 2,000 Hz.
# usage: mementos-phase-table.py <run.csv> --mic <mic.csv> [--mic ...] [--last MIN] [--ref dBA]
import re, statistics as st, sys

args = sys.argv[1:]
def opt(name, many=False):
    global args
    vals = []
    while name in args:
        i = args.index(name); vals.append(args[i + 1]); args = args[:i] + args[i + 2:]
    return vals if many else (vals[0] if vals else None)
mics, last, ref = opt('--mic', True), float(opt('--last') or 10), opt('--ref')
run = args[0]
hdr, rows, phases, end = None, [], [], None
for line in open(run):
    line = line.rstrip('\n')
    if line.startswith('#'):
        m = re.match(r'# (\d+) .*?phase (\S+): (\d+) workers', line)
        if m:
            phases.append({'name': m.group(2), 't0': int(m.group(1)), 'load': int(m.group(3))})
        elif line.endswith(' done'):
            end = int(line.split()[1])
    elif hdr is None:
        hdr = line.split(',')
    elif line[:1].isdigit():
        rows.append(dict(zip(hdr, line.split(','))))
for i, p in enumerate(phases):
    p['t1'] = phases[i + 1]['t0'] if i + 1 < len(phases) else (end or int(rows[-1]['epoch']))
mic = []
for mp in mics:
    mh = None
    for line in open(mp):
        f = line.rstrip('\n').split(',')
        if mh is None:
            mh = f; continue
        try:
            r = dict(zip(mh, f)); r['t'] = float(r['epoch'])
            r['tones'] = next((v for k, v in r.items() if k.startswith('tones')), '')
            mic.append(r)
        except (ValueError, KeyError):
            pass
def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
def med(xs):
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else None
def tone(r):
    best = None
    for t in (r.get('tones') or '').split(';'):
        try:
            f, p, l = t.split(':'); f, l = float(f), float(l)
        except ValueError:
            continue
        if 300 <= f <= 2000 and (best is None or l > best[1]):
            best = (f, l)
    return best
print('| phase | load | min | fan % | max % | CPU | max CPU | pkg0/1 C | DIMM | exh | HDD | SSD | pkg W | thr | dB(A) | vs ref | 500 Hz | 1 kHz | tone 300-2000 Hz |')
print('|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|')
for p in phases:
    t0, t1 = p['t0'], p['t1']
    s0 = max(t0, t1 - last * 60)
    allr = [r for r in rows if t0 <= int(r['epoch']) < t1]
    sr = [r for r in allr if int(r['epoch']) >= s0]
    if not sr:
        continue
    g = lambda k, rr=sr: med([num(r.get(k)) for r in rr])
    thr = None
    if allr:
        a, b = num(allr[0].get('thr_core')), num(allr[-1].get('thr_core'))
        thr = int(b - a) if a is not None and b is not None else None
    mc = [r for r in mic if s0 <= r['t'] < t1]
    dba = med([num(r.get('A')) for r in mc])
    tz = [x for x in (tone(r) for r in mc) if x]
    pw = (g('pkg0_w') or 0) + (g('pkg1_w') or 0)
    fmt = lambda v, d=0: '' if v is None else (f'{v:.{d}f}')
    vs = '' if dba is None or ref is None else f'{dba - float(ref):+.1f}'
    ts = f'{med([x[0] for x in tz]):.0f} Hz, {med([x[1] for x in tz]):.0f}' if tz else ''
    print(f"| {p['name']} | {p['load']} | {(t1 - t0) / 60:.0f} | {fmt(g('pct'))} | {fmt(max((num(r.get('pct')) or 0) for r in allr))} | "
          f"{fmt(g('cpu'))} | {fmt(max((num(r.get('cpu')) or 0) for r in allr))} | {fmt(g('pkg0_t'))}/{fmt(g('pkg1_t'))} | "
          f"{fmt(g('dimm'))} | {fmt(g('exh'))} | {fmt(g('hdd'))} | {fmt(g('ssd'))} | {pw:.0f} | {'' if thr is None else thr} | "
          f"{fmt(dba, 2)} | {vs} | {fmt(med([num(r.get('o500')) for r in mc]), 1)} | {fmt(med([num(r.get('o1000')) for r in mc]), 1)} | {ts} |")
