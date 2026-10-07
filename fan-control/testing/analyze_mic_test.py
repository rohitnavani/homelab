#!/usr/bin/env python3
# analyze_mic_test: can the mic hear known changes? Splits a mic-level-log CSV into states from the event logs of the
# shelf holds (shelf-decay-<label>.log) and the R720 steps (mic-r720.log), drops the settling time after each change,
# and compares each step with the baselines on either side (A-weighted level, octave bands, tones).
# usage: analyze_mic_test.py <levels.csv> <shelf-decay log> [<shelf-decay log> ...] <mic-r720.log>
import math, re, statistics as st, sys, time
from collections import defaultdict

lv, shelf_logs, r720_log = sys.argv[1], sys.argv[2:-1], sys.argv[-1]
rows = []
lines = open(lv).read().splitlines()
hdr = lines[0].split(',')
for l in lines[1:]:
    p = l.split(',')
    rows.append({'t': int(p[0]), 'A': float(p[1]), 'Z': float(p[2]),
                 'oct': [float(v) for v in p[3:11]], 'tones': p[11] if len(p) > 11 else ''})
OCT = [h[1:] for h in hdr[3:11]]
CLIP = 10

def ep(s):
    return time.mktime(time.strptime(s, '%Y-%m-%d %H:%M:%S'))

events = []   # (epoch, kind, value)
for f in shelf_logs:
    for l in open(f):
        m = re.match(r'(\S+ \S+) (\S+): sent _shutup (\d+) once', l)
        if m:
            events.append((ep(m.group(1)), 'shelf', int(m.group(3))))
        m = re.match(r'(\S+ \S+) (\S+): done', l)
        if m:
            events.append((ep(m.group(1)), 'shelf', 17))       # md1200-fan resumes its own level
for l in open(r720_log):
    p = l.split()
    if len(p) >= 4 and p[2] == 'fans':
        events.append((int(p[0]), 'r720', int(p[3].rstrip('%'))))
    elif len(p) >= 3 and p[2] == 'restore:':
        events.append((int(p[0]), 'r720', 'wd'))
events.sort()
SETTLE = {'shelf': 25, 'r720': 15}
shelf, r720 = 17, 'wd'
bounds = [(rows[0]['t'], f'shelf {shelf}% / R720 {r720}', 0)]
for t, k, v in events:
    if k == 'shelf':
        shelf = v
    else:
        r720 = v
    bounds.append((t, f'shelf {shelf}% / R720 {r720 if r720 == "wd" else str(r720) + "%"}', SETTLE[k]))
end = rows[-1]['t'] + CLIP + 1
states = []
for i, (t, name, settle) in enumerate(bounds):
    t2 = bounds[i + 1][0] if i + 1 < len(bounds) else end
    clips = [r for r in rows if r['t'] >= t + settle and r['t'] + CLIP <= t2]
    states.append({'name': name, 'from': t, 'to': t2, 'clips': clips})

def keep(clips):
    # drop clips hit by a passing sound: more than 3 MADs (at least 1 dB) from the state's median A level
    if len(clips) < 3:
        return clips
    m = st.median(r['A'] for r in clips)
    mad = st.median(abs(r['A'] - m) for r in clips) * 1.4826
    return [r for r in clips if abs(r['A'] - m) <= max(3 * mad, 1.0)]

for s in states:
    s['all'], s['clips'] = s['clips'], keep(s['clips'])

def hi(r):   # the 1 kHz + 2 kHz octave bands together: where the rack fans show and the low-frequency room noise does not
    return 10 * math.log10(10 ** (r['oct'][4] / 10) + 10 ** (r['oct'][5] / 10))

def summ(s, key=lambda r: r['A']):
    a = [key(r) for r in s['clips']]
    return (st.mean(a) if a else float('nan'), st.stdev(a) if len(a) > 1 else 0.0, len(a))

print(f'{"state":<26} {"start":>8} {"n":>2} {"out":>3} {"A dBFS":>7} {"sd":>4} {"1-2k":>6}   ' + ' '.join(f'{o:>6}' for o in OCT))
for s in states:
    m, sd, n = summ(s)
    h = summ(s, hi)[0]
    octs = [st.mean(r['oct'][j] for r in s['clips']) for j in range(8)] if s['clips'] else [float('nan')] * 8
    print(f'{s["name"]:<26} {time.strftime("%H:%M:%S", time.localtime(s["from"])):>8} {n:>2} {len(s["all"]) - n:>3} {m:7.2f} {sd:4.2f} {h:6.1f}   '
          + ' '.join(f'{o:6.1f}' for o in octs))

def tones(s):
    c = defaultdict(list)
    for r in s['clips']:
        for t in filter(None, r['tones'].split(';')):
            f, p, lev = t.split(':')
            c[round(float(f) / 5) * 5].append(float(p))
    n = max(1, len(s['clips']))
    return sorted(((f, len(v), st.mean(v)) for f, v in c.items() if len(v) >= max(2, n // 2)), key=lambda x: x[0])

print('\nsteady tones per state (Hz, prominence dB; in at least half the clips):')
for s in states:
    print(f'  {s["name"]:<26} ' + '  '.join(f'{f}:{p:.0f}' for f, k, p in tones(s)))

print('\nsteps vs the baselines on either side (A-weighted; t = difference / its standard error):')
for i, s in enumerate(states):
    if i == 0 or i + 1 >= len(states) or not s['clips']:
        continue
    a, b = states[i - 1], states[i + 1]
    if not a['clips'] or not b['clips'] or a['name'] != b['name']:   # only A/B/A steps
        continue
    base = a['clips'] + b['clips']
    ma, sa, na = summ(s)
    mb = st.mean(r['A'] for r in base); sb = st.stdev(r['A'] for r in base); nb = len(base)
    se = math.sqrt(sa ** 2 / max(na, 1) + sb ** 2 / max(nb, 1)) or 1e-9
    doct = [st.mean(r['oct'][j] for r in s['clips']) - st.mean(r['oct'][j] for r in base) for j in range(8)]
    hs, hb = summ(s, hi)[0], st.mean(hi(r) for r in base)
    hb1, hb2 = st.mean(hi(r) for r in a['clips']), st.mean(hi(r) for r in b['clips'])
    print(f'  {s["name"]:<26} {ma - mb:+5.2f} dB(A)  t={(ma - mb) / se:5.1f}   1-2k {hs - hb:+5.2f} dB '
          f'(vs before {hs - hb1:+.2f}, vs after {hs - hb2:+.2f})   bands '
          + ' '.join(f'{o}:{d:+.1f}' for o, d in zip(OCT, doct)))
