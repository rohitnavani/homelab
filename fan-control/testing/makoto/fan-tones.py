#!/usr/bin/env python3
# fan-tones: per fanstep phase, a long-averaged mic spectrum (0.5 Hz bins, Sonos-active frames dropped) from the
# mirror-voice AEC dump, and the level and prominence at k x rev/s of each fan (k = 2..12, blade-pass candidates).
# Dump offsets come from mic.csv (miclevels.py writes the dump size with every 10 s row). Levels only, no audio kept.
# usage: fan-tones.py STEPS.csv [skip s at phase start, default 60]
import csv, statistics as st, sys
import numpy as np

D = '/home/rohit/lab-thermal-2026-10-19/data/'
DUMP = '/home/rohit/.claude/jobs/da0efdf0/tmp/live/aec.f32'
FB, FS, NFFT = 1920, 16000, 32768
steps = list(csv.DictReader(open(sys.argv[1])))
SKIP = float(sys.argv[2]) if len(sys.argv) > 2 else 60
mic = [(int(r['epoch']), int(r['offset'])) for r in csv.DictReader(open(D + 'mic.csv')) if r.get('offset')]
ms = [r for r in csv.DictReader(open(D + 'msample.csv')) if r['fan1']]


def offset_at(t):
    """dump byte offset at epoch t, interpolated between logged (epoch, size) pairs"""
    for (t0, o0), (t1, o1) in zip(mic, mic[1:]):
        if t0 <= t <= t1:
            return int((o0 + (o1 - o0) * (t - t0) / max(1, t1 - t0)) // FB * FB)
    if mic and 0 < t - mic[-1][0] <= 60:             # just past the last row: real time from there
        return int((mic[-1][1] + (t - mic[-1][0]) * FS * FB / 160) // FB * FB)
    return None


phases = []
for r in steps:
    if not phases or phases[-1][0] != r['label']:
        phases.append([r['label'], int(r['epoch']), int(r['epoch'])])
    phases[-1][2] = int(r['epoch'])
F = np.fft.rfftfreq(NFFT, 1 / FS)
WIN = np.hanning(NFFT)
for lab, t0, t1 in phases:
    a, b = offset_at(t0 + SKIP), offset_at(t1)
    if a is None or b is None or b - a < FB * 100 * 30:
        continue
    with open(DUMP, 'rb') as f:
        f.seek(a)
        x = np.frombuffer(f.read(b - a), np.float32).reshape(-1, 3, 160)
    quiet = np.abs(x[:, 1, :]).max(axis=1) < 1e-4
    keep = quiet & (np.convolve(quiet, np.ones(200), 'same') >= 199.5)    # 1 s clear of any Sonos frame
    mic_s = x[keep, 0, :].ravel()
    del x
    segs = [mic_s[i:i + NFFT] for i in range(0, len(mic_s) - NFFT, NFFT // 2)]
    # drop the loudest quarter of segments (speech, bangs), average the rest
    pw = np.array([np.abs(np.fft.rfft((s - s.mean()) * WIN)) ** 2 for s in segs])
    lev = pw.sum(axis=1)
    pw = pw[lev <= np.percentile(lev, 75)].mean(axis=0) / (FS * (WIN ** 2).sum())
    pdb = 10 * np.log10(pw + 1e-30)
    rows = [r for r in ms if t0 + SKIP <= int(r['epoch']) <= t1]
    rpm1, rpm4 = st.median(float(r['fan1']) for r in rows), st.median(float(r['fan4']) for r in rows)
    out = []
    for name, rpm in (('FAN1', rpm1), ('FAN4', rpm4)):
        hits = []
        for k in range(2, 13):
            f = k * rpm / 60
            if f > 4000:
                break
            i = int(round(f / F[1]))
            w = int(round(0.04 * f / F[1])) + 2           # +-4% (the BMC reads rpm in 100s)
            pk = i - w + int(np.argmax(pdb[i - w:i + w + 1]))
            bg = np.median(pdb[max(0, pk - 200):pk + 200])
            if pdb[pk] - bg >= 6:
                hits.append(f'{k}x {F[pk]:.0f}Hz +{pdb[pk] - bg:.0f}dB')
        out.append(f"{name} {rpm:.0f}rpm: {', '.join(hits) or '-'}")
    print(f"{lab:12s} {(t1 - t0 - SKIP) / 60:4.1f} min  " + ' | '.join(out))
