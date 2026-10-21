#!/usr/bin/env python3
# aec-spectra (2026-10-20): compact magnitude spectra of the mirror mic for the test windows only, from mirror-voice's raw
# AEC dump (float32 (mic, reference, output) x 160 per 10 ms frame, 16 kHz; channel 0 = the raw mic). One row per
# data/mic.csv clip in [START, END): the 10 s before that row's offset (the dump's size when miclevels read the clip),
# Welch power (1 s Hann segments, half overlap) in dB; 0-2 kHz kept at 1 Hz, 2-8 kHz averaged into 10 Hz bins; float16.
# Clips mic.csv left blank (our Sonos playing) are skipped. No audio is kept: 10 s averaged magnitudes cannot be turned
# back into speech, and mirror-voice deletes the dump afterwards.
# usage: aec-spectra.py DUMP MIC.csv OUT.npz START_EPOCH END_EPOCH
import csv
import sys

import numpy as np

dump, mic, out, a, b = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4]), float(sys.argv[5])
FS, FRAME, CLIP = 16000, 160, 1000          # 1000 frames = 10 s
FB = 3 * FRAME * 4                          # bytes per frame
win = np.hanning(FS)
hop = FS // 2
hi_edges = np.arange(2000, 8000, 10)        # 2000-7990 Hz, 10 Hz wide
ep, rows = [], []
with open(dump, 'rb') as f:
    for r in csv.DictReader(open(mic)):
        t = float(r['epoch'])
        if not (a <= t < b) or r.get('dba_bg', '') == '' or not r.get('offset'):
            continue
        end = int(float(r['offset']))
        start = end - CLIP * FB
        if start < 0:
            continue
        f.seek(start)
        raw = f.read(CLIP * FB)
        if len(raw) < CLIP * FB:
            continue
        x = np.frombuffer(raw, np.float32).reshape(-1, 3, FRAME)[:, 0, :].ravel().astype(np.float64)
        p = np.mean([np.abs(np.fft.rfft(x[i:i + FS] * win)) ** 2 for i in range(0, len(x) - FS + 1, hop)], axis=0)
        p /= (win ** 2).sum()
        hi = [p[e:e + 10].mean() for e in hi_edges]
        rows.append(10 * np.log10(np.concatenate([p[:2001], hi]) + 1e-20))
        ep.append(t)
freqs = np.concatenate([np.arange(0, 2001), hi_edges + 5]).astype(np.float32)
np.savez_compressed(out, epoch=np.array(ep), freq_hz=freqs, db=np.array(rows, np.float16))
print(f'{len(ep)} clips, {len(freqs)} bins -> {out}')
