#!/usr/bin/env python3
# mic-window: median levels of morgana's mic log (mic-level-log.py CSV) over named time windows.
# usage: mic-window.py <csv> <date YYYY-MM-DD> <label>=<HH:MM:SS>-<HH:MM:SS> [...]
# Prints per window: clips, dB(A) median and p10-p90, unweighted dB, the 500 Hz / 1 kHz octaves, and the
# strongest tone between 400 and 1000 Hz (median frequency and level over the clips that have one).
import statistics as st
import sys
import time

csv, day, wins = sys.argv[1], sys.argv[2], sys.argv[3:]
rows = []
for line in open(csv):
    p = line.strip().split(',')
    if not p or not p[0].isdigit():
        continue
    try:
        t, a, z = int(p[0]), float(p[1]), float(p[2])
        octs = [float(x) for x in p[3:11]]
    except (ValueError, IndexError):
        continue
    tones = []
    if len(p) > 11 and p[11]:
        for tok in p[11].split(';'):
            try:
                f, prom, lev = tok.split(':')
                tones.append((float(f), float(lev)))
            except ValueError:
                pass
    rows.append((t, a, z, octs, tones))


def ep(hms):
    return int(time.mktime(time.strptime(f'{day} {hms}', '%Y-%m-%d %H:%M:%S')))


def q(v, f):
    v = sorted(v)
    return v[min(len(v) - 1, int(f * len(v)))]


print(f'{"window":<14} {"clips":>5} {"dB(A)":>7} {"p10..p90":>14} {"dB":>7} {"500Hz":>6} {"1kHz":>6}  tone 400-1000 Hz')
for w in wins:
    lab, span = w.split('=')
    a, b = span.split('-')
    sel = [r for r in rows if ep(a) <= r[0] < ep(b)]
    if not sel:
        print(f'{lab:<14} {0:>5}')
        continue
    da = [r[1] for r in sel]
    tone = [max((t for t in r[4] if 400 <= t[0] <= 1000), key=lambda t: t[1]) for r in sel
            if any(400 <= t[0] <= 1000 for t in r[4])]
    ts = f'{st.median(t[0] for t in tone):.0f} Hz, {st.median(t[1] for t in tone):.0f} dBFS ({len(tone)}/{len(sel)})' if tone else '-'
    print(f'{lab:<14} {len(sel):>5} {st.median(da):>7.2f} {q(da, .1):>6.2f}..{q(da, .9):>6.2f} '
          f'{st.median(r[2] for r in sel):>7.2f} {st.median(r[3][3] for r in sel):>6.1f} {st.median(r[3][4] for r in sel):>6.1f}  {ts}')
