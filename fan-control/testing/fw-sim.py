#!/usr/bin/env python3
# fw-sim (2026-10-15): simulate fan-watchdog rules on mementos with the fitted CPU model (mementos-thermal-model.py:
# heatsink node + die offset, coretemp package 0; the iDRAC CPU reading fan-watchdog uses is package 0 + 5C, rounded).
# Only the CPU curve matters at these loads (exhaust, inlet, HDD, SSD and DIMM stayed under their curves in every run).
# Loop period 45 s (30 s sleep + ~15 s of reads, as logged). Noise per fan % from the 10-15 R720 sweep at the mic spot.
# usage: fw-sim.py [--validate]
import math, random, sys

PRM = dict(r10=0.46650797738103883, n=1.0026021020024558, C=472.87983678421193, Rdh=0.26824419611075223,
           a0=4.601268107848098)
PKG0_W = {0: 21.3, 6: 65.4, 12: 75.6, 18: 95.4, 24: 113.5, 36: 113.4, 48: 113.1}
IDRAC_OFFSET = 5
LOOP = 45
DB = [(10, 0), (15, .27), (20, 1.07), (25, 2.42), (30, 3.22), (35, 5.52), (36, 5.47), (37, 5.91), (38, 7.11),
      (39, 8.12), (40, 8.99), (41, 7.57), (42, 9.89), (43, 11.31), (44, 12.36), (45, 13.2), (50, 13.75), (60, 16)]
BURST_MED = [(18, 2), (0, 1.5), (6, 3), (18, 1), (0, 0.5), (12, 4), (18, 5), (0, 2), (6, 1.5), (12, 3), (0, 3), (6, 1.5),
             (18, 2)]
BURST_ALL = [(48, 1.5), (0, 2), (24, 3), (6, 2), (36, 1), (0, 1), (48, 4), (12, 2), (0, 3), (36, 2), (6, 1.5),
             (48, 0.5), (0, 1.5), (24, 5)]


def db(f):
    for (a, x), (b, y) in zip(DB, DB[1:]):
        if f <= b:
            return x + (y - x) * (max(f, a) - a) / (b - a)
    return DB[-1][1]


def cpu_want(t, pts=((68, 10), (82, 35), (88, 55))):
    if t <= pts[0][0]:
        return 10
    for (x0, p0), (x1, p1) in zip(pts, pts[1:]):
        if t <= x1:
            return p0 + (p1 - p0) * (t - x0) // (x1 - x0)
    return pts[-1][1]


def rule_v42(pct, tgt, cpu, st):
    if tgt >= pct + 2 or (tgt > pct and cpu >= 85):
        return tgt
    if tgt <= pct - 2 or (tgt == 10 and pct > 10):
        step = 3 if pct > 35 else 1
        return max(pct - step, tgt)
    return pct


def make_fast_cool(step_cool=4, cool_cpu=60):
    """v4.3 candidate: when every sensor asks for the floor and the CPU is clearly cool, step down faster"""
    def rule(pct, tgt, cpu, st):
        if tgt >= pct + 2 or (tgt > pct and cpu >= 85):
            return tgt
        if tgt <= pct - 2 or (tgt == 10 and pct > 10):
            step = 3 if pct > 35 else 1
            if tgt == 10 and cpu <= cool_cpu:
                step = max(step, step_cool)
            return max(pct - step, tgt)
        return pct
    return rule


