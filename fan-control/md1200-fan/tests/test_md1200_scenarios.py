#!/usr/bin/env python3
# Closed-loop scenarios for md1200-fan (written 2026-10-08 for v3.2). Runs the real controller source on a fake clock
# with a fake EMM console, smartctl, zpool and sg_ses, against a first-order model of the shelf's hottest drive:
#   T -> room + R20 * (3290 / rpm) ** EXPO + extra, time constant TAU * (3290 / rpm) ** TEXP
# The defaults are the fit to the steady-room overnight map of 2026-10-07/08 (10, 12, 15, 20, 25%, 75-120 min each):
# R20 18.1C (the hottest drive's rise over the room at 20%), EXPO 1.15, TAU 1200 s at 20%, TEXP 0.67; backplane =
# T - BP_OFF (4, measured 2.9-5.1), SIM = T + 2, expander = T + 30. Each reading gets +-NOISE C before rounding.
# Env: TAU, TEXP, R20, EXPO, BP_OFF, NOISE override the model; JSON=1 prints a machine-readable summary last.
# Scenarios A-I: settled room, hot-room start, recovery from 37%, scrubs, AC failure, a 56C spike, room cycling and
# the 2026-10-07 runaway's shape (one reading at the urgent threshold in a hot room).
# usage: python3 -I tests/test_md1200_scenarios.py <controller source> [scenario ...]
import json, math, os, random, re, sys, tempfile, types, time as _t

SRC = sys.argv[1]
ONLY = set(sys.argv[2:])
BASE = 1_800_000_000.0
TAU = float(os.environ.get('TAU', '1200')); TEXP = float(os.environ.get('TEXP', '0.67'))
R20 = float(os.environ.get('R20', '18.1')); EXPO = float(os.environ.get('EXPO', '1.15'))
BP_OFF = float(os.environ.get('BP_OFF', '4'))
NOISE = float(os.environ.get('NOISE', '0.5'))   # +-C on each reading before rounding (hottest of 12 integer sensors)
rng = random.Random(1)
clock = [BASE]
plant = {'T': 49.0, 'amb': 23.5, 'extra': 0.0, 't': BASE, 'cyc': 0.0}
last_pct = [20]
sent, printed, trace = [], [], []

def now(): return clock[0] - BASE
def rpm(p): return 2330 + (p - 10) * 96
def amb(): return plant['amb'] + plant['cyc'] * math.sin(2 * math.pi * now() / 3900)
def t_inf(p=None): return amb() + R20 * (3290 / rpm(last_pct[0] if p is None else p)) ** EXPO + plant['extra']
def tau(): return TAU * (3290 / rpm(last_pct[0])) ** TEXP
def advance():
    dt = clock[0] - plant['t']
    while dt > 0:   # integrate in <= 10 s steps so a changing room and tau are followed
        h = min(dt, 10.0)
        plant['T'] = t_inf() + (plant['T'] - t_inf()) * math.exp(-h / tau())
        dt -= h
    plant['t'] = clock[0]
def temps():
    advance(); T = plant['T']
    n = lambda: rng.uniform(-NOISE, NOISE)
    return {'drive': round(T + n()), 'bp': round(T - BP_OFF + n()), 'sim': round(T + 2 + n()), 'exp': round(T + 30 + n())}

class FakeSerial:
    def __init__(self, *a, **k): self.buf = b''
    def close(self): pass
    def write(self, data):
        cmd = data.decode().strip(); prompt = '\r\nBlueDress.106.000 >'
        if cmd.startswith('_shutup'):
            advance(); p = int(cmd.split()[1]); assert p >= 10, 'never _shutup below 10'
            last_pct[0] = p; sent.append((now(), p))
            self.buf = (cmd + prompt).encode()
        elif cmd == '_who':
            self.buf = ("_who\r\nEMM (I'm primary and  active)  : 0 1" + prompt).encode()
        elif cmd == '_temp_rd':
            t = temps()
            self.buf = (f"_temp_rd\r\nBP_1[2] = {t['bp']-2}c\r\nBP_2[3] = {t['bp']}c\r\nSIM0[0] = {t['sim']}c\r\n"
                        f"SIM1[1] = {t['sim']-3}c\r\nEXP0[4] = {t['exp']}c\r\nEXP1[5] = {t['exp']-3}c" + prompt).encode()
    def read(self, n):
        clock[0] += 0.05; b, self.buf = self.buf, b''; return b

