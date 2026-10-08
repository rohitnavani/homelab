#!/usr/bin/env python3
# exp4_spans (2026-10-07): turn shelf-exp4's phase markers into --span arguments for analyze_mic_phases.py, e.g.
#   python3 -I analyze_mic_phases.py mic.csv $(python3 -I exp4_spans.py shelf-exp4.csv) --ref EPOCH0-EPOCH1 --skip 900
# Each span starts at the phase marker and ends at the next marker (or the last row). Use a long --skip: the shelf
# fans change at once, but the point is the steady sound of each level.
import sys, time
marks = []
for path in sys.argv[1:]:
    for l in open(path):
        if l.startswith('# ') and (' phase ' in l or ' done' in l or ' ended early' in l):
            p = l.split()
            t = int(time.mktime(time.strptime(p[1] + ' ' + p[2], '%Y-%m-%d %H:%M:%S')))
            name = p[4].rstrip(':') if ' phase ' in l else None
            marks.append((t, name))
marks.sort()
out = []
for i, (t, name) in enumerate(marks):
    if name:
        end = marks[i + 1][0] if i + 1 < len(marks) else int(time.time())
        out.append(f'--span {name}={t}-{end}')
print(' '.join(out))
