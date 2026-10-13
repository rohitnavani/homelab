#!/usr/bin/env python3
# phase-table (2026-10-13): one row per phase of a ryuji-floor run, joined with turbostat and the mic on epoch.
# Phase boundaries come from the run CSV's "# <epoch> ... phase <name>: offset <o>, <n> busy threads" notes.
# Settled = the last LAST minutes of each phase (default 4; the whole phase if shorter). Per phase: sensor medians over
# the settled window (CPU0/1, SIO1, VR, DIMM, CPU and system fans, DCMI wall W, RAPL package W), the hottest CPU and VR
# over the whole phase, thermal-throttle events during the phase (kernel counters, all cores / per package), whether
# the test dropped the load; turbostat (Busy%, busy MHz, package temp, package W); mic (dB(A), 500 Hz and 1 kHz octaves,
# the strongest tone in 400-1000 Hz outside the room's fixed 786-797 Hz tone, share of clips in the 680-830 Hz band).
# usage: phase-table.py <run.csv> [--turbo turbostat.tsv] [--mic mic.csv ...] [--last MIN] [--md]
import re, statistics as st, sys

args = sys.argv[1:]
def opt(name, many=False):
    global args
    vals = []
    while name in args:
        i = args.index(name); vals.append(args[i + 1]); args = args[:i] + args[i + 2:]
    return vals if many else (vals[0] if vals else None)
turbo_p, mic_ps, last, md = opt('--turbo'), opt('--mic', True), float(opt('--last') or 4), '--md' in args
args = [a for a in args if a != '--md']
run = args[0]

hdr, rows, phases, stops, end = None, [], [], [], None
for line in open(run):
    line = line.rstrip('\n')
    if line.startswith('#'):
        m = re.match(r'# (\d+) .*?phase (\S+): offset (\S+), (\d+) busy', line)
        if m:
            phases.append({'name': m.group(2), 't0': int(m.group(1)), 'off': m.group(3), 'load': int(m.group(4))})
        elif 'load stopped' in line or 'ABORT' in line:
            stops.append((int(line.split()[1]), line.split(' ', 4)[-1]))
        elif re.search(r' done$| BMC SEL entries at end', line):
            end = int(line.split()[1])
    elif hdr is None:
        hdr = line.split(',')
    elif line[:1].isdigit():
        rows.append(dict(zip(hdr, line.split(','))))
last_epoch = int(rows[-1]['epoch']) if rows else 0
for i, p in enumerate(phases):
    p['t1'] = phases[i + 1]['t0'] if i + 1 < len(phases) else (end or last_epoch)

turbo = []
if turbo_p:
    for line in open(turbo_p):
        f = line.split()
        try:
            turbo.append((float(f[0]), float(f[1]), float(f[2]), float(f[4]), float(f[5])))  # t, busy%, MHz, pkgtmp, pkgW
        except (ValueError, IndexError):
            pass
mic = []
for mp in mic_ps:
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
            hz, _, lvl = t.split(':'); hz, lvl = float(hz), float(lvl)
        except ValueError:
            continue
        if 400 <= hz <= 1000 and not 786 <= hz <= 797 and (best is None or lvl > best[1]):
            best = (hz, lvl)
    return best

out = []
for p in phases:
    w0 = max(p['t0'], p['t1'] - last * 60)
    win = [r for r in rows if w0 <= int(r['epoch']) < p['t1']]
    allp = [r for r in rows if p['t0'] <= int(r['epoch']) < p['t1']]
    if not allp:
        continue
    g = lambda k, rs=win: med([num(r.get(k)) for r in rs])
    mx = lambda k: max([num(r.get(k)) or 0 for r in allp])
    thr = lambda k: (num(allp[-1].get(k)) or 0) - (num(allp[0].get(k)) or 0) if allp[0].get(k) not in (None, '') else None
    tb = [x for x in turbo if w0 <= x[0] < p['t1']]
    mc = [r for r in mic if w0 <= r['t'] < p['t1']]
    tones = [tone(r) for r in mc]
    tz = [x for x in tones if x]
    stopped = [s for t, s in stops if p['t0'] <= t < p['t1']]
    out.append({
        'phase': p['name'], 'off': p['off'], 'load': p['load'], 'min': round((p['t1'] - p['t0']) / 60, 1),
        'cpu0': g('cpu0'), 'cpu1': g('cpu1'), 'cpu_max': max(mx('cpu0'), mx('cpu1')), 'sio1': g('sio1'),
        'vr': g('vr'), 'vr_max': mx('vr'), 'dimm': g('dimm'), 'cfan': g('cpu_fan0'), 'sfan': g('sys_fan'),
        'wall_w': g('dcmi_w'), 'pkg_w': (g('pkg0_w') or 0) + (g('pkg1_w') or 0) if g('pkg0_w') is not None else None,
        'room': g('room'), 'thr_core': thr('thr_core'), 'thr_pkg': thr('thr_pkg'),
        'busy%': med([x[1] for x in tb]), 'mhz': med([x[2] for x in tb]), 'ts_pkgw': med([x[4] for x in tb]),
        'dBA': med([num(r.get('A')) for r in mc]), 'o500': med([num(r.get('o500')) for r in mc]),
        'o1k': med([num(r.get('o1000')) for r in mc]),
        'tone': med([x[0] for x in tz]), 'tone_lvl': med([x[1] for x in tz]),
        'band%': round(100 * sum(1 for x in tz if 680 <= x[0] <= 830) / len(mc)) if mc else None,
        'stopped': 'load stopped' if stopped else '',
    })
cols = ['phase', 'off', 'load', 'min', 'cpu0', 'cpu1', 'cpu_max', 'sio1', 'vr', 'vr_max', 'dimm', 'cfan', 'sfan',
        'wall_w', 'pkg_w', 'ts_pkgw', 'busy%', 'mhz', 'thr_core', 'thr_pkg', 'room', 'dBA', 'o500', 'o1k', 'tone',
        'tone_lvl', 'band%', 'stopped']
def fmt(v):
    if v is None:
        return ''
    if isinstance(v, float):
        return f'{v:.2f}' if abs(v) < 100 and v != int(v) else f'{v:.0f}'
    return str(v)
if md:
    print('| ' + ' | '.join(cols) + ' |'); print('|' + '---|' * len(cols))
    for o in out:
        print('| ' + ' | '.join(fmt(o[c]) for c in cols) + ' |')
else:
    print(','.join(cols))
    for o in out:
        print(','.join(fmt(o[c]) for c in cols))
for t, s in stops:
    print(f'# stop {t}: {s}', file=sys.stderr)