ZP = "dataPool\t87.3T\n\traidz2-0\t87.3T\n" + ''.join(
    f"\t/dev/disk/by-id/wwn-0x5000c500862d{i:04x}-part1\n" for i in range(12)) + "logs\t-\n\t/dev/disk/by-id/wwn-0x5000cca02b3ee8cc-part1\n"
def fake_run(args, capture_output=True, text=True):
    out = ''
    if args[0] == 'zpool': out = ZP
    elif args[0] == 'smartctl':
        t = temps(); out = f"Current Drive Temperature:     {t['drive'] if args[-1].endswith('0000') else t['drive'] - 3} C\n"
    elif args[0] == 'sg_ses':
        out = ''.join(f'Actual speed={rpm(last_pct[0])} rpm\n' for _ in range(5))
    return types.SimpleNamespace(stdout=out)

class Stop(Exception): pass
END = [0]

def settle_pct(room, target):
    for p in range(10, 46):
        if room + R20 * (3290 / rpm(p)) ** EXPO <= target:
            return p
    return 45

def run(end, T0, room, start_pct, evs=(), cyc=0.0):
    clock[0] = BASE; plant.update(T=T0, amb=room, extra=0.0, t=BASE, cyc=cyc); last_pct[0] = start_pct; rng.seed(1)
    sent.clear(); printed.clear(); trace.clear(); END[0] = end; ev = sorted(evs, key=lambda e: e[0])
    st = tempfile.NamedTemporaryFile('w', delete=False, suffix='.json')
    json.dump({'time': _t.strftime('%Y-%m-%d %H:%M:%S', _t.localtime(BASE)), 'pct': start_pct}, st); st.close()
    src = open(SRC).read().replace('import json, re, subprocess, sys, time, serial', 'import json, re, sys')
    src = src.replace("STATE = '/run/md1200-fan.state'", f"STATE = '{st.name}'")
    for kv in os.environ.get('PATCH', '').split(';'):   # PATCH="NAME=value;..." overrides module constants
        if kv:
            k, v = kv.split('=', 1)
            src, n = re.subn(rf'^{k} = [^#\n]*', f'{k} = {v}  ', src, count=1, flags=re.M)
            assert n == 1, k
    next_trace = [0.0]
    def sleep(s):
        clock[0] += s
        while ev and now() >= ev[0][0]: ev.pop(0)[1]()
        if now() >= next_trace[0]:
            advance(); trace.append((now(), last_pct[0], plant['T'])); next_trace[0] += 60
        if now() > END[0]: raise Stop()
    ft = types.SimpleNamespace(time=lambda: clock[0], sleep=sleep,
                               strftime=lambda f, *a: _t.strftime(f, _t.localtime(clock[0] if not a else _t.mktime(a[0]))),
                               strptime=_t.strptime, mktime=_t.mktime, localtime=_t.localtime)
    g = {'__name__': 'sim', 'serial': types.SimpleNamespace(Serial=FakeSerial),
         'subprocess': types.SimpleNamespace(run=fake_run), 'time': ft, 'json': json,
         'print': lambda *a, **k: printed.append((round(now()), ' '.join(map(str, a))))}
    try:
        exec(src, g)
    except Stop:
        pass
    os.unlink(st.name)
    ch, last = [], None
    for t, p in sent:
        if p != last: ch.append((round(t / 60), p)); last = p
    return ch

def summary(name, ch, note=''):
    peak = max(p for _, p, _ in trace); tmax = max(T for _, _, T in trace)
    end_p, end_T = trace[-1][1], trace[-1][2]
    nch = len(ch) - 1
    print(f'{name:<34} changes {nch:3d}  peak {peak:2d}%  T max {tmax:5.1f}  end {end_p:2d}% T {end_T:5.1f}  {note}')
    return dict(changes=nch, peak=peak, tmax=tmax, end_pct=end_p, end_T=end_T)

def first_time_within(target_pct, tol=1, after=0):
    for t, p, T in trace:
        if t >= after and abs(p - target_pct) <= tol:
            return t / 60
    return None

def target_of():
    m = re.search(r"TARGET = \{'drive': ([0-9.]+)", open(SRC).read())
    return float(m.group(1))

TGT = target_of()
results = {}
def scenario(key, fn):
    if not ONLY or key in ONLY:
        results[key] = fn()

H = 3600
# A: settled start in a steady room, 4 h: a good controller makes 0-2 changes.
def sA():
    room = 23.5; p = settle_pct(room, TGT); T0 = room + R20 * (3290 / rpm(p)) ** EXPO
    ch = run(4 * H, T0, room, p)
    return summary('A settled 23.5C room, 4 h', ch, f'(settle {p}%, T0 {T0:.1f})')
