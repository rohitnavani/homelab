#!/usr/bin/env python3
# refit_shelf_model (2026-10-07): fit the md1200 harness's plant model to the overnight shelf map. For every phase of
# shelf-exp4 (and part 1) it fits T(t) = A + B exp(-t/tau) to the hottest drive and the backplane (as analyze_exp4.py),
# then fits, over the phases:
#   rise of the hottest drive over the room = R20 * (3290 / rpm) ** EXPO    (log-linear least squares)
#   tau of the hottest drive                = TAU * (3290 / rpm) ** TEXP   (log-linear least squares)
# and reports the backplane's offset from the hottest drive per phase (the harness uses BP = T + BP_OFF). Phases
# shorter than MIN_MIN minutes are left out. usage: refit_shelf_model.py <csv> [<csv> ...]
import math, subprocess, sys, os
sys.path.insert(0, os.path.dirname(__file__))
MIN_MIN = 45
src = open(os.path.join(os.path.dirname(__file__), 'analyze_exp4.py')).read()
g = {'__name__': 'lib'}
sys_argv = sys.argv
sys.argv = [sys.argv[0]] + sys.argv[1:]
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    exec(src, g)           # builds g['phases'] (name, rows) and g['fit']
fit, phases = g['fit'], g['phases']
pts = []
print(f"{'phase':<6} {'%':>3} {'rpm':>5} {'min':>4} {'room':>5} {'A_max':>6} {'tau':>4} {'rise':>5} {'A_bp':>5} {'bp_off':>6}")
for name, rs in phases:
    dur = (rs[-1]['t'] - rs[0]['t']) / 60
    if dur < MIN_MIN:
        continue
    t0 = rs[0]['t']; ts = [r['t'] - t0 for r in rs]
    fm, fb = fit(ts, [r['dmax'] for r in rs]), fit(ts, [r['bp'] for r in rs])
    room = sum(r['inlet'] for r in rs) / len(rs)
    rpm = sum(r['rpm'] for r in rs if r['rpm'] == r['rpm']) / max(1, sum(1 for r in rs if r['rpm'] == r['rpm']))
    rise = fm[1] - room
    pts.append((rpm, rise, fm[3], fm[1], fb[1]))
    print(f"{name:<6} {rs[0]['set']:>3} {rpm:5.0f} {dur:4.0f} {room:5.1f} {fm[1]:6.1f} {fm[3]/60:4.0f} {rise:5.1f} {fb[1]:5.1f} {fb[1]-fm[1]:+6.1f}")
def loglin(xs, ys):
    lx = [math.log(3290 / x) for x in xs]; ly = [math.log(y) for y in ys]
    n = len(lx); mx, my = sum(lx) / n, sum(ly) / n
    sxx = sum((a - mx) ** 2 for a in lx)
    b = sum((a - mx) * (c - my) for a, c in zip(lx, ly)) / sxx if sxx else 0
    return math.exp(my - b * mx), b
if len(pts) >= 2:
    r20, expo = loglin([p[0] for p in pts], [p[1] for p in pts])
    tau, texp = loglin([p[0] for p in pts], [p[2] for p in pts])
    print(f'\nfit: R20 {r20:.2f}C  EXPO {expo:.2f}   TAU {tau:.0f} s ({tau/60:.0f} min at 20%)  TEXP {texp:.2f}')
    print(f'harness: R20={r20:.2f} EXPO={expo:.2f} TAU={tau:.0f} TEXP={texp:.2f}; BP offset mean {sum(p[4]-p[3] for p in pts)/len(pts):+.1f}C')
else:
    print('not enough complete phases yet')
