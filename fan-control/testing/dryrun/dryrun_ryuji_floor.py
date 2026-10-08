#!/usr/bin/env python3
# Dry run of scripts/thu/ryuji-floor.py with a simulated ryuji: fake clock, fake ipmitool/BMC offset tool/lsblk/
# smartctl/systemctl/lscpu. FANMODEL: fan_min at each offset (dict). Prints the script's notes and the phase list.
# usage: python3 -I dryrun_ryuji_floor.py <script> '<json fan_min by offset>'
import json, os, re, sys, tempfile, types, time as _t
SRC, FAN = sys.argv[1], {int(k): v for k, v in json.loads(sys.argv[2]).items()}
clock = [1_800_000_000.0]; state = {'offset': -80, 'stress': 0, 'guard': 'active'}; notes = []; sets = []
tmp = tempfile.mkdtemp()
def fan_for(o):
    ks = sorted(FAN)
    return FAN.get(o, FAN[min(ks, key=lambda k: abs(k - o))])
def fake_run(args, capture_output=True, text=True, timeout=None, env=None, **k):
    a = list(args); out, rc = '', 0
    if a[:2] == ['lscpu', '-p=CORE,SOCKET']:
        out = '\n'.join(f'{c},{s}' for s in (0, 1) for c in range(10))
    elif a[0] == 'ipmitool' and a[1:3] == ['sdr', 'type'] and a[3] == 'Temperature':
        cpu = 45 + (15 if state['stress'] else 0) + max(0, (-80 - state['offset']) // 10)
        out = (f'CPU0_TEMP | 01h | ok | 3.1 | {cpu} degrees C\nCPU1_TEMP | 02h | ok | 3.2 | {cpu+5} degrees C\n'
               f'SIO Temp 1 | 03h | ok | 7.1 | 72 degrees C\nVR_P0_TEMP | 04h | ok | 7.1 | 50 degrees C\nDIMM_P0_A0 | 05h | ok | 7.1 | 40 degrees C\n')
    elif a[0] == 'ipmitool' and a[1:3] == ['sdr', 'type'] and a[3] == 'Fan':
        fm = fan_for(state['offset'])
        out = (f'CPU0_FAN | 60h | ok | 29.1 | {fm + 1000} RPM\nCPU1_FAN | 61h | ok | 29.2 | {fm + 1100} RPM\n'
               + ''.join(f'SYS_FAN{i} | 6{i}h | ok | 29.{i} | {fm + (100 if i % 2 else 0)} RPM\n' for i in range(1, 5))
               + 'SYS_FAN5 | 66h | ns | 29.7 | No Reading\n')
    elif a[0] == 'ipmitool' and a[1] == 'dcmi':
        out = 'Instantaneous power reading: 150 Watts\n'
    elif a[0] == 'ipmitool' and a[1:3] == ['sel', 'info']:
        out = 'Entries          : 571\n'
    elif a[0] == 'lsblk':
        out = 'sdc 1 disk\nsdd 1 disk\n'
    elif a[0] == 'smartctl':
        out = '194 Temperature_Celsius     0x0022   100   100   000    Old_age   Always       -       40\n'
    elif a[0] == 'systemctl':
        if a[1] == 'is-active': out = state['guard'] + '\n'
        elif a[1] in ('start', 'stop'): state['guard'] = 'active' if a[1] == 'start' else 'inactive'
    elif a[0] == 'python3' and 'gbt-fan-offset.py' in a[1]:
        o = int(a[-1]); state['offset'] = o; sets.append((round((clock[0] - 1_800_000_000) / 60, 1), o)); out = f'offset now {o}\n'
    return types.SimpleNamespace(stdout=out, stderr='', returncode=rc)
class FakePopen:
    def __init__(self, args, **k): state['stress'] = int(args[args.index('--cpu') + 1]); self.alive = True
    def poll(self): return None if self.alive else 0
    def terminate(self): self.alive = False; state['stress'] = 0
    def wait(self, t=None): return 0
    def kill(self): self.terminate()
src = open(SRC).read()
src = src.replace("CSV = f'/var/tmp/ryuji-profile-{LABEL}.csv'", f"CSV = '{tmp}/dry.csv'")
src = src.replace("ZONES = sorted(glob.glob('/sys/class/powercap/intel-rapl:[01]'))", "ZONES = []")
src = src.replace("ROOM_FILE, ROOM_START", f"ROOM_FILE_UNUSED, ROOM_START")
open(f'{tmp}/room', 'w').write(f'{int(clock[0])} 24')
src = src.replace("open(ROOM_FILE).read().split()", "(str(int(time.time())), '24')")
fake_sub = types.SimpleNamespace(run=fake_run, Popen=FakePopen, DEVNULL=None, TimeoutExpired=Exception)
def sleep(s):
    clock[0] += s
    if clock[0] - 1_800_000_000 > 6 * 3600: raise SystemExit('dry run too long')
ft = types.SimpleNamespace(time=lambda: clock[0], sleep=sleep, strftime=lambda f, *a: _t.strftime(f, _t.gmtime(clock[0])))
g = {'__name__': '__main__', 'subprocess': fake_sub, 'time': ft, 'sys': sys, 'os': os, 're': re,
     'glob': types.SimpleNamespace(glob=lambda p: []), 'print': lambda *a, **k: notes.append(' '.join(map(str, a)))}
src = src.replace('import glob, os, re, subprocess, sys, time\n', '')
sys.argv = ['ryuji-floor.py', 'dry', os.environ.get('PLAN', 'floor')]
try:
    exec(src, g)
except SystemExit as e:
    notes.append(f'SystemExit {e}')
for n in notes: print('  ', n)
print('offset sets (min, offset):', sets)
print('total minutes:', round((clock[0] - 1_800_000_000) / 60))
