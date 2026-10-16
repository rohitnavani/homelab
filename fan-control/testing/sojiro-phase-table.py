#!/usr/bin/env python3
# sojiro-phase-table (2026-10-15): one row per phase of a sojiro-floor run, joined with morgana's mic on epoch.
# Settled = the last LAST minutes of each phase (default 4 of 6). Per phase: medians of CPU0_TEMP, coretemp package,
# MB_TEMP1, CPU0_FAN and SYS_FAN1, the hottest CPU over the whole phase; mic dB(A) median, the 500 Hz and 1 kHz octaves
# and the strongest tone between 300 and 2,000 Hz; dB(A) against the mean of the two offset-0 holds (o0_a, o0_b).
# usage: sojiro-phase-table.py <run.csv> --mic <mic.csv> [--last MIN]
import statistics as st, sys

args = sys.argv[1:]
def opt(name, default=None):
    global args
    if name in args:
        i = args.index(name); v = args[i + 1]; args = args[:i] + args[i + 2:]; return v
    return default
mic_p, last = opt('--mic'), float(opt('--last', 4))
rows, hdr = [], None
for line in open(args[0]):
    if line.startswith('#'):
        continue
    f = line.rstrip('\n').split(',')
    if hdr is None:
        hdr = f; continue
    r = dict(zip(hdr, f))
    try:
        r['t'] = int(r['epoch'])
    except (ValueError, KeyError):
        continue
    rows.append(r)
phases = []
for r in rows:
    if not phases or phases[-1]['name'] != r['phase']:
        phases.append({'name': r['phase'], 'offset': r['offset'], 'rows': []})
    phases[-1]['rows'].append(r)
mic, mh = [], None
for line in open(mic_p):
    f = line.rstrip('\n').split(',')
    if mh is None:
        mh = f; continue
    try:
        m = dict(zip(mh, f)); m['t'] = float(m['epoch']); m['A'] = float(m['A'])
        m['tones'] = next((v for k, v in m.items() if k.startswith('tones')), '')
        mic.append(m)
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
def tone(m):
    best = None
    for t in (m.get('tones') or '').split(';'):
        try:
            fq, p, l = t.split(':'); fq, l = float(fq), float(l)
        except ValueError:
            continue
        if 300 <= fq <= 2000 and (best is None or l > best[1]):
            best = (fq, l)
    return best
for p in phases:
    t1 = p['rows'][-1]['t']; t0 = max(p['rows'][0]['t'] - 20, t1 - last * 60)
    sr = [r for r in p['rows'] if r['t'] >= t0]
    mc = [m for m in mic if t0 <= m['t'] <= t1]
    p.update({k: med([num(r[k]) for r in sr]) for k in ('cpu', 'pkg', 'mb', 'cpu_fan', 'sys_fan')})
    p['maxcpu'] = max((num(r['cpu']) or 0) for r in p['rows'])
    p['dba'] = med([m['A'] for m in mc]); p['n'] = len(mc)
    p['o500'] = med([num(m.get('o500')) for m in mc]); p['o1k'] = med([num(m.get('o1000')) for m in mc])
    tz = [x for x in (tone(m) for m in mc) if x]
    p['tone'] = f'{med([x[0] for x in tz]):.0f} Hz, {med([x[1] for x in tz]):.0f}' if tz else ''
refs = [p['dba'] for p in phases if p['name'].startswith('o0') and p['dba'] is not None]
ref = sum(refs) / len(refs) if refs else None
f = lambda v, d=0: '' if v is None else f'{v:.{d}f}'
print('| phase | offset | CPU (max) | pkg | MB | CPU fan | SYS fan | clips | dB(A) | vs offset 0 | 500 Hz | 1 kHz | tone 300-2000 Hz |')
print('|---|---|---|---|---|---|---|---|---|---|---|---|---|')
for p in phases:
    vs = '' if ref is None or p['dba'] is None else f"{p['dba'] - ref:+.2f}"
    print(f"| {p['name']} | {p['offset']} | {f(p['cpu'])} ({f(p['maxcpu'])}) | {f(p['pkg'])} | {f(p['mb'])} | {f(p['cpu_fan'])} | "
          f"{f(p['sys_fan'])} | {p['n']} | {f(p['dba'], 2)} | {vs} | {f(p['o500'], 1)} | {f(p['o1k'], 1)} | {p['tone']} |")
