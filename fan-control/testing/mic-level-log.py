#!/usr/bin/env python3
# mic-level-log: sound level logger on arsene's internal mic (Realtek codec, card 0, "Internal Mic").
# Records CLIP-second clips into RAM, keeps only levels (A-weighted and unweighted, octave bands, the strongest
# tones) and deletes each clip at once. Fixed gain: Capture 23 (0 dB), Internal Mic Boost 0. The mixer state is
# saved first and restored on exit. Levels are dBFS (relative to this mic and gain), not calibrated SPL.
# usage (root): mic-level-log.py <minutes> <csv> [clip seconds, default 10]
import os, subprocess, sys, time, wave
import numpy as np

mins, out = float(sys.argv[1]), sys.argv[2]
CLIP = int(sys.argv[3]) if len(sys.argv) > 3 else 10
WAV, STATE = '/dev/shm/mic-clip.wav', '/dev/shm/mic-asound.before'
OCT = (63, 125, 250, 500, 1000, 2000, 4000, 8000)


def amix(*a):
    subprocess.run(['amixer', '-q', '-c0', 'sset', *a], check=True)


def a_weight(f):
    f2 = f ** 2
    ra = (12194.0 ** 2 * f2 ** 2) / ((f2 + 20.6 ** 2) * np.sqrt((f2 + 107.7 ** 2) * (f2 + 737.9 ** 2)) * (f2 + 12194.0 ** 2))
    return 20 * np.log10(np.maximum(ra, 1e-30)) + 2.0


def levels(path):
    w = wave.open(path)
    fs, ch = w.getframerate(), w.getnchannels()
    x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).reshape(-1, ch)[:, 0] / 32768.0
    x = x[int(0.5 * fs):]                       # drop the ADC settling
    x = x - x.mean()
    n = 16384
    win = np.hanning(n)
    segs = np.array([x[i:i + n] * win for i in range(0, len(x) - n, n // 2)])
    p = (np.abs(np.fft.rfft(segs, axis=1)) ** 2).mean(axis=0) / (fs * (win ** 2).sum())
    p[1:-1] *= 2                                # one-sided power density, mean square per Hz
    f = np.fft.rfftfreq(n, 1 / fs)
    df = f[1]
    band = (f >= 20) & (f <= 20000)
    z = 10 * np.log10(p[band].sum() * df)
    a = 10 * np.log10((p[band] * 10 ** (a_weight(f[band]) / 10)).sum() * df)
    octs = [10 * np.log10(p[(f >= c / 2 ** 0.5) & (f < c * 2 ** 0.5)].sum() * df) for c in OCT]
    # tones: bins standing at least 8 dB above the median of +-40 bins (about +-117 Hz), 40 Hz to 6 kHz
    pdb = 10 * np.log10(p + 1e-30)
    med = np.median(np.lib.stride_tricks.sliding_window_view(np.pad(pdb, 40, mode='edge'), 81), axis=1)
    prom = pdb - med
    idx = [i for i in range(1, len(f) - 1) if 40 <= f[i] <= 6000 and prom[i] >= 8
           and pdb[i] >= pdb[i - 1] and pdb[i] >= pdb[i + 1]]
    idx = sorted(idx, key=lambda i: -prom[i])[:6]
    tones = ';'.join(f'{f[i]:.0f}:{prom[i]:.0f}:{pdb[i] + 10 * np.log10(df):.0f}' for i in sorted(idx))
    return a, z, octs, tones


subprocess.run(['alsactl', '--file', STATE, 'store'], check=True)
try:
    amix('Capture', '23', 'cap')
    amix('Internal Mic Boost', '0')
    amix('Internal Mic', 'cap')
    new = not os.path.exists(out)
    log = open(out, 'a', buffering=1)
    if new:
        log.write('epoch,A,Z,' + ','.join(f'o{c}' for c in OCT) + ',tones(Hz:prominence dB:level dBFS)\n')
    end = time.time() + mins * 60
    while time.time() < end:
        t0 = time.time()
        subprocess.run(['arecord', '-q', '-D', 'hw:0,0', '-f', 'S16_LE', '-r', '48000', '-c', '2',
                        '-d', str(CLIP), WAV], check=True)
        try:
            a, z, octs, tones = levels(WAV)
        finally:
            os.remove(WAV)
        log.write(f'{t0:.0f},{a:.2f},{z:.2f},' + ','.join(f'{o:.1f}' for o in octs) + f',{tones}\n')
finally:
    if os.path.exists(WAV):
        os.remove(WAV)
    subprocess.run(['alsactl', '--file', STATE, 'restore'])
    os.remove(STATE)
