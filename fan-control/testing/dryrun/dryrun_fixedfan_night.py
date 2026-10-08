#!/usr/bin/env python3
# Dry run of scripts/thu/mementos-fixedfan-night.py: fake clock, fake ipmitool/systemctl/stress-ng, a first-order CPU
# model (steady CPU = inlet + 26/(1+0.02(f-10)) + 3.33 n/(1+0.04(f-10)), tau 60 s; HOT adds C to it), room from ROOM.
# FAIL=k makes the k-th temperature read fail once (tests the retry). Prints notes, fan commands and peak CPU per phase.
import builtins, io, os, re, sys, tempfile, types, time as _t
SRC = sys.argv[1]; HOT = float(os.environ.get('HOT', 0)); ROOM = os.environ.get('ROOM', '24'); FAIL = int(os.environ.get('FAIL', 0))
T0 = 1_800_000_000.0; clock = [T0]; st = {'fan': 10, 'n': 0, 'cpu': 50.0, 'reads': 0, 'auto': False}
notes, fans, peak = [], [], {}
tmp = tempfile.mkdtemp(); CSV = f'{tmp}/ff.csv'
def m(): return round((clock[0] - T0) / 60, 1)
def advance(s):
    import math
    ss = 24 + 26 / (1 + 0.02 * (st['fan'] - 10)) + 3.33 * st['n'] / (1 + 0.04 * (st['fan'] - 10)) + (HOT if st['n'] else 0)
    st['cpu'] = ss + (st['cpu'] - ss) * math.exp(-s / 60); clock[0] += s
def fake_run(args, capture_output=True, text=True, timeout=None, **k):
    a = list(args); out = ''
    if a[0] == 'systemctl': notes.append((m(), 'systemctl ' + ' '.join(a[1:])))
    elif a[:4] == ['ipmitool', 'sdr', 'type', 'Temperature']:
        st['reads'] += 1
        if FAIL and st['reads'] == FAIL: out = ''
        else:
            c = round(st['cpu']); out = f'Inlet Temp | 04h | ok | 7.1 | 24 degrees C\nExhaust Temp | 01h | ok | 7.1 | 40 degrees C\nTemp | 0Eh | ok | 3.1 | {c} degrees C\nTemp | 0Fh | ok | 3.2 | {c-2} degrees C\n'
    elif a[:4] == ['ipmitool', 'sdr', 'type', 'Fan']: out = 'Fan1 | 30h | ok | 7.1 | 3400 RPM\n'
    elif a[:3] == ['ipmitool', 'dcmi', 'power']: out = 'Instantaneous power reading: 300 Watts\n'
    elif a[:4] == ['ipmitool', 'raw', '0x30', '0x30']:
        if a[4] == '0x02': st['fan'] = int(a[6], 16); fans.append((m(), st['fan']))
        if a[4:6] == ['0x01', '0x01']: st['auto'] = True; fans.append((m(), 'AUTO'))
    return types.SimpleNamespace(stdout=out, stderr='', returncode=0)
class FakeStress:
    def __init__(self, a, **k): st['n'] = int(a[2]); self.alive = True
    def poll(self): return None if self.alive else 0
    def terminate(self): self.alive = False; st['n'] = 0
    def wait(self, t=None): return 0
    def kill(self): self.terminate()
real_open = builtins.open
def fake_open(p, *a, **k):
    if p == '/run/room-inlet': return io.StringIO(f'{int(clock[0])} {ROOM}')
    if p == '/var/tmp/dimm-log.csv': return io.StringIO('x,y,45,40\n')
    return real_open(p, *a, **k)
def sleep(s):
    advance(s); cur = notes[-1][1] if notes else ''
ft = types.SimpleNamespace(time=lambda: clock[0], sleep=sleep, strftime=lambda f, *a: _t.strftime(f, _t.localtime(clock[0])))
src = real_open(SRC).read().replace("CSV = '/var/tmp/mementos-fixedfan-night.csv'", f"CSV = '{CSV}'").replace('import glob, re, subprocess, sys, time\n', '')
g = {'__name__': '__main__', 're': re, 'sys': sys, 'time': ft, 'open': fake_open, 'print': lambda *a, **k: None,
     'glob': types.SimpleNamespace(glob=lambda p: []), 'subprocess': types.SimpleNamespace(run=fake_run, Popen=FakeStress, DEVNULL=None, TimeoutExpired=Exception)}
try: exec(src, g)
except SystemExit as e: notes.append((m(), f'SystemExit {e}'))
for l in real_open(CSV):
    if l[0].isdigit():
        r = l.split(','); peak[r[2]] = max(peak.get(r[2], 0), int(r[7]))
    elif l.startswith('#'): notes.append((None, l.split(' ', 3)[3].strip()))
print('notes:'); [print('  ', n) for n in notes if n[0] is None or 'systemctl' in n[1] or 'SystemExit' in n[1]]
print('fan commands (min, %):', fans)
print('peak CPU per phase:', peak); print('max fan %:', max(f for _, f in fans if f != 'AUTO'), '| auto:', st['auto'], '| total min:', m())
