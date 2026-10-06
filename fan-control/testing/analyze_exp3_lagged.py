#!/usr/bin/env python3
# Companion to analyze_exp2.py for the exp3 CSV: keeps only rows after the last "start" marker
# (default: the 2026-10-06 00:18:08 run), writes that trimmed CSV (for analyze_exp2.py), and compares
# phases as rise over a LAGGED inlet. The room cools/warms over hours; the R720 inlet sensor follows
# within minutes but the shelf drives take tens of minutes, so plain "drive - inlet" jumps when the
# room changes. Lagged inlet = exponential moving average of inlet with tau 30 and 60 min.
# usage: analyze_exp3_lagged.py <exp3.csv> [trimmed_out.csv] [start-marker-substring]
import math, sys

src = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else None
marker = sys.argv[3] if len(sys.argv) > 3 else '2026-10-06 00:18:08 start'
lines = open(src).read().splitlines()
hdr = next(l for l in lines if l.startswith('time,'))
cols = hdr.split(',')
start = max(i for i, l in enumerate(lines) if l.startswith('#') and marker in l)
kept = [l for l in lines[start:] if l.strip()]
if out:
    with open(out, 'w') as f:
        f.write(hdr + '\n' + '\n'.join(kept) + '\n')

rows = []
day = 0
prev_sec = None
for l in kept:
    if l.startswith('#'):
        continue
    r = dict(zip(cols, l.split(',')))
    h, m, s = (int(x) for x in r['time'].split(':'))
    sec = h * 3600 + m * 60 + s
    if prev_sec is not None and sec < prev_sec - 3600:
        day += 1                       # crossed midnight
    prev_sec = sec
    r['t'] = (sec + day * 86400) / 60.0
    rows.append(r)

def num(r, k):
    try:
        return float(r[k])
    except (KeyError, ValueError):
        return None

# EMA of inlet, irregular sampling (about 1/min). Seeded with the first 10 min mean.
seed = [num(r, 'inlet') for r in rows[:10] if num(r, 'inlet') is not None]
ema = {30: sum(seed) / len(seed), 60: sum(seed) / len(seed)}
prev_t = rows[0]['t']
for r in rows:
    x = num(r, 'inlet')
    dt = r['t'] - prev_t
    prev_t = r['t']
    for tau in ema:
        if x is not None:
            a = 1 - math.exp(-dt / tau) if dt > 0 else 0
            ema[tau] += a * (x - ema[tau])
        r[f'lag{tau}'] = ema[tau]

phases = []
for r in rows:
    if not phases or phases[-1][0] != r['phase']:
        phases.append((r['phase'], []))
    phases[-1][1].append(r)

print('Per phase, last 10 min means (lag30/lag60 = inlet EMA with 30/60 min time constant):')
print(f'{"phase":<10} {"min":>5} {"shelf":>5} {"r720%":>5} {"rpm":>5} {"inlet":>5} {"lag30":>5} {"lag60":>5} '
      f'{"hot":>5} {"avg":>5} {"BP":>4} {"SIM":>4} {"EXP":>4} | {"avg-in":>6} {"avg-l30":>7} {"avg-l60":>7} {"hot-l60":>7} {"BP-l60":>6}')
for name, rs in phases:
    tl = rs[-1]['t']
    last = [r for r in rs if r['t'] >= tl - 10]
    def m(k):
        v = [num(r, k) if k in r and not isinstance(r[k], float) else r.get(k) for r in last]
        v = [x for x in v if x is not None]
        return sum(v) / len(v) if v else float('nan')
    inl, l30, l60 = m('inlet'), m('lag30'), m('lag60')
    avg, hot, bp = m('drive_avg'), m('drive_max'), m('BP')
    dur = rs[-1]['t'] - rs[0]['t']
    print(f'{name:<10} {dur:5.0f} {rs[0]["shelf_set"]:>5} {m("r720_pct"):5.1f} {m("rpm_avg"):5.0f} {inl:5.2f} {l30:5.2f} {l60:5.2f} '
          f'{hot:5.2f} {avg:5.2f} {bp:4.1f} {m("SIM"):4.1f} {m("EXP"):4.1f} | {avg - inl:6.2f} {avg - l30:7.2f} {avg - l60:7.2f} {hot - l60:7.2f} {bp - l60:6.2f}')
    extra = f'r720 rpm {m("r720_rpm"):.0f}, cpu {m("cpu"):.1f}, exh {m("exh"):.1f}, dimm {m("dimm_max"):.1f}, r720 W {m("r720_w"):.0f}'
    print(f'{"":<10} {extra}')
r = rows[-1]
print(f'\nlatest {r["time"]} {r["phase"]} min {r["phase_min"]}: hot {r["drive_max"]} avg {r["drive_avg"]} BP {r["BP"]} '
      f'SIM {r["SIM"]} EXP {r["EXP"]} inlet {r["inlet"]} (lag60 {r["lag60"]:.2f}) rpm {r["rpm_avg"]} '
      f'r720 {r["r720_pct"]}% {r["r720_rpm"]} rpm cpu {r["cpu"]} dimm {r["dimm_max"]} serial_err {r["serial_errors"]} '
      f'status {r["fan_status"]} {r["emm_status"]} {r["psu_status"]}')
