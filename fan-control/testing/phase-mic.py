#!/usr/bin/env python3
# phase-mic (2026-10-10): per-phase mic and sensor summary for a ryuji-profile / ryuji-floor run. Phase boundaries come
# from the run CSV's "# <epoch> ... phase <name>:" notes. For each phase, over its last LAST minutes (default 15; the
# whole phase if shorter): ryuji sensor medians, mic dB(A) median over all clips and over "clean" clips (4 kHz octave
# at or below CLEAN dBFS: household sounds such as voices or dishes lift 2-8 kHz, ryuji's fans barely do), the
# strongest tone in 400-1000 Hz outside the room's fixed 788-796 Hz tone (median Hz / dBFS), and the share of clips
# with a tone in the 680-830 Hz ringing band (fixed tone excluded).
# usage: phase-mic.py <run.csv> <mic.csv> [LAST minutes] [CLEAN dBFS]
import csv, re, statistics as st, sys

run, mic = sys.argv[1], sys.argv[2]
LAST = float(sys.argv[3]) if len(sys.argv) > 3 else 15
CLEAN = float(sys.argv[4]) if len(sys.argv) > 4 else -82
cols = ['epoch', 'time_utc', 'phase', 'phase_min', 'offset', 'load', 'cpu0', 'cpu1', 'sio1', 'sio2', 'pch', 'vr', 'dimm',
        'hdd', 'cpu_fan0', 'cpu_fan1', 'sys_fan', 'fan_min', 'dcmi_w', 'pkg0_w', 'pkg1_w', 'room']
phases, data, end = [], [], None
for line in open(run):
    if line.startswith('#'):
        m = re.match(r'# (\d+) .*?phase (\S+): offset (\S+), (\d+) busy', line)
        if m:
            phases.append([m.group(2), int(m.group(1)), None, m.group(3), int(m.group(4))])
        if re.search(r'guard (started|takes over)|done|restore', line):
            end = int(line.split()[1])
    elif line[0].isdigit():
        data.append(dict(zip(cols, line.strip().split(','))))
for i, p in enumerate(phases):
    p[2] = phases[i + 1][1] if i + 1 < len(phases) else (end or int(data[-1]['epoch']) + 40)
mrows = list(csv.DictReader(open(mic)))
TCOL = 'tones(Hz:prominence dB:level dBFS)'
def tones(s):
    out = []
    for t in (s or '').split(';'):
        q = t.split(':')
        if len(q) == 3:
            try:
                out.append((float(q[0]), float(q[2])))
            except ValueError:
                pass
    return out
def med(v):
    v = [x for x in v if x is not None]
    return st.median(v) if v else float('nan')
hdr = (f'{"phase":<10}{"off":>5}{"thr":>4}{"min":>5} {"CPU fan":>8}{"sys fan":>8}{"SIO1":>6}{"CPU":>5}{"W":>5}'
       f'{"n":>5}{"dB(A)":>8}{"clean":>8}{"nclean":>7}{"tone Hz":>9}{"dBFS":>6}{"ring%":>7}')
print(f'(last {LAST:g} min of each phase; clean = 4 kHz octave <= {CLEAN:g} dBFS)')
print(hdr)
for name, a, b, off, thr in phases:
    s = max(a, b - LAST * 60)
    d = [r for r in data if s <= int(r['epoch']) < b]
    m = [r for r in mrows if s <= int(r['epoch']) < b]
    if not m:
        continue
    clean = [r for r in m if float(r['o4000']) <= CLEAN]
    best, ring = [], 0
    for r in m:
        tt = [x for x in tones(r.get(TCOL)) if not 788 <= x[0] <= 796]
        c = [x for x in tt if 400 <= x[0] <= 1000]
        if c:
            best.append(max(c, key=lambda x: x[1]))
        if any(680 <= x[0] <= 830 for x in tt):
            ring += 1
    f = lambda k: med([float(r[k]) for r in d if r.get(k) not in (None, '', 'None')])
    cpu = med([max(float(r['cpu0']), float(r['cpu1'])) for r in d if r['cpu0'] and r['cpu1']])
    fan = med([(float(r['cpu_fan0']) + float(r['cpu_fan1'])) / 2 for r in d if r['cpu_fan0'] and r['cpu_fan1']])
    print(f'{name:<10}{off:>5}{thr:>4}{(b - s) / 60:5.0f} {fan:8.0f}{f("sys_fan"):8.0f}{f("sio1"):6.0f}{cpu:5.0f}{f("dcmi_w"):5.0f}'
          f'{len(m):5}{med([float(r["A"]) for r in m]):8.2f}{med([float(r["A"]) for r in clean]):8.2f}{len(clean):7}'
          f'{med([x[0] for x in best]):9.0f}{med([x[1] for x in best]):6.0f}{ring / len(m):7.0%}')