def make_prop(div=4, cap=5, cool_cpu=None, step_cool=None):
    """v4.3 candidate: step down by a share of the gap to the target (at least 1, at most cap)"""
    def rule(pct, tgt, cpu, st):
        if tgt >= pct + 2 or (tgt > pct and cpu >= 85):
            return tgt
        if tgt <= pct - 2 or (tgt == 10 and pct > 10):
            step = max(1, min(cap, (pct - tgt) // div))
            if pct > 35:
                step = max(step, 3)
            if cool_cpu is not None and tgt == 10 and cpu <= cool_cpu:
                step = max(step, step_cool)
            return max(pct - step, tgt)
        return pct
    return rule


def simulate(load_seq, rule, tin=23.0, start_pct=10, dt=1.0, loop=LOOP, phase0=0.0):
    """load_seq: [(workers, minutes)]. Returns per-second lists of (t, workers, pct, Tp, cpu_reading)."""
    r10, n, C, Rdh, a0 = PRM['r10'], PRM['n'], PRM['C'], PRM['Rdh'], PRM['a0']
    p0 = PKG0_W[load_seq[0][0]]
    rha = r10 * (start_pct / 10) ** -n
    th = tin + p0 * rha     # settled start
    pct, t, nxt, st = start_pct, 0.0, loop * phase0, {}
    out, sched, acc = [], [], 0.0
    for w, mins in load_seq:
        sched.append((acc, w)); acc += mins * 60
    end, cpu = acc, None
    i = 0
    while t < end:
        while i + 1 < len(sched) and t >= sched[i + 1][0]:
            i += 1
        w = sched[i][1]
        p = PKG0_W[w]
        tp = th + Rdh * p + a0
        if t >= nxt:
            cpu = int(round(tp + IDRAC_OFFSET))
            pct = rule(pct, cpu_want(cpu), cpu, st)
            nxt += loop
        rha = r10 * (pct / 10) ** -n
        th += (p - (th - tin) / rha) / C * dt
        out.append((t, w, pct, tp, cpu))
        t += dt
    return out


def metrics(out):
    e = sum(10 ** (db(x[2]) / 10) for x in out) / len(out)
    mean_db = 10 * math.log10(e)
    ups, downs, last, ch = 0, 0, out[0][2], []
    for x in out:
        if x[2] > last:
            ups += 1
        elif x[2] < last:
            downs += 1
        last = x[2]
    above20 = sum(1 for x in out if x[2] > 20) / 60
    above30 = sum(1 for x in out if x[2] > 30) / 60
    maxcpu = max(x[4] or 0 for x in out)
    t80 = sum(1 for x in out if (x[4] or 0) >= 80) / 60
    return dict(mean_db=round(mean_db, 2), above20=round(above20, 1), above30=round(above30, 1), max_pct=max(x[2] for x in out),
                maxcpu=maxcpu, min80=round(t80, 1), ups=ups, downs=downs)


def realistic(seed, hours=6):
    """VM-host-like day: idle gaps of 2-20 min, bursts of 0.5-6 min at 6-24 workers, the odd long job"""
    rnd = random.Random(seed)
    seq, tot = [(0, 5)], 5
    while tot < hours * 60:
        gap = rnd.choice([2, 3, 5, 8, 12, 20])
        w = rnd.choice([6, 6, 12, 12, 18, 24, 48])
        mins = rnd.choice([0.5, 1, 1, 2, 3, 6]) if rnd.random() < 0.9 else rnd.choice([15, 30])
        seq += [(w, mins), (0, gap)]
        tot += gap + mins
    return seq


RULES = {
    'v4.2': rule_v42,
    'cool4@60': make_fast_cool(4, 60),
    'cool3@60': make_fast_cool(3, 60),
    'cool5@62': make_fast_cool(5, 62),
    'prop/4 cap4': make_prop(4, 4),
    'prop/3 cap5': make_prop(3, 5),
    'prop/4 cap3 +cool4@60': make_prop(4, 3, 60, 4),

}

if __name__ == '__main__':
    if '--validate' in sys.argv:
        out = simulate([(0, 5)] + BURST_MED + [(0, 20)], rule_v42, tin=23.0)
        for x in out[::30]:
            print(f'{int(x[0]) // 60:3d}:{int(x[0]) % 60:02d} w{x[1]:2d} pct {x[2]:2d} tp {x[3]:5.1f} cpu {x[4]}')
        sys.exit()
    scen = {'burst_med': [(0, 5)] + BURST_MED + [(0, 20)], 'burst_all': [(0, 5)] + BURST_ALL + [(0, 20)],
            'steps': [(0, 10), (6, 20), (12, 20), (18, 20), (24, 20), (0, 25)],
            'full_onset': [(0, 10), (48, 20), (0, 20), (48, 15), (0, 20)]}
    for s in range(1, 6):
        scen[f'day{s}'] = realistic(s)
    print('| scenario | rule | mean dB (energy) | min >20% | min >30% | max % | max CPU | min >=80C | ups | downs |')
    print('|---|---|---|---|---|---|---|---|---|---|')
    for sn, sq in scen.items():
        for rn, rf in RULES.items():
            m = metrics(simulate(sq, rf))
            print(f"| {sn} | {rn} | {m['mean_db']} | {m['above20']} | {m['above30']} | {m['max_pct']} | {m['maxcpu']} | "
                  f"{m['min80']} | {m['ups']} | {m['downs']} |")
