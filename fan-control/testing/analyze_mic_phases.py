#!/usr/bin/env python3
# analyze_mic_phases (2026-10-07): sound level per test phase from morgana's mic log (mic-level-log.py rows: epoch,
# A, Z, octave bands 63..8000 Hz, tones). Phases come from a test CSV with 'epoch' and 'phase' columns (mementos-quiet,
# ryuji-quiet) or from --span label=EPOCH0-EPOCH1 arguments. Per phase: median dB(A), the 1-2 kHz bands (fan noise),
# and the change against the reference window (default: the 30 min before the first phase), skipping the first
# SKIP s of each phase (fans take ~1 min to settle). Levels are dBFS for this mic and gain: only differences mean much.
# usage: analyze_mic_phases.py <mic.csv> [test.csv] [--ref EPOCH0-EPOCH1] [--span label=EPOCH0-EPOCH1 ...] [--skip S]
import csv, statistics as st, sys

args = sys.argv[1:]
mic_path = args.pop(0)
test_path = args.pop(0) if args and not args[0].startswith('--') else None
ref, spans, skip = None, [], 60
while args:
    a = args.pop(0)
    if a == '--ref':
        x, y = args.pop(0).split('-'); ref = (int(x), int(y))
    elif a == '--span':
        lab, rng = args.pop(0).split('='); x, y = rng.split('-'); spans.append((lab, int(x), int(y)))
    elif a == '--skip':
        skip = int(args.pop(0))

mic = []
for r in csv.reader(open(mic_path)):
    if r and r[0][:1].isdigit():
        try:
            mic.append((int(r[0]), float(r[1]), float(r[7]), float(r[8])))   # epoch, A, o1000, o2000
        except (ValueError, IndexError):
            pass

if test_path:   # consecutive rows with the same phase label = one span
    cur = None
    for l in open(test_path):
        if l.startswith('#') or l.startswith('epoch'):
            continue
        p = l.strip().split(',')
        try:
            t, lab = int(p[0]), p[2]
        except (ValueError, IndexError):
            continue
        if cur and cur[0] == lab:
            cur[2] = t
        else:
            if cur:
                spans.append(tuple(cur))
            cur = [lab, t - 20, t]       # rows are logged at the end of each 20-30 s sample
    if cur:
        spans.append(tuple(cur))
spans.sort(key=lambda s: s[1])
if ref is None and spans:
    ref = (spans[0][1] - 1800, spans[0][1])


def stats(a, b):
    v = [m for m in mic if a <= m[0] < b]
    if not v:
        return None
    return len(v), st.median(x[1] for x in v), st.median(x[2] for x in v), st.median(x[3] for x in v)


r = stats(*ref) if ref else None
if r:
    print(f'reference {ref[0]}-{ref[1]}: n={r[0]} A {r[1]:.2f}  1k {r[2]:.1f}  2k {r[3]:.1f}')
print(f'{"phase":<16}{"start":>11}{"min":>6}{"n":>5}{"dB(A)":>8}{"dA":>7}{"d1k":>7}{"d2k":>7}')
for lab, a, b in spans:
    s = stats(a + skip, b)
    if not s:
        continue
    d = (s[1] - r[1], s[2] - r[2], s[3] - r[3]) if r else (0, 0, 0)
    import time
    print(f'{lab:<16}{time.strftime("%H:%M:%S", time.localtime(a)):>11}{(b - a) / 60:>6.1f}{s[0]:>5}{s[1]:>8.2f}'
          f'{d[0]:>+7.2f}{d[1]:>+7.1f}{d[2]:>+7.1f}')
