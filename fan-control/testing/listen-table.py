#!/usr/bin/env python3
# listen-table (2026-10-15): the Thursday 20:00 listening test's slots with the key and what the mic (at the rack) heard
# in each: dB(A) median after the fans settle (first SKIP s dropped), the 500 Hz and 1 kHz octaves, the strongest tone
# between 300 and 2,000 Hz. Rohit's notes (0 / 1 / 2 and A / T per slot) are joined from --notes "A1=0A,A2=1T,...".
# Block 2 (ryuji 11 workers, 20:17-20:31) is shown per minute.
# usage: listen-table.py <mic.csv> [--notes "A1=..,B1=.."] [--skip S] [--day 2026-10-15] [--start 21:25:00]
import statistics as st, sys, time

args = sys.argv[1:]
def opt(name, default=None):
    global args
    if name in args:
        i = args.index(name); v = args[i + 1]; args = args[:i] + args[i + 2:]; return v
    return default
notes = dict(x.split('=', 1) for x in (opt('--notes', '') or '').split(',') if '=' in x)
skip, day, start = float(opt('--skip', 20)), opt('--day', '2026-10-15'), opt('--start', '20:00:00')   # 10-15: ran at 21:25:00
SLOTS = [('A1', '20:00:00', 20), ('A2', '20:01:30', 10), ('A3', '20:03:00', 30), ('A4', '20:04:30', 15),
         ('A5', '20:06:00', 25), ('walk', '20:07:30', 10), ('B1', '20:08:30', 30), ('B2', '20:10:00', 15),
         ('B3', '20:11:30', 10), ('B4', '20:13:00', 25), ('B5', '20:14:30', 20), ('pause', '20:16:00', None),
         ('end', '20:17:00', None)]
_ep = lambda hms: time.mktime(time.strptime(f'{day} {hms}', '%Y-%m-%d %H:%M:%S'))
SHIFT = _ep(start) - _ep('20:00:00')
ep = lambda hms: _ep(hms) + SHIFT   # slot times are written for 20:00; --start moves the whole timetable
mic, mh = [], None
for line in open(args[0]):
    f = line.rstrip('\n').split(',')
    if mh is None:
        mh = f; continue
    try:
        m = dict(zip(mh, f)); m['t'] = float(m['epoch']); m['A'] = float(m['A'])
        m['tones'] = next((v for k, v in m.items() if k.startswith('tones')), '')
        mic.append(m)
    except (ValueError, KeyError):
        pass
def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
def med(xs):
    xs = [x for x in xs if x is not None]
    return st.median(xs) if xs else None
def tone(ms):
    best = []
    for m in ms:
        b = None
        for t in (m.get('tones') or '').split(';'):
            try:
                fq, p, l = t.split(':'); fq, l = float(fq), float(l)
            except ValueError:
                continue
            if 300 <= fq <= 2000 and (b is None or l > b[1]):
                b = (fq, l)
        if b:
            best.append(b)
    return f'{med([x[0] for x in best]):.0f} Hz, {med([x[1] for x in best]):.0f}' if best else ''
def row(label, t0, t1, extra):
    ms = [m for m in mic if t0 <= m['t'] < t1]
    a, o5, o1 = med([m['A'] for m in ms]), med([num(m.get('o500')) for m in ms]), med([num(m.get('o1000')) for m in ms])
    f = lambda v, d: '' if v is None else f'{v:.{d}f}'
    print(f"| {label} | {extra} | {len(ms)} | {f(a, 2)} | {f(o5, 1)} | {f(o1, 1)} | {tone(ms)} | {notes.get(label, '')} |")
print('| slot | R720 % | clips | dB(A) at the rack | 500 Hz | 1 kHz | tone 300-2000 Hz | Rohit |')
print('|---|---|---|---|---|---|---|---|')
for (lab, hms, pct), (_, nxt, _) in zip(SLOTS, SLOTS[1:]):
    row(lab, ep(hms) + skip, ep(nxt), '' if pct is None else pct)
print()
print('| block 2 minute | ryuji | clips | dB(A) at the rack | 500 Hz | 1 kHz | tone 300-2000 Hz | Rohit |')
print('|---|---|---|---|---|---|---|---|')
for k in range(16):
    t0 = ep('20:17:00') + 60 * k
    row(time.strftime('%H:%M', time.localtime(t0)), t0, t0 + 60, '11 workers' if k < 14 else 'idle')
