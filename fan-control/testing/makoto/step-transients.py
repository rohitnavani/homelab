# step-transients: mic level in 0.5 s blocks around fan step changes (from a fanstep CSV), from the live AEC dump.
# Maps time to file offset assuming real-time appends since the dump's last write (gaps would shift it). Levels only.
import csv, os, sys, time
import numpy as np
dump, steps = sys.argv[1], sys.argv[2]
FB, FS = 1920, 16000
size, mtime = os.path.getsize(dump), os.path.getmtime(dump)
rows = list(csv.DictReader(open(steps)))
starts = []
for i, r in enumerate(rows):
    if i == 0 or r['label'] != rows[i - 1]['label']:
        starts.append((int(r['epoch']) - 2, rows[i - 1]['label'] if i else '', r['label']))
F = np.fft.rfftfreq(8000, 1 / FS)
def bandlev(x, lo, hi):
    s = np.abs(np.fft.rfft((x - x.mean()) * np.hanning(len(x)))) ** 2
    return 10 * np.log10(s[(F >= lo) & (F < hi)].sum() + 1e-20)
out = {}
with open(dump, 'rb') as f:
    for t, prev, lab in starts:
        off = size - int(round((mtime - (t - 15)) * 100)) * FB
        if off < 0: continue
        f.seek(off); n = 30 * 100
        x = np.frombuffer(f.read(n * FB), np.float32).reshape(-1, 3, 160)
        mic, ref = x[:, 0, :].ravel(), np.abs(x[:, 1, :]).max()
        bl = mic[:len(mic) // 8000 * 8000].reshape(-1, 8000)
        out[(t, prev, lab)] = ([bandlev(b, 150, 2500) for b in bl], [bandlev(b, 2500, 7000) for b in bl], [bandlev(b, 40, 150) for b in bl], ref)
for (t, prev, lab), (mid, hi, lo, ref) in out.items():
    m = np.array(mid); h = np.array(hi); l = np.array(lo)
    print(f"{time.strftime('%H:%M:%S', time.localtime(t))} {prev:>8s} -> {lab:8s} 150-2500 Hz: before {np.median(m[:28]):6.1f} after(2-8s) {np.median(m[34:46]):6.1f} after(8-15s) {np.median(m[46:]):6.1f} | 2.5-7k {np.median(h[:28]):6.1f}->{np.median(h[34:]):6.1f} | 40-150 {np.median(l[:28]):6.1f}->{np.median(l[34:]):6.1f} ref {ref:.0e}")
