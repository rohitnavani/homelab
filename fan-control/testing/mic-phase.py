#!/usr/bin/env python3
# mic-phase (2026-10-20): mirror-mic levels per test phase, from miclevels.py's CSV (10 s clips, Sonos-active frames
# already dropped). For each phase it takes the clips inside [start + SKIP, end] (SKIP lets fans settle), and prints the
# median background dB(A) (dba_bg = the quieter half of each clip), its p20, the octave bands, and the steady tones:
# for each 10 Hz bin the share of clips with a tone there, listing the ones present in at least 30% of clips.
# A/B/A rows: each phase's dB(A) is also given against the mean of its anchor phases (labels matching --anchor).
# dBFS for this mic and gain: only differences mean anything.
# usage: mic-phase.py MIC.csv PHASES.csv [--skip S] [--anchor REGEX] [--band 600-1000]
#   PHASES.csv: start_epoch,end_epoch,label  (one phase per line, header optional)
import csv, re, statistics as st, sys

args = sys.argv[1:]
skip = float(args[args.index('--skip') + 1]) if '--skip' in args else 30
anchor = args[args.index('--anchor') + 1] if '--anchor' in args else None
band = tuple(map(float, args[args.index('--band') + 1].split('-'))) if '--band' in args else (600, 1000)
mic, phases = args[0], args[1]

rows = []
with open(mic) as f:
    for r in csv.DictReader(f):
        try:
            if r['dba_bg'] == '':
                continue
            rows.append(r)
        except KeyError:
            continue
OCT = [k for k in rows[0].keys() if re.fullmatch(r'o\d+', k)] if rows else []
TK = [k for k in rows[0].keys() if k.startswith('tones')][0] if rows else 'tones'

ph = []
with open(phases) as f:
    for line in f:
        p = line.strip().split(',')
        if len(p) < 3 or not p[0].replace('.', '').isdigit():
            continue
        ph.append((float(p[0]), float(p[1]), p[2]))


def tones(sel):
    cnt = {}
    for r in sel:
        seen = set()
        for t in (r[TK] or '').split(';'):
            if not t:
                continue
            hz, prom, lvl = t.split(':')
            b = int(round(float(hz) / 10) * 10)
            if b not in seen:
                seen.add(b)
                cnt.setdefault(b, []).append(float(lvl))
    out = []
    for b, lv in sorted(cnt.items()):
        share = len(lv) / len(sel)
        if share >= 0.3:
            out.append((b, share, st.median(lv)))
    return out


res = []
for a, b, label in ph:
    sel = [r for r in rows if a + skip <= float(r['epoch']) <= b]
    if not sel:
        res.append((label, 0, None, None, [], [], a, b))
        continue
    bg = [float(r['dba_bg']) for r in sel]
    p20 = [float(r['dba_p20']) for r in sel]
    octs = [st.median(float(r[o]) for r in sel if r[o] != '') for o in OCT]
    res.append((label, len(sel), st.median(bg), st.median(p20), octs, tones(sel), a, b))

anc = [r[2] for r in res if anchor and re.search(anchor, r[0]) and r[2] is not None]
ref = st.mean(anc) if anc else None
print(f'# mic {mic}; skip {skip:.0f} s; anchor {anchor} = {ref:.2f} dB(A)' if ref is not None else f'# mic {mic}; skip {skip:.0f} s')
print('label,clips,dba_bg,dba_p20,vs_anchor,' + ','.join(OCT) + f',tones in {band[0]:.0f}-{band[1]:.0f} Hz (Hz share level),all steady tones')
for label, n, bg, p20, octs, tn, a, b in res:
    if bg is None:
        print(f'{label},0')
        continue
    inb = ' '.join(f'{hz}:{s:.0%}:{lv:.0f}' for hz, s, lv in tn if band[0] <= hz <= band[1])
    allt = ' '.join(f'{hz}:{s:.0%}' for hz, s, lv in tn)
    d = f'{bg - ref:+.2f}' if ref is not None else ''
    print(f'{label},{n},{bg:.2f},{p20:.2f},{d},' + ','.join(f'{o:.1f}' for o in octs) + f',{inb},{allt}')
