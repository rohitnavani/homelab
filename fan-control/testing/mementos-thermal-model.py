#!/usr/bin/env python3
# mementos-thermal-model (2026-10-15): fit a two-node model of mementos's hotter CPU socket (package 0) to
# mementos-steps runs, for simulating fan-watchdog rules. Inputs per sample: package 0 power (W), the R720 fan % that
# fan-watchdog set, the iDRAC inlet. Heatsink node: C dTh/dt = P - (Th - Tin) / Rha(f), Rha(f) = r10 * (f / 10)^-n;
# die: Tp = Th + Rdh * P + a0. Fit by Nelder-Mead on coretemp package 0 (20 s samples). Also fits the offset between
# fan-watchdog's CPU reading (the iDRAC's hottest "Temp") and coretemp package 0.
# usage: mementos-thermal-model.py <run.csv> [...]   prints the parameters and the per-run error
import json, math, sys


def load(path):
    hdr, rows = None, []
    for line in open(path):
        if line.startswith('#'):
            continue
        f = line.rstrip('\n').split(',')
        if hdr is None:
            hdr = f
            continue
        r = dict(zip(hdr, f))
        try:
            rows.append({'t': int(r['epoch']), 'p': float(r['pkg0_w']) if r['pkg0_w'] else None,
                         'tp': float(r['pkg0_t']), 'tp1': float(r['pkg1_t']), 'cpu': float(r['cpu']),
                         'f': float(r['pct']), 'tin': float(r['inlet']), 'load': int(r['load'])})
        except (ValueError, KeyError):
            continue
    last = 21.0
    for r in rows:
        if r['p'] is None:
            r['p'] = last
        last = r['p']
    return rows


def sim(rows, prm, th0=None):
    r10, n, c, rdh, a0 = prm
    th = rows[0]['tp'] - rdh * rows[0]['p'] - a0 if th0 is None else th0
    out = []
    for i, r in enumerate(rows):
        if i:
            dt = r['t'] - rows[i - 1]['t']
            q = rows[i - 1]
            rha = r10 * (max(q['f'], 5) / 10) ** -n
            steps = max(1, int(dt // 2))
            for _ in range(steps):
                th += (q['p'] - (th - q['tin']) / rha) / c * (dt / steps)
        out.append(th + rdh * r['p'] + a0)
    return out


def err(runs, prm):
    if prm[0] <= 0 or prm[1] <= 0 or prm[2] <= 1 or prm[3] < 0 or abs(prm[4]) > 15:
        return 1e9
    e, n = 0.0, 0
    for rows in runs:
        for r, y in zip(rows, sim(rows, prm)):
            e += (y - r['tp']) ** 2
            n += 1
    return e / n


def nelder_mead(f, x0, scale, iters=600):
    pts = [list(x0)] + [[x + (scale[j] if j == i else 0) for j, x in enumerate(x0)] for i in range(len(x0))]
    vals = [f(p) for p in pts]
    for _ in range(iters):
        order = sorted(range(len(pts)), key=lambda i: vals[i])
        pts, vals = [pts[i] for i in order], [vals[i] for i in order]
        cen = [sum(p[j] for p in pts[:-1]) / (len(pts) - 1) for j in range(len(x0))]
        refl = [c + (c - w) for c, w in zip(cen, pts[-1])]
        fr = f(refl)
        if fr < vals[0]:
            exp = [c + 2 * (c - w) for c, w in zip(cen, pts[-1])]
            fe = f(exp)
            pts[-1], vals[-1] = (exp, fe) if fe < fr else (refl, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = refl, fr
        else:
            con = [c + 0.5 * (w - c) for c, w in zip(cen, pts[-1])]
            fc = f(con)
            if fc < vals[-1]:
                pts[-1], vals[-1] = con, fc
            else:
                pts = [pts[0]] + [[b + 0.5 * (x - b) for b, x in zip(pts[0], p)] for p in pts[1:]]
                vals = [vals[0]] + [f(p) for p in pts[1:]]
    i = min(range(len(pts)), key=lambda i: vals[i])
    return pts[i], vals[i]


if __name__ == '__main__':
    runs = [load(p) for p in sys.argv[1:]]
    best, e = nelder_mead(lambda p: err(runs, p), [0.4, 0.5, 300, 0.1, 0], [0.1, 0.2, 100, 0.05, 2])
    best, e = nelder_mead(lambda p: err(runs, p), best, [0.05, 0.1, 50, 0.03, 1])
    print(json.dumps({'r10': best[0], 'n': best[1], 'C': best[2], 'Rdh': best[3], 'a0': best[4], 'rmse': math.sqrt(e)}))
    for path, rows in zip(sys.argv[1:], runs):
        y = sim(rows, best)
        d = [a - r['tp'] for a, r in zip(y, rows)]
        print(f'{path}: rmse {math.sqrt(sum(x * x for x in d) / len(d)):.2f}C, max err {max(d, key=abs):+.1f}C, '
              f'{len(d)} samples')
    # iDRAC CPU reading vs coretemp: fan-watchdog's cpu against the hotter package, at the samples where it changed
    diffs = []
    for rows in runs:
        for a, b in zip(rows, rows[1:]):
            if b['cpu'] != a['cpu']:
                diffs.append(b['cpu'] - max(b['tp'], b['tp1']))
    diffs.sort()
    print(f'iDRAC cpu - max(pkg) at updates: median {diffs[len(diffs) // 2]:+.1f}, p10 {diffs[len(diffs) // 10]:+.1f}, '
          f'p90 {diffs[9 * len(diffs) // 10]:+.1f} (n={len(diffs)})')
