#!/usr/bin/env python3
# psu-tone (2026-10-10): follow ryuji's PSU-fan tone in the mic log, minute by minute. The PSU tone sits near 450 Hz at
# idle and climbs to 620-950 Hz under load; the room's fixed ~791 Hz tone (every clip, ~-86 dBFS) is reported apart.
# Per minute: median dB(A), the 500 Hz and 1 kHz octaves, the strongest tone in 400-1000 Hz outside 786-797 Hz
# (median frequency and level of each clip's strongest), its share of clips, and the 786-797 Hz level.
# usage: psu-tone.py <mic.csv> <HH:MM>-<HH:MM>[@YYYY-MM-DD] [minutes per row, default 1]
import csv, datetime, statistics as st, sys

rows = list(csv.DictReader(open(sys.argv[1])))
rng, day = (sys.argv[2].split('@') + [None])[:2]
day = day or datetime.datetime.fromtimestamp(int(rows[0]['epoch'])).strftime('%Y-%m-%d')
a, b = rng.split('-')
t0 = datetime.datetime.strptime(f'{day} {a}', '%Y-%m-%d %H:%M').timestamp()
t1 = datetime.datetime.strptime(f'{day} {b}', '%Y-%m-%d %H:%M').timestamp()
step = 60 * float(sys.argv[3]) if len(sys.argv) > 3 else 60
TCOL = 'tones(Hz:prominence dB:level dBFS)'
def tones(s):
    out = []
    for t in (s or '').split(';'):
        p = t.split(':')
        if len(p) == 3:
            try:
                out.append((float(p[0]), float(p[2])))
            except ValueError:
                pass
    return out
print(f'{"time":>5} {"n":>3} {"dB(A)":>7} {"o500":>6} {"o1k":>6}   {"PSU Hz":>7} {"lvl":>5} {"share":>5}   {"791 lvl":>7}')
t = t0
while t < t1:
    sel = [r for r in rows if t <= int(r['epoch']) < t + step]
    if sel:
        best, fix = [], []
        for r in sel:
            tt = tones(r.get(TCOL))
            c = [x for x in tt if 400 <= x[0] <= 1000 and not 786 <= x[0] <= 797]
            if c:
                best.append(max(c, key=lambda x: x[1]))
            f = [x[1] for x in tt if 786 <= x[0] <= 797]
            if f:
                fix.append(max(f))
        med = lambda k: st.median(float(r[k]) for r in sel)
        psu = (f'{st.median(x[0] for x in best):7.0f} {st.median(x[1] for x in best):5.0f} {len(best) / len(sel):5.0%}'
               if best else f'{"-":>7} {"-":>5} {"0%":>5}')
        print(f'{datetime.datetime.fromtimestamp(t):%H:%M} {len(sel):3} {med("A"):7.2f} {med("o500"):6.1f} {med("o1000"):6.1f}'
              f'   {psu}   {(st.median(fix) if fix else float("nan")):7.1f}')
    t += step
