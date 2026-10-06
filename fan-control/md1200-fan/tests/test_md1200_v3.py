# Closed-loop harness for md1200-fan v3: fake clock + first-order shelf thermal model.
# Hottest drive T -> amb + R(rpm) + extra, tau 15 min; R(3290 rpm) = 23C, R ~ rpm^-0.8.
import json, math, os, re, sys, tempfile, types
SRC = sys.argv[1]
BASE = 1_000_000.0
clock = [BASE]
plant = {'T': 49.0, 'amb': 26.0, 'extra': 0.0, 't': BASE}
sent, printed, events = [], [], []
last_pct = [20]
def now(): return clock[0] - BASE
def rpm(p): return 2330 + (p - 10) * 96
def t_inf(): return plant['amb'] + 23.0 * (3290 / rpm(last_pct[0])) ** 0.8 + plant['extra']
def advance():
    dt = clock[0] - plant['t']
    if dt > 0:
        plant['T'] = t_inf() + (plant['T'] - t_inf()) * math.exp(-dt / 900)
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
ok = True
def expect(c, msg):
    global ok; print('   ', 'PASS' if c else 'FAIL', msg); ok &= c
# 1 settle at 26C room from 20%
ch = run('1 settle at room 26C', 4 * 3600)
final = pct_at(ch, 240); late = changes_between(ch, 150, 240)
expect(20 <= final <= 24, f'settles near 21-22% (got {final}%)')
expect(len(late) <= 4 and (max(late) - min(late) if late else 0) <= 2, f'steady in the last 90 min (changes {late})')
expect(abs(plant['T'] - 48.5) <= 1.0, f'hottest drive ends near target 48.5C (model {plant["T"]:.1f}C)')
# 2 AC comes back after 1h: room 26 -> 21
ch = run('2 AC back at 60 min (room 21C)', 5 * 3600, T0=48.5, start_pct=22, evs=[(3600, lambda: plant.update(amb=21.0))])
fin = pct_at(ch, 300)
expect(fin < 22, f'gets quieter when the room cools (22% -> {fin}%)')
expect(abs(plant['T'] - 48.5) <= 1.5 or fin == 10, f'still holds the target or reaches 10% (model {plant["T"]:.1f}C)')
# 3 scrub-like heat: +5C for 40 min starting at 60 min
ch = run('3 heavy load +5C for 40 min', 4 * 3600, T0=48.5, start_pct=22, evs=[(3600, lambda: plant.update(extra=5.0)), (6000, lambda: plant.update(extra=0.0))])
peak = max(v for m, v in ch if 60 <= m <= 110)
expect(peak <= 45, f'medium level under load, peak {peak}% (cap 45%)')
expect(pct_at(ch, 240) <= 25, f'comes back down afterwards ({pct_at(ch, 240)}%)')
# 4 spike to urgent
ch = run('4 sudden spike (+8C)', 3600, T0=48.5, start_pct=22, evs=[(600, lambda: plant.update(T=56.0, extra=6.0))])
after = [v for m, v in ch if 10 <= m <= 15]
expect(after and max(after) >= 32, f'ramps fast on an urgent reading (within 5 min: {after})')
drops = [a - b for (_, a), (_, b) in zip(ch, ch[1:]) if a > b]
expect(all(d <= 5 for d in drops), f'never drops more than 5% at once (drops {drops})')
# 5 restart with a fresh state file -> resumes its last %
import time as _t
ch = run('5 restart resumes last %', 120, T0=48.5, start_pct=10, state={'time': _t.strftime('%Y-%m-%d %H:%M:%S', _t.localtime(BASE - 60)), 'pct': 23})
expect(ch and ch[0][1] == 23, f'starts at the saved 23% (got {ch[0][1] if ch else None})')
print('ALL PASS' if ok else 'SOME FAILED')
