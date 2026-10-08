#!/usr/bin/env python3
# Sweep the shelf model's uncertain parameters around the 2026-10-08 fit and compare two md1200-fan versions on every
# scenario of test_md1200_scenarios.py (81 models, about 12 min). Prints, per scenario, the worst peak % and drive
# temperature of each version and in how many models the new one peaks higher. OUT=<file> also saves the raw results.
# usage: python3 -I tests/sweep_md1200_scenarios.py <old controller source> <new controller source>
import itertools, json, os, subprocess, sys
HARNESS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_md1200_scenarios.py')
old, new = sys.argv[1], sys.argv[2]
grid = list(itertools.product((900, 1200, 1800), (0.5, 1.0, 2.0), (16.5, 18.0, 19.5), (1.0, 1.15, 1.3)))  # around the 10-08 fit
rows = []
for tau, texp, r20, expo in grid:
    env = dict(os.environ, TAU=str(tau), TEXP=str(texp), R20=str(r20), EXPO=str(expo), JSON='1')
    res = {}
    for src in (old, new):
        out = subprocess.run([sys.executable, '-I', HARNESS, src], env=env, capture_output=True, text=True, timeout=300).stdout
        res[src] = json.loads(out.strip().splitlines()[-1])
    rows.append(((tau, texp, r20, expo), res))
for sc in 'ABCDEFGHI':
    o = [r[old][sc] for _, r in rows]; n = [r[new][sc] for _, r in rows]
    worse_peak = sum(1 for a, b in zip(o, n) if b['peak'] > a['peak'])
    worse_ch = sum(1 for a, b in zip(o, n) if b['changes'] > a['changes'] + 2)
    print(f"{sc}: old peak max {max(x['peak'] for x in o):2d}% / new {max(x['peak'] for x in n):2d}%; "
          f"old Tmax max {max(x['tmax'] for x in o):5.1f} / new {max(x['tmax'] for x in n):5.1f}; "
          f"changes old max {max(x['changes'] for x in o):3d} mean {sum(x['changes'] for x in o)/len(o):5.1f} / "
          f"new max {max(x['changes'] for x in n):3d} mean {sum(x['changes'] for x in n)/len(n):5.1f}; "
          f"new worse peak in {worse_peak}/{len(rows)}, >2 more changes in {worse_ch}")
os.environ.get('OUT') and json.dump([[list(k), {os.path.basename(s): v for s, v in r.items()}] for k, r in rows], open(os.environ['OUT'], 'w'))
