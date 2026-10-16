#!/usr/bin/env python3
# Dry run of mementos-steps.py (2026-10-13 version) with a simulated mementos: fake clock, a fake fan-watchdog state
# file whose CPU temperature and fan % follow the load, fake stress-ng. Prints the script's notes and the total time.
# usage: python3 -I dryrun_mementos_steps.py <script> <plan> [hot]   (hot: CPU 90 under load, to see the stop rule)
import os, re, sys, tempfile, types, time as _t

SRC, PLAN = sys.argv[1], sys.argv[2]
HOT = len(sys.argv) > 3
clock = [1_800_000_000.0]
state = {'stress': 0}
notes = []
tmp = tempfile.mkdtemp()
sf = f'{tmp}/fan-watchdog.state'


def write_state():
    n = state['stress']
    cpu = 50 + (40 if HOT and n else min(30, n))
    pct = 10 + n // 2
    open(sf, 'w').write(f'2026-10-14 01:36:07 {pct}% (cpu={cpu} exh=40 inlet=24 hdd=38 ssd=42) (dimm=43)\n')


class FakePopen:
    def __init__(self, args, **k):
        state['stress'] = int(args[args.index('--cpu') + 1])
        self.alive = True
        write_state()

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.alive = False
        state['stress'] = 0
        write_state()

    def wait(self, t=None):
        return 0

    def kill(self):
        self.terminate()


def sleep(s):
    clock[0] += s
    if clock[0] - 1_800_000_000 > 6 * 3600:
        raise SystemExit('dry run too long')


write_state()
src = open(SRC).read()
src = src.replace("CSV = f'/var/tmp/mementos-steps-{LABEL}.csv'", f"CSV = '{tmp}/dry.csv'")
src = src.replace("STATE = '/run/fan-watchdog.state'", f"STATE = '{sf}'")
src = src.replace("os.stat(STATE).st_mtime", "(time.time() - 10)")
src = src.replace('import glob, os, re, subprocess, sys, time\n', '')
fake_sub = types.SimpleNamespace(Popen=FakePopen, DEVNULL=None, TimeoutExpired=Exception)
ft = types.SimpleNamespace(time=lambda: clock[0], sleep=sleep,
                           strftime=lambda f, *a: _t.strftime(f, a[0] if a else _t.localtime(clock[0])),
                           localtime=lambda s=None: _t.localtime(clock[0] if s is None else s))
g = {'__name__': '__main__', 'subprocess': fake_sub, 'time': ft, 'sys': sys, 'os': os, 're': re,
     'glob': types.SimpleNamespace(glob=lambda p: []), 'print': lambda *a, **k: notes.append(' '.join(map(str, a)))}
sys.argv = ['mementos-steps.py', PLAN, 'dry']
try:
    exec(src, g)
except SystemExit as e:
    notes.append(f'SystemExit {e}')
for n in notes:
    print('  ', n)
rows = [l for l in open(f'{tmp}/dry.csv') if not l.startswith('#')]
print('rows:', len(rows) - 1, '| last:', rows[-1].strip())
print('total minutes:', round((clock[0] - 1_800_000_000) / 60))
