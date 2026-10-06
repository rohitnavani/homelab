#!/usr/bin/env python3
# analyze_mementos_steps: per-phase summary of /var/tmp/mementos-steps.csv (copied locally): last 3 min means,
# peaks, time to the first fan-watchdog step above 25% / to auto, and the notes (load stops, skips).
# usage: analyze_mementos_steps.py <mementos-steps.csv>
import csv, sys
lines = open(sys.argv[1]).read().splitlines()
for l in lines:
    if l.startswith('#') and ('stopped' in l or 'skipped' in l or 'start' in l or 'done' in l or 'RAPL' in l):
        print(l)
rows = [r for r in csv.DictReader(l for l in lines if not l.startswith('#'))]
def f(r, k):
    try:
        return float(r[k])
    except (KeyError, ValueError, TypeError):
        return None
ph = {}
for r in rows:
    ph.setdefault(r['phase'], []).append(r)
print(f'\n{"phase":<12} {"min":>4} {"cap":>4} {"load":>4} {"pkgW":>5} {"wallW":>5} {"cpu":>5} {"cpuMax":>6} {"dimm":>5} {"exh":>5} '
      f'{"fan%":>5} {"fan%max":>7} {"rpm":>5} {"inlet":>5} {"room":>5} auto')
for name, rs in ph.items():
    t1 = int(rs[-1]['epoch']); last = [r for r in rs if int(r['epoch']) >= t1 - 180]
    def m(k, src=last):
        v = [f(r, k) for r in src if f(r, k) is not None]
        return sum(v) / len(v) if v else float('nan')
    def mx(k):
        v = [f(r, k) for r in rs if f(r, k) is not None]
        return max(v) if v else float('nan')
    auto = any(r['mode'] == 'auto' for r in rs)
    print(f'{name:<12} {(t1 - int(rs[0]["epoch"])) / 60:4.1f} {rs[0]["cap"]:>4} {m("load"):4.0f} {m("pkg_w"):5.0f} {m("w"):5.0f} '
          f'{m("cpu"):5.1f} {mx("cpu"):6.0f} {m("dimm"):5.1f} {m("exh"):5.1f} {m("pct"):5.1f} {mx("pct"):7.0f} {m("rpm"):5.0f} '
          f'{m("inlet"):5.1f} {m("room"):5.1f} {"AUTO" if auto else ""}')
