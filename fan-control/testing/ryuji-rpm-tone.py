#!/usr/bin/env python3
# ryuji-rpm-tone (2026-10-08): per phase of a ryuji-floor run, the CPU-fan rpm against the mic (dB(A) median after SKIP s, octave
# bands, and the strongest tone in 600-760 Hz), so the speeds that ring the ~700 Hz resonance stand out.
# usage: ryuji-rpm-tone.py <profile.csv> <mic.csv> [skip s]
import collections, csv, statistics as st, sys
prof, micf = sys.argv[1], sys.argv[2]; SKIP = int(sys.argv[3]) if len(sys.argv) > 3 else 45
rows = [r for r in csv.DictReader(l for l in open(prof) if not l.startswith('#'))]
mic = [r for r in csv.DictReader(open(micf)) if r['epoch'].isdigit()]
tcol = [k for k in mic[0] if k.startswith('tones')][0]
ph = collections.OrderedDict()
for r in rows: ph.setdefault(r['phase'], []).append(r)
out = []
for p, rs in ph.items():
    a, b = int(rs[0]['epoch']) + SKIP, int(rs[-1]['epoch']) + 10
    late = [r for r in rs if int(r['epoch']) >= a] or rs
    mr = [r for r in mic if a <= int(r['epoch']) <= b]
    if not mr: continue
    m = lambda k, xs=late: st.median(float(x[k]) for x in xs if x[k] not in ('', None))
    tone = []
    for r in mr:
        best = None
        for tok in (r[tcol] or '').split(';'):
            if tok.count(':') == 2:
                hz, prom, dbfs = tok.split(':')
                if 600 <= int(hz) <= 760 and (best is None or float(dbfs) > best[1]): best = (int(hz), float(dbfs))
        tone.append(best)
    hits = [t for t in tone if t]
    tl = f"{st.median(h[1] for h in hits):6.1f} @ {st.median(h[0] for h in hits):4.0f} Hz in {len(hits)}/{len(tone)}" if hits else '   -'
    out.append((p, m('offset'), m('load'), m('cpu_fan0'), m('cpu_fan1'), m('sys_fan'), max(m('cpu0'), m('cpu1')),
                st.median(float(r['A']) for r in mr), st.median(float(r['o500']) for r in mr),
                st.median(float(r['o1000']) for r in mr), st.median(float(r['o2000']) for r in mr), tl, len(mr)))
print(f"{'phase':<11} {'off':>4} {'ld':>2} {'cpu fans':>11} {'sys':>5} {'CPU':>4} | {'dB(A)':>7} {'o500':>6} {'o1k':>6} {'o2k':>6} | 600-760 Hz tone (median dBFS @ Hz in clips)")
for o in out:
    print(f"{o[0]:<11} {o[1]:>4.0f} {o[2]:>2.0f} {o[3]:>5.0f}/{o[4]:<5.0f} {o[5]:>5.0f} {o[6]:>4.0f} | {o[7]:7.2f} {o[8]:6.1f} {o[9]:6.1f} {o[10]:6.1f} | {o[11]}")
