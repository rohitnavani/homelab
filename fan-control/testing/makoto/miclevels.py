#!/usr/bin/env python3
# miclevels: sound levels at the mirror's Pi mic (C-Media USB, gain max, AGC on), read from mirror-voice's AEC debug
# dump (float32 (mic, reference, output) x 160 per 10 ms frame, 16 kHz, appended live). Keeps only levels, never audio.
# Every CLIP s it takes the frames appended since the last read, drops any while the Sonos reference is active (plus
# 1 s after), splits the rest into 0.5 s blocks and writes: A-weighted level p20/median of the blocks, the level of the
# quietest half of the blocks (bg: speech and bangs fall out), unweighted bg, octave bands 63-4000 Hz (bg) and the
# strongest steady tones in the bg spectrum. dBFS for this mic and gain: only differences mean anything.
# offset = the dump's size in bytes when the clip was read (so a later analysis can find any window exactly).
# usage: miclevels.py DUMP OUT.csv [hours, default 12] [clip s, default 10]
import os, sys, time
import numpy as np

dump, out = sys.argv[1], sys.argv[2]
hours = float(sys.argv[3]) if len(sys.argv) > 3 else 12
CLIP = float(sys.argv[4]) if len(sys.argv) > 4 else 10
FS, FRAME, BLOCK = 16000, 160, 8000
FB = 3 * FRAME * 4                       # bytes per frame
OCT = (63, 125, 250, 500, 1000, 2000, 4000)
NFFT = 8192


def a_weight(f):
    f2 = f ** 2
    ra = (12194.0 ** 2 * f2 ** 2) / ((f2 + 20.6 ** 2) * np.sqrt((f2 + 107.7 ** 2) * (f2 + 737.9 ** 2)) * (f2 + 12194.0 ** 2))
    return 20 * np.log10(np.maximum(ra, 1e-30)) + 2.0


F = np.fft.rfftfreq(NFFT, 1 / FS)
DF = F[1]
BAND = (F >= 20)
AW = 10 ** (a_weight(np.maximum(F, 1)) / 10)
WIN = np.hanning(NFFT)
WNORM = FS * (WIN ** 2).sum()


def psd(x):
    """mean-square per Hz, one-sided, Welch with 50% overlap"""
    segs = np.array([x[i:i + NFFT] * WIN for i in range(0, len(x) - NFFT + 1, NFFT // 2)])
    p = (np.abs(np.fft.rfft(segs, axis=1)) ** 2).mean(axis=0) / WNORM
    p[1:-1] *= 2
    return p


def levels(mic):
    """mic: float32 samples with the Sonos-active stretches removed. Returns the CSV fields or None."""
    nb = len(mic) // BLOCK
    if nb < 4:
        return None
    blocks = mic[:nb * BLOCK].reshape(nb, BLOCK)
    blocks = blocks - blocks.mean(axis=1, keepdims=True)
    # per-block A-weighted level from a zero-padded FFT of each 0.5 s block
    sp = np.abs(np.fft.rfft(blocks * np.hanning(BLOCK), n=NFFT, axis=1)) ** 2 / (FS * (np.hanning(BLOCK) ** 2).sum())
    sp[:, 1:-1] *= 2
    bda = 10 * np.log10((sp[:, BAND] * AW[BAND]).sum(axis=1) * DF + 1e-20)
    quiet = blocks[np.argsort(bda)[:max(2, nb // 2)]].ravel()
    p = psd(quiet)
    a = 10 * np.log10((p[BAND] * AW[BAND]).sum() * DF + 1e-20)
    z = 10 * np.log10(p[BAND].sum() * DF + 1e-20)
    octs = [10 * np.log10(p[(F >= c / 2 ** 0.5) & (F < c * 2 ** 0.5)].sum() * DF + 1e-20) for c in OCT]
    pdb = 10 * np.log10(p + 1e-30)
    med = np.median(np.lib.stride_tricks.sliding_window_view(np.pad(pdb, 40, mode='edge'), 81), axis=1)
    prom = pdb - med
    idx = [i for i in range(1, len(F) - 1) if 40 <= F[i] <= 6000 and prom[i] >= 8
           and pdb[i] >= pdb[i - 1] and pdb[i] >= pdb[i + 1]]
    idx = sorted(idx, key=lambda i: -prom[i])[:8]
    tones = ';'.join(f'{F[i]:.0f}:{prom[i]:.0f}:{pdb[i] + 10 * np.log10(DF):.0f}' for i in sorted(idx))
    return (nb, np.percentile(bda, 20), np.median(bda), a, z, octs, tones)


new = not os.path.exists(out)
log = open(out, 'a', buffering=1)
if new:
    log.write('epoch,blocks,dba_p20,dba_med,dba_bg,dbz_bg,' + ','.join(f'o{c}' for c in OCT) +
              ',tones(Hz:prominence dB:level dBFS),offset\n')
pos = os.path.getsize(dump) // FB * FB
hold = 0                                   # frames still to drop after the reference went quiet
end = time.time() + hours * 3600
while time.time() < end:
    time.sleep(CLIP)
    size = os.path.getsize(dump)
    if size < pos:                         # renamed or truncated: start from the new file's end
        pos = size // FB * FB
        continue
    n = (size - pos) // FB
    if n <= 0:
        continue
    with open(dump, 'rb') as f:
        f.seek(pos)
        x = np.frombuffer(f.read(n * FB), np.float32).reshape(n, 3, FRAME)
    pos += n * FB
    if n > CLIP * 100 * 3:                 # a backlog (we were paused): only the newest clip is "now"
        x = x[-int(CLIP * 100):]
    keep = np.ones(len(x), bool)
    for i, fr in enumerate(x):
        if np.abs(fr[1]).max() > 1e-4:
            hold = 100
        if hold:
            keep[i] = False
            hold -= 1
    r = levels(x[keep, 0, :].ravel())
    now = time.time()
    del x
    if r is None:
        log.write(f'{now:.0f},0,,,,,' + ',' * (len(OCT) - 1) + f',,{pos}\n')
        continue
    nb, p20, med, a, z, octs, tones = r
    log.write(f'{now:.0f},{nb},{p20:.2f},{med:.2f},{a:.2f},{z:.2f},' + ','.join(f'{o:.1f}' for o in octs) + f',{tones},{pos}\n')