# B: 10-07 morning: 27.5C room, start at 10% with the drives at 48 (the quiet mode's start), 4 h.
def sB():
    ch = run(4 * H, 48.0, 27.5, 10)
    p = settle_pct(27.5, TGT)
    return summary('B 10% start in a 27.5C room, 4 h', ch, f'(settle {p}%, first within 1% at {first_time_within(p)} min)')
# C: after an emergency: 37% with the drives at 39 in a 24C room (10-07 08:45), 10 h.
def sC():
    ch = run(10 * H, 39.0, 24.0, 37)
    p = settle_pct(24.0, TGT)
    return summary('C recover from 37%, 24C room, 10 h', ch, f'(settle {p}%, first within 1% at {first_time_within(p)} min)')
# D: a scrub: +3C on the drives for 46 min from a settled start (10-06: every drive +3C during the scrub).
def sD():
    room = 23.5; p = settle_pct(room, TGT); T0 = room + R20 * (3290 / rpm(p)) ** EXPO
    ch = run(5 * H, T0, room, p, evs=[(1 * H, lambda: plant.update(extra=3.0)), (1 * H + 46 * 60, lambda: plant.update(extra=0.0))])
    return summary('D scrub +3C 46 min, 23.5C room', ch, f'(settle {p}%)')
# E: AC failure: room 23.5 -> 28 at 1 h for 4 h, then back, 9 h total.
def sE():
    room = 23.5; p = settle_pct(room, TGT); T0 = room + R20 * (3290 / rpm(p)) ** EXPO
    ch = run(9 * H, T0, room, p, evs=[(1 * H, lambda: plant.update(amb=28.0)), (5 * H, lambda: plant.update(amb=23.5))])
    return summary('E AC fails 4 h (23.5 -> 28C)', ch, f'(settle {p}% -> {settle_pct(28.0, TGT)}%)')
# F: an emergency spike: drives jump to 56C (extra +6C for 30 min).
def sF():
    room = 23.5; p = settle_pct(room, TGT); T0 = room + R20 * (3290 / rpm(p)) ** EXPO
    ch = run(8 * H, T0, room, p, evs=[(30 * 60, lambda: plant.update(T=56.0, extra=6.0)), (60 * 60, lambda: plant.update(extra=0.0))])
    t60 = next((t / 60 for t, pp, T in trace if pp >= 60), None)
    low = min(pp for t, pp, T in trace if t > 3 * H)
    return summary('F spike to 56C, 8 h', ch, f'(60% floor at {t60} min; lowest % after 3 h {low}; settle {p}%)')
# G: the old AC's hourly cycle (+-1C, 65 min) around 25C, settled start, 6 h.
def sG():
    room = 25.0; p = settle_pct(room, TGT); T0 = room + R20 * (3290 / rpm(p)) ** EXPO
    ch = run(6 * H, T0, room, p, cyc=1.0)
    return summary('G room cycle +-1C/65 min, 6 h', ch, f'(settle {p}%)')
# H: a hot room plus a scrub: 27.5C room settled, scrub +3C 46 min.
def sH():
    room = 27.5; p = settle_pct(room, TGT); T0 = room + R20 * (3290 / rpm(p)) ** EXPO
    ch = run(5 * H, T0, room, p, evs=[(1 * H, lambda: plant.update(extra=3.0)), (1 * H + 46 * 60, lambda: plant.update(extra=0.0))])
    return summary('H scrub +3C in a 27.5C room', ch, f'(settle {p}%)')

# I: forced urgent: a 28.5C room with the shelf held low (10%, drives already at 50C), 4 h (the 10-07 runaway's shape).
def sI():
    ch = run(4 * H, 50.0, 28.5, 10)
    urg = [(m, p) for m, p in ch]
    return summary('I 10% start, drives 50C, 28.5C room', ch, f'(settle {settle_pct(28.5, TGT)}%, first 15 changes {urg[:15]})')

print(f'# {os.path.basename(SRC)}: target {TGT}C; model R20 {R20} EXPO {EXPO} TAU {TAU:.0f}s TEXP {TEXP} NOISE {NOISE} '
      f'(tau at 10% {TAU*(3290/2330)**TEXP/60:.0f} min, 20% {TAU/60:.0f}, 37% {TAU*(3290/rpm(37))**TEXP/60:.0f})')
for k, f in [('A', sA), ('B', sB), ('C', sC), ('D', sD), ('E', sE), ('F', sF), ('G', sG), ('H', sH), ('I', sI)]:
    scenario(k, f)
if os.environ.get('JSON'):
    print(json.dumps(results))
