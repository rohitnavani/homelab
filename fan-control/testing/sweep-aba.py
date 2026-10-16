#!/usr/bin/env python3
# sweep-aba (2026-10-15): A/B/A noise table for noise-sweep.py / r720-notch-sweep.py runs. Segments are runs of rows with
# the same phase label (the reference holds repeat one label). Each step is compared with the mean of the reference
# segments right before and after it (dB(A) medians, first SKIP s of every segment dropped: fans settle in ~20-30 s).
# usage: sweep-aba.py <mic.csv> <sweep.csv> [--skip S]
import statistics as st, sys

args = sys.argv[1:]
skip = 30
if '--skip' in args:
    i = args.index('--skip'); skip = float(args[i + 1]); args = args[:i] + args[i + 2:]
mic_p, sw_p = args
mic = []
mh = None
for line in open(mic_p):
    f = line.rstrip('\n').split(',')
    if mh is None:
        mh = f; continue
    try:
        r = dict(zip(mh, f)); r['t'] = float(r['epoch']); r['A'] = float(r['A'])
        r['tones'] = next((v for k, v in r.items() if k.startswith('tones')), '')
        mic.append(r)
    except (ValueError, KeyError):
        pass
segs, sh = [], None
for line in open(sw_p):
    if line.startswith('#'):
        continue
    f = line.rstrip('\n').split(',')
    if sh is None:
        sh = f; continue
    r = dict(zip(sh, f))
    try:
        t = int(r['epoch'])
    except (ValueError, KeyError):
        continue
    if segs and segs[-1]['phase'] == r['phase']:
        segs[-1]['t1'] = t
    else:
        segs.append({'phase': r['phase'], 'box': r.get('box'), 'pct': r.get('pct'), 't0': t, 't1': t,
                     'rpm': r.get('r720_rpm') if r.get('box') == 'r720' else r.get('shelf_rpm')})
    segs[-1]['rpm'] = r.get('r720_rpm') if r.get('box') == 'r720' else r.get('shelf_rpm')


def level(s):
    v = [m['A'] for m in mic if s['t0'] + skip <= m['t'] <= s['t1'] + 10]
    return (st.median(v), len(v)) if v else (None, 0)


def tone(s):
    best = []
    for m in mic:
        if not (s['t0'] + skip <= m['t'] <= s['t1'] + 10):
            continue
        b = None
        for tk in (m['tones'] or '').split(';'):
            try:
                fq, p, l = tk.split(':'); fq, l = float(fq), float(l)
            except ValueError:
                continue
            if 300 <= fq <= 2000 and (b is None or l > b[1]):
                b = (fq, l)
        if b:
            best.append(b)
    return f'{st.median(x[0] for x in best):.0f} Hz, {st.median(x[1] for x in best):.0f}' if best else ''


print('| step | box | % | rpm | dB(A) | refs before / after | vs refs | tone 300-2000 Hz |')
print('|---|---|---|---|---|---|---|---|')
for i, s in enumerate(segs):
    if s['phase'].endswith('_ref'):
        continue
    a = next((x for x in reversed(segs[:i]) if x['phase'].endswith('_ref') and x['box'] == s['box']), None)
    b = next((x for x in segs[i + 1:] if x['phase'].endswith('_ref') and x['box'] == s['box']), None)
    lv, n = level(s)
    la = level(a)[0] if a else None
    lb = level(b)[0] if b else None
    refs = [x for x in (la, lb) if x is not None]
    ref = sum(refs) / len(refs) if refs else None
    d = f'{lv - ref:+.2f}' if lv is not None and ref is not None else ''
    print(f"| {s['phase']} | {s['box']} | {s['pct']} | {s['rpm']} | {'' if lv is None else f'{lv:.2f}'} | "
          f"{'' if la is None else f'{la:.2f}'} / {'' if lb is None else f'{lb:.2f}'} | {d} | {tone(s)} |")
