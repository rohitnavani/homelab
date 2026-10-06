#!/usr/bin/env python3
# ryuji_profile_table: merge ryuji-profile CSVs into one offset x load table (settled = last 3 min of each phase,
# phases shorter than 4 min or with the load dropped are flagged), with the room from makoto's room.csv, plus the CPU
# thermal resistance (C per package W, per socket) against CPU fan rpm and a projection for other CPU powers.
# usage: ryuji_profile_table.py <room.csv> <profile.csv> [profile.csv ...] [--project W_per_socket ...]
import bisect, csv, sys

args = sys.argv[1:]
proj = []
if '--project' in args:
    i = args.index('--project'); proj = [float(x) for x in args[i + 1:]]; args = args[:i]
room_csv, files = args[0], args[1:]
room = {}
for l in open(room_csv):
    p = l.strip().split(',')
    try:
        room[int(p[0])] = int(p[2])
    except (ValueError, IndexError):
        pass
rk = sorted(room)

def room_mean(a, b):
    v = [room[t] for t in rk[bisect.bisect_left(rk, a):bisect.bisect_right(rk, b)]]
    return sum(v) / len(v) if v else float('nan')

def f(r, k):
    try:
        return float(r[k])
    except (KeyError, ValueError, TypeError):
        return None

out = []
for fn in files:
    rows = [r for r in csv.DictReader(l for l in open(fn) if not l.startswith('#'))]
    phases = {}
    for r in rows:
        if r['phase'].endswith('_wait'):
            continue
        phases.setdefault(r['phase'], []).append(r)
    for ph, rs in phases.items():
        t1 = int(rs[-1]['epoch']); t0 = int(rs[0]['epoch'])
        last = [r for r in rs if int(r['epoch']) >= t1 - 180]
        def m(k):
            v = [f(r, k) for r in last if f(r, k) is not None]
            return sum(v) / len(v) if v else float('nan')
        loads = {r['load'] for r in last}
        flag = ('short ' if t1 - t0 < 240 else '') + ('load-dropped ' if len(loads) > 1 or '0' in loads and m('load') > 0 else '')
        off = rs[0]['offset']
        out.append(dict(file=fn.split('/')[-1].replace('ryuji-profile-e5-2650v3', '').strip('-').replace('.csv', '') or 'sweep',
                        phase=ph, off=off, load=m('load'), pkg0=m('pkg0_w'), pkg1=m('pkg1_w'), cpu0=m('cpu0'), cpu1=m('cpu1'),
                        cf=(m('cpu_fan0') + m('cpu_fan1')) / 2, sf=m('sys_fan'), sio1=m('sio1'), sio2=m('sio2'), pch=m('pch'),
                        vr=m('vr'), dimm=m('dimm'), hdd=m('hdd'), w=m('dcmi_w'), room=room_mean(t1 - 180, t1), flag=flag,
                        dur=(t1 - t0) / 60))
def okey(r):
    o = r['off'].lstrip('g')
    try:
        return (-int(o), r['load'])
    except ValueError:
        return (999, r['load'])
print(f'{"run":<9} {"phase":<10} {"off":>5} {"thr":>3} {"pkgW":>5} {"cpu0":>5} {"cpu1":>5} {"cpuFan":>6} {"sysFan":>6} '
      f'{"sio1":>5} {"sio2":>5} {"pch":>5} {"vr":>4} {"dimm":>5} {"hdd":>4} {"W":>4} {"room":>5}  flags')
for r in sorted(out, key=okey):
    print(f'{r["file"]:<9} {r["phase"]:<10} {r["off"]:>5} {r["load"]:3.0f} {r["pkg0"] + r["pkg1"]:5.0f} {r["cpu0"]:5.1f} {r["cpu1"]:5.1f} '
          f'{r["cf"]:6.0f} {r["sf"]:6.0f} {r["sio1"]:5.1f} {r["sio2"]:5.1f} {r["pch"]:5.1f} {r["vr"]:4.0f} {r["dimm"]:5.1f} '
          f'{r["hdd"]:4.0f} {r["w"]:4.0f} {r["room"]:5.1f}  {r["flag"]}{"(" + format(r["dur"], ".0f") + " min)" if r["flag"] else ""}')
# CPU thermal resistance: (CPU temp - room) / socket package W, for loaded phases, against CPU fan rpm
pts = []
for r in out:
    if r['load'] >= 4 and not r['flag']:
        for c, p in (('cpu0', 'pkg0'), ('cpu1', 'pkg1')):
            if r[p] > 20:
                pts.append((r['cf'], (r[c] - r['room']) / r[p], c, r['off'], r['load']))
print('\nCPU C/W (rise over room per package W) vs CPU fan rpm (loaded phases):')
for cf, k, c, off, ld in sorted(pts):
    print(f'  {cf:6.0f} rpm  {k:.3f} C/W  {c} offset {off} {ld:.0f} threads')
if proj and pts:
    # fit k = a + b / rpm (fan-limited convection) for the hotter socket (cpu1)
    hp = [(cf, k) for cf, k, c, *_ in pts if c == 'cpu1']
    n = len(hp); xs = [1 / cf for cf, _ in hp]; ys = [k for _, k in hp]
    mx, my = sum(xs) / n, sum(ys) / n
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    a = my - b * mx
    print(f'\nfit (hotter socket): C/W = {a:.3f} + {b:.0f}/rpm')
    for W in proj:
        print(f'  {W:.0f} W/socket at room 27C: ' + ', '.join(f'{rpm} rpm -> {27 + (a + b / rpm) * W:.0f}C' for rpm in (4000, 5000, 6000, 7000)))
