# Realistic-plant variant of test_md1200_v3.py (2026-10-06): env TAU (s, shelf settling time constant), EXPO (rpm exponent of the rise over room, 1.1 fits exp3), CYC (room +-C, 65 min cycle), PATCH="NAME=value;..." overrides controller constants. usage: TAU=2700 python3 -I tests/<this> md1200-fan
# Closed-loop harness for md1200-fan v3: fake clock + first-order shelf thermal model.
# Hottest drive T -> amb + R(rpm) + extra, tau 15 min; R(3290 rpm) = 23C, R ~ rpm^-0.8.
import json, math, os, re, sys, tempfile, types
SRC = sys.argv[1]
BASE = 1_000_000.0
clock = [BASE]
plant = {'T': 49.0, 'amb': 26.0, 'extra': 0.0, 't': BASE}
TAU=float(os.environ.get('TAU','3600')); EXPO=float(os.environ.get('EXPO','1.1')); CYC=float(os.environ.get('CYC','0'))
sent, printed, events = [], [], []
last_pct = [20]
def now(): return clock[0] - BASE
def rpm(p): return 2330 + (p - 10) * 96
def t_inf(): return plant['amb'] + CYC * math.sin(2 * math.pi * now() / 3900) + 22.5 * (3290 / rpm(last_pct[0])) ** EXPO + plant['extra']
def advance():
    dt = clock[0] - plant['t']
    if dt > 0:
        plant['T'] = t_inf() + (plant['T'] - t_inf()) * math.exp(-dt / TAU)
        plant['t'] = clock[0]
def temps():
    advance(); T = plant['T']
    return {'drive': round(T), 'bp': round(T - 4), 'sim': round(T + 3), 'exp': round(T + 30)}
class FakeSerial:
    def __init__(self, *a, **k): self.buf = b''
    def close(self): pass
    def write(self, data):
        cmd = data.decode().strip(); prompt = '\r\nBlueDress.106.000 >'
        if cmd.startswith('_shutup'):
            advance(); p = int(cmd.split()[1]); last_pct[0] = p; sent.append((now(), p))
            self.buf = (cmd + prompt).encode()
        elif cmd == '_who':
            self.buf = ("_who\r\nEMM (I'm primary and  active)  : 0 1" + prompt).encode()
        elif cmd == '_temp_rd':
            t = temps()
            self.buf = (f"_temp_rd\r\nBP_1[2] = {t['bp']-2}c\r\nBP_2[3] = {t['bp']}c\r\nSIM0[0] = {t['sim']}c\r\nSIM1[1] = {t['sim']-3}c\r\nEXP0[4] = {t['exp']}c\r\nEXP1[5] = {t['exp']-3}c" + prompt).encode()
    def read(self, n):
        clock[0] += 0.05; b, self.buf = self.buf, b''; return b
ZP = "dataPool\t87.3T\n\traidz2-0\t87.3T\n" + ''.join(f"\t/dev/disk/by-id/wwn-0x5000c500862d{i:04x}-part1\n" for i in range(12)) + "logs\t-\n\t/dev/disk/by-id/wwn-0x5000cca02b3ee8cc-part1\n"
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
def run(label, end, T0=49.0, amb=26.0, start_pct=20, evs=(), state=None):
    clock[0] = BASE; plant.update(T=T0, amb=amb, extra=0.0, t=BASE); last_pct[0] = start_pct
    sent.clear(); printed.clear(); END[0] = end; ev = sorted(evs)
    st = tempfile.NamedTemporaryFile('w', delete=False, suffix='.json')
    if state: json.dump(state, st)
    st.close()
    src = open(SRC).read().replace('import json, re, subprocess, sys, time, serial', 'import json, re, sys')
    for kv in os.environ.get('PATCH', '').split(';'):
        if kv:
            k, v = kv.split('=', 1)
            src = re.sub(rf'^{k} = [^#\n]*', f'{k} = {v}  ', src, count=1, flags=re.M)
    src = src.replace("STATE = '/run/md1200-fan.state'", f"STATE = '{st.name}'")
    def sleep(s):
        clock[0] += s
        while ev and now() >= ev[0][0]: ev.pop(0)[1]()
        if now() > END[0]: raise Stop()
    import time as _t
    ft = types.SimpleNamespace(time=lambda: clock[0], sleep=sleep, strftime=lambda f, *a: _t.strftime(f, _t.localtime(clock[0])),
                               strptime=_t.strptime, mktime=lambda tup: _t.mktime(tup))
    g = {'__name__': 'sim', 'serial': types.SimpleNamespace(Serial=FakeSerial), 'subprocess': types.SimpleNamespace(run=fake_run),
         'time': ft, 'json': json, 'print': lambda *a, **k: printed.append((round(now()), ' '.join(map(str, a))))}
    try: exec(src, g)
    except Stop: pass
    os.unlink(st.name)
    # summarize: % and T every 10 min
    ch, last = [], None
    for t, p in sent:
        if p != last: ch.append((round(t / 60), p)); last = p
    print(f'## {label}')
    print('   % changes (min, %):', ch[:40])
    return ch
def pct_at(ch, minute):
    p = None
    for m, v in ch:
        if m <= minute: p = v
    return p
def changes_between(ch, a, b): return [v for m, v in ch if a <= m <= b]


def summary(label, end, **kw):
    ch = run(label, end, **kw)
    late = [v for m, v in ch if m >= 120]
    n_late = len(late)
    lo = min([pct_at(ch, 120)] + late); hi = max([pct_at(ch, 120)] + late)
    print(f'   SUMMARY changes_after_2h={n_late} range_after_2h={lo}-{hi} final={pct_at(ch, end//60)} T_end={plant["T"]:.1f}')
summary('A morning: drive 50, room 27, start 25%', 8*3600, T0=50.0, amb=27.0, start_pct=25)
summary('B start 48.5, room 26, 22%', 8*3600, T0=48.5, amb=26.0, start_pct=22)
