#!/usr/bin/env python3
# Dry run of scripts/thu/r720-notch-sweep.py (copy of dryrun_noise_sweep.py): fake clock, fake EMM console (answers _who as primary unless WHO=secondary),
# fake ipmitool/sg_ses/systemctl. Prints the phase sequence with times and the systemctl calls.
import os, re, sys, tempfile, types, time as _t
SRC = sys.argv[1]; WHO = os.environ.get('WHO', 'primary')
clock = [1_800_000_000.0]; calls = []; shut = []
tmp = tempfile.mkdtemp()
class FakeSerial:
    def __init__(self, *a, **k): self.buf = b''
    def read(self, n): clock[0] += 0.01; b, self.buf = self.buf, b''; return b
    def write(self, d):
        c = d.decode().strip()
        if c == '_who':
            self.buf = (f"_who\r\nEMM (I'm {WHO} and  active)  : 0 1\r\nBlueDress.106.000 >").encode()
        elif c.startswith('_shutup'):
            p = int(c.split()[1]); assert p >= 10
            if not shut or shut[-1][1] != p: shut.append((round((clock[0] - 1_800_000_000) / 60, 1), p))
            self.buf = (c + '\r\nBlueDress.106.000 >').encode()
    def close(self): pass
def fake_run(args, capture_output=True, text=True, timeout=None, **k):
    a = list(args); out = ''
    if a[0] == 'systemctl': calls.append((round((clock[0] - 1_800_000_000) / 60, 1), ' '.join(a[1:])))
    elif a[0] == 'sg_ses': out = 'Actual speed=2800 rpm\n' * 5
    elif a[:4] == ['ipmitool', 'sdr', 'type', 'Temperature']:
        out = 'Inlet Temp | 04h | ok | 7.1 | 24 degrees C\nTemp | 0Eh | ok | 3.1 | 45 degrees C\nTemp | 0Fh | ok | 3.2 | 43 degrees C\n'
    elif a[:4] == ['ipmitool', 'sdr', 'type', 'Fan']: out = 'Fan1 | 30h | ok | 7.1 | 3400 RPM\n'
    elif a[:3] == ['ipmitool', 'raw', '0x30']: calls.append((round((clock[0] - 1_800_000_000) / 60, 1), 'raw ' + ' '.join(a[3:])))
    return types.SimpleNamespace(stdout=out, stderr='', returncode=0)
def sleep(s): clock[0] += s
ft = types.SimpleNamespace(time=lambda: clock[0], sleep=sleep, strftime=lambda f, *a: _t.strftime(f, _t.localtime(clock[0])))
sys.modules['serial'] = types.SimpleNamespace(Serial=FakeSerial)
src = open(SRC).read().replace("CSV = '/var/tmp/r720-notch.csv'", f"CSV = '{tmp}/ns.csv'").replace('import re, subprocess, sys, time\n', '')
src = src.replace("SG = ses_dev()", "SG = '/dev/sg39'")
g = {'__name__': '__main__', 're': re, 'sys': sys, 'time': ft, 'subprocess': types.SimpleNamespace(run=fake_run), 'print': lambda *a, **k: None}
try: exec(src, g)
except SystemExit as e: print('SystemExit:', e)
print('shelf commands (must be none):', shut)
print('systemctl / raw calls:', [c for c in calls if '0x02 0xff' not in c[1]][:12], '...')
print('R720 steps:', [(m, c.split()[-1]) for m, c in calls if '0x02 0xff' in c])
print('total minutes:', round((clock[0] - 1_800_000_000) / 60))
print('csv rows:', sum(1 for l in open(f'{tmp}/ns.csv') if l[0].isdigit()))
