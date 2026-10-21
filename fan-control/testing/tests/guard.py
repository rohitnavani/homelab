# Loaded first by every test (via exec): any real process or network call from the code under test fails the test.
import os, subprocess, urllib.request


def _blocked(*a, **k):
    raise AssertionError(f'REAL CALL BLOCKED: {a[:1]}')


for _n in ('run', 'Popen', 'call', 'check_call', 'check_output', 'getoutput', 'getstatusoutput'):
    setattr(subprocess, _n, _blocked)
os.system = _blocked
os.popen = _blocked
os.execv = os.execvp = os.execvpe = _blocked
os.kill = os.killpg = _blocked          # a fake pid must never reach a real process group
urllib.request.urlopen = _blocked
