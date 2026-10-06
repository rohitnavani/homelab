#!/usr/bin/env python3
# Summarize /var/tmp/shelf-exp2.csv (copied locally): per-phase settled values, rise over R720 inlet,
# and an exponential fit T(t) = Tinf - A*exp(-t/tau) to estimate where each phase was heading.
import csv, math, sys

path = sys.argv[1]
rows, notes = [], []
with open(path) as f:
    lines = [l for l in f]
hdr = next(l for l in lines if l.startswith('time,'))
cols = hdr.strip().split(',')
for l in lines:
    if l.startswith('#'):
        notes.append(l.strip())
    elif not l.startswith('time,') and l.strip():
        rows.append(dict(zip(cols, l.strip().split(','))))

def num(r, k):
    try:
        return float(r[k])
    except (KeyError, ValueError):
        return None

def fit(ts, ys):
    # grid-search tau; for each tau, T = Tinf - A*e^(-t/tau) is linear in (Tinf, A)
    best = None
    for tau in [x / 2 for x in range(4, 241)]:  # 2..120 min
        xs = [math.exp(-t / tau) for t in ts]
        n, sx, sy = len(xs), sum(xs), sum(ys)
        sxx, sxy = sum(x * x for x in xs), sum(x * y for x, y in zip(xs, ys))
        den = n * sxx - sx * sx
        if abs(den) < 1e-12:
            continue
        b = (n * sxy - sx * sy) / den          # = -A
        a = (sy - b * sx) / n                  # = Tinf
        sse = sum((a + b * x - y) ** 2 for x, y in zip(xs, ys))
        if best is None or sse < best[0]:
            best = (sse, a, -b, tau)
    sse, tinf, amp, tau = best
    return tinf, tau, math.sqrt(sse / len(ts))

phases = []
for r in rows:
    if not phases or phases[-1][0] != r['phase']:
        phases.append((r['phase'], []))
    phases[-1][1].append(r)

for n in notes:
    print(n)
print()
keys = ['drive_max', 'drive_avg', 'BP', 'SIM', 'EXP', 'inlet', 'exh', 'cpu', 'dimm_max', 'ssd', 'int_hdd', 'r720_w', 'r720_rpm', 'rpm_avg']
for name, rs in phases:
    last = [r for r in rs if num(r, 'phase_min') is not None and num(r, 'phase_min') >= num(rs[-1], 'phase_min') - 10]
    print(f'== {name}: shelf {rs[0]["shelf_set"]}%, R720 floor {rs[0]["r720_floor"]}%, {rs[0]["time"]}-{rs[-1]["time"]}, {len(rs)} samples')
    for k in keys:
        vals = [num(r, k) for r in last if num(r, k) is not None]
        first = num(rs[0], k)
        if vals:
            print(f'   {k:>9}: start {first}  last10 mean {sum(vals)/len(vals):.2f}  range {min(vals)}-{max(vals)}')
    rise = [num(r, 'drive_avg') - num(r, 'inlet') for r in last if num(r, 'drive_avg') is not None and num(r, 'inlet') is not None]
    if rise:
        print(f'   drive_avg - inlet (last 10 min): {sum(rise)/len(rise):.2f}')
    slots = [sum(num(r, f's{i}') for r in last) / len(last) for i in range(12)] if last else []
    if slots:
        print('   slots last10:', ' '.join(f'{v:.1f}' for v in slots))
    rmin = [num(r, 'rpm_min') for r in rs if num(r, 'rpm_min')]
    rmax = [num(r, 'rpm_max') for r in rs if num(r, 'rpm_max')]
    if rmin:
        print(f'   shelf rpm over phase: {min(rmin):.0f}-{max(rmax):.0f}')
    io = [num(r, 'shelf_io_mb') for r in rs if num(r, 'shelf_io_mb') is not None]
    print(f'   shelf io MB: total {sum(io):.0f}, max/min {max(io) if io else 0:.0f}; unsolicited {rs[0]["unsolicited"]}->{rs[-1]["unsolicited"]}; serial errors {rs[0]["serial_errors"]}->{rs[-1]["serial_errors"]}')
    st = {(r['fan_status'], r['emm_status'], r['psu_status']) for r in rs}
    if st != {('OK/OK/OK/OK', 'OK/OK', 'OK/OK')}:
        print('   status seen:', st)
    if len(rs) >= 8:
        ts = [num(r, 'phase_min') for r in rs]
        for k in ['drive_avg', 'drive_max', 'BP', 'SIM']:
            ys = [num(r, k) for r in rs]
            if None in ys:
                continue
            tinf, tau, rmse = fit(ts, ys)
            inl = [num(r, 'inlet') for r in last if num(r, 'inlet') is not None]
            rel = f', {tinf - sum(inl)/len(inl):+.1f} over inlet' if inl else ''
            print(f'   fit {k:>9}: heading to {tinf:.1f} (tau {tau:.0f} min, rmse {rmse:.2f}{rel})')
    print()
