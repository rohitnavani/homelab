#!/usr/bin/env python3
# analyze_exp4 (2026-10-07): per-phase results of the overnight shelf map (shelf-exp4.csv, shelf-exp3's columns).
# For each phase: the last-10-min means, and an exponential fit T(t) = A + B exp(-t / tau) of the drive average, the
# hottest drive and the backplane over the whole phase (grid search on tau 5-180 min, least squares for A and B), so
# A is where the phase was heading. Rise = A minus the room (mementos inlet, exponential moving average with a 45 min
# time constant, i.e. lagged like the drives). The inlet reads in 1C steps, so the room's mean over the phase is the
# better reference while it is flat. usage: analyze_exp4.py <shelf-exp4.csv> [more CSVs, e.g. part1 first]
import math, sys

rows = []
for path in sys.argv[1:]:
    hdr, day0, last_sec, day = None, None, None, 0
    for l in open(path):
        l = l.rstrip('\n')
        if l.startswith('time,'):
            hdr = l.split(','); continue
        if l.startswith('#'):
            if ' start' in l and day0 is None:
                day0 = l.split()[1]            # '# 2026-10-07 18:01:29 start, ...'
            continue
        if not hdr or not l:
            continue
        r = dict(zip(hdr, l.split(',')))
        h, m, s = (int(x) for x in r['time'].split(':'))
        sec = h * 3600 + m * 60 + s
        if last_sec is not None and sec < last_sec - 3600:
            day += 1                           # past midnight
        last_sec = sec
        try:
            rows.append({'t': day * 86400 + sec, 'phase': r['phase'], 'pmin': float(r['phase_min']), 'set': int(r['shelf_set']),
                         'rpm': float(r['rpm_avg'] or 'nan'), 'dmax': float(r['drive_max']), 'davg': float(r['drive_avg']),
                         'bp': float(r['BP']), 'sim': float(r['SIM']), 'exp': float(r['EXP']), 'inlet': float(r['inlet'])})
        except (ValueError, KeyError):
            pass
rows.sort(key=lambda r: r['t'])
# lagged room: EMA of the inlet with a 45 min time constant
ema = None
for i, r in enumerate(rows):
    if ema is None:
        ema = r['inlet']
    else:
        dt = r['t'] - rows[i - 1]['t']
        ema += (r['inlet'] - ema) * (1 - math.exp(-dt / 2700))
    r['room'] = ema

def fit(ts, ys):
    best = None
    for tau in [x * 60 for x in range(5, 181)]:
        e = [math.exp(-t / tau) for t in ts]
        n = len(ts); se, sy, see, sey = sum(e), sum(ys), sum(x * x for x in e), sum(x * y for x, y in zip(e, ys))
        det = n * see - se * se
        if abs(det) < 1e-9:
            continue
        b = (n * sey - se * sy) / det; a = (sy - b * se) / n
        sse = sum((a + b * x - y) ** 2 for x, y in zip(e, ys))
        if best is None or sse < best[0]:
            best = (sse, a, b, tau)
    return best

phases = []
for r in rows:
    if not phases or phases[-1][0] != r['phase']:
        phases.append([r['phase'], []])
    phases[-1][1].append(r)
print(f"{'phase':<6} {'set':>3} {'rpm':>5} {'min':>5} | last 10 min: {'max':>5} {'avg':>6} {'BP':>5} {'SIM':>5} {'EXP':>5} {'room':>5} | "
      f"fit avg: {'A':>5} {'tau':>4} rise | fit max: {'A':>5} {'tau':>4} rise | fit BP: {'A':>5} rise")
for name, rs in phases:
    t0 = rs[0]['t']; dur = (rs[-1]['t'] - t0) / 60
    last = [r for r in rs if r['t'] >= rs[-1]['t'] - 600]
    mean = lambda k, xs=last: sum(r[k] for r in xs) / len(xs)
    room = sum(r['room'] for r in rs[-30:]) / len(rs[-30:])
    out = f"{name:<6} {rs[0]['set']:>3} {mean('rpm', rs):5.0f} {dur:5.0f} | {'':12}{mean('dmax'):5.1f} {mean('davg'):6.2f} {mean('bp'):5.1f} {mean('sim'):5.1f} {mean('exp'):5.1f} {room:5.1f} | "
    for k in ('davg', 'dmax', 'bp'):
        f = fit([r['t'] - t0 for r in rs], [r[k] for r in rs]) if len(rs) >= 15 else None
        if f:
            out += f"{'':9}{f[1]:5.1f} {f[3] / 60:4.0f} {f[1] - room:+5.1f}" if k != 'bp' else f"{'':8}{f[1]:5.1f} {f[1] - room:+5.1f}"
            out += ' |' if k != 'bp' else ''
        else:
            out += ' (too short) |'
    print(out)
