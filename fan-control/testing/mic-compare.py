#!/usr/bin/env python3
# mic-compare (2026-10-10): compare mic-level-log windows (dB(A), unweighted, octave bands, tones). Each window is
# split by the AC's state, read from the 63 Hz octave (the AC's hum lifts it 3-5 dB while it runs): clips above the
# window's 63 Hz midpoint count as "AC on". Tones: how often each frequency bin (10 Hz) shows up among a clip's listed
# tones, and its median level, so a source that stops (a fan) shows as a tone that disappears.
# usage: mic-compare.py <mic.csv> <label>=<HH:MM>-<HH:MM>[@YYYY-MM-DD] ...   (date defaults to the first row's date)
import collections, csv, datetime, statistics as st, sys

rows = list(csv.DictReader(open(sys.argv[1])))
day0 = datetime.datetime.fromtimestamp(int(rows[0]['epoch'])).strftime('%Y-%m-%d')
BANDS = ['A', 'Z', 'o63', 'o125', 'o250', 'o500', 'o1000', 'o2000', 'o4000']
def tones(s):
    out = []
    for t in (s or '').split(';'):
        p = t.split(':')
        if len(p) == 3:
            try:
                out.append((float(p[0]), float(p[1]), float(p[2])))
            except ValueError:
                pass
    return out
wins = []
for arg in sys.argv[2:]:
    label, rng = arg.split('=')
    day = day0
    if '@' in rng:
        rng, day = rng.split('@')
    a, b = rng.split('-')
    t0 = datetime.datetime.strptime(f'{day} {a}', '%Y-%m-%d %H:%M').timestamp()
    t1 = datetime.datetime.strptime(f'{day} {b}', '%Y-%m-%d %H:%M').timestamp()
    if t1 <= t0:
        t1 += 86400
    sel = [r for r in rows if t0 <= int(r['epoch']) < t1]
    wins.append((label, sel))
allo63 = [float(r['o63']) for _, sel in wins for r in sel]
mid = (min(allo63) + max(allo63)) / 2 if allo63 else 0
print(f'63 Hz split at {mid:.1f} (AC on above)')
print(f'{"window":<14}{"AC":>4}{"n":>5}' + ''.join(f'{b:>8}' for b in BANDS))
for label, sel in wins:
    for ac in ('all', 'off', 'on'):
        s = sel if ac == 'all' else [r for r in sel if (float(r['o63']) > mid) == (ac == 'on')]
        if len(s) < 6:
            continue
        print(f'{label:<14}{ac:>4}{len(s):>5}' + ''.join(f'{st.median(float(r[b]) for r in s):8.2f}' for b in BANDS))
print('\ntones present in at least 20% of clips in some window (share of clips / median level dBFS):')
bins = {}
for label, sel in wins:
    c, lv = collections.Counter(), collections.defaultdict(list)
    for r in sel:
        seen = set()
        for f, prom, lev in tones(r.get('tones(Hz:prominence dB:level dBFS)')):
            k = int(f // 10 * 10)
            if k not in seen:
                c[k] += 1; lv[k].append(lev); seen.add(k)
    bins[label] = (len(sel), c, lv)
keys = sorted({k for n, c, lv in bins.values() for k in c if n and c[k] / n >= 0.2})
print(f'{"Hz":>6}' + ''.join(f'{label:>22}' for label, _ in wins))
for k in keys:
    line = f'{k:>6}'
    for label, _ in wins:
        n, c, lv = bins[label]
        line += f'{(c[k] / n if n else 0):>14.0%} {(st.median(lv[k]) if lv[k] else float("nan")):6.1f}  '
    print(line)
