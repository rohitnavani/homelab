#!/usr/bin/env python3
# tone_timeline (2026-10-08): minute by minute through a ryuji-floor run, the strongest tone between LO and HI Hz in
# morgana's mic log next to ryuji's DCMI watts and fan speeds. A tone that rises for many minutes at a constant load,
# glides down after it, and drops when the chassis fans speed up follows a component's temperature (on 10-08: ryuji's
# PSU fan); coil whine would switch with the load, and the BMC-controlled fans follow their own rpm.
# usage: tone_timeline.py <profile.csv> <mic.csv> [lo hi]
import collections, csv, statistics as st, sys
prof, micf = sys.argv[1], sys.argv[2]
LO, HI = (int(sys.argv[3]), int(sys.argv[4])) if len(sys.argv) > 4 else (400, 1000)
rows = [r for r in csv.DictReader(l for l in open(prof) if not l.startswith('#'))]
mic = [r for r in csv.DictReader(open(micf)) if r['epoch'].isdigit()]
tcol = [k for k in mic[0] if k.startswith('tones')][0]
t0 = int(rows[0]['epoch'])
bymin = collections.OrderedDict()
for r in rows: bymin.setdefault((int(r['epoch']) - t0) // 60, []).append(r)
print(f'min  phase           W  cpuF  sysF | strongest {LO}-{HI} Hz tone (minute median: Hz, dBFS)')
for k, rs in bymin.items():
    a = t0 + k * 60; tones = []
    for r in mic:
        if a <= int(r['epoch']) < a + 60:
            best = None
            for tok in (r[tcol] or '').split(';'):
                if tok.count(':') == 2:
                    hz, prom, dbfs = tok.split(':')
                    if LO <= int(hz) <= HI and (best is None or float(dbfs) > best[1]): best = (int(hz), float(dbfs))
            if best: tones.append(best)
    tt = f'{st.median(t[0] for t in tones):5.0f} Hz {st.median(t[1] for t in tones):6.1f}' if tones else '   -'
    m = lambda key: st.median(float(x[key]) for x in rs if x[key] not in ('', None))
    print(f"{k:3d}  {rs[0]['phase']:<13} {m('dcmi_w'):4.0f} {m('cpu_fan0'):5.0f} {m('sys_fan'):5.0f} | {tt}  ({len(tones)} clips)")
