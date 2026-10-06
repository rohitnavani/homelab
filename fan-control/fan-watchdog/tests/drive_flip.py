# wd4 harness: run fw-test (fan-watchdog v4 with a 0.2 s interval) against stubbed sensors; summarize fan commands.
import os, signal, subprocess, sys, time
H = sys.argv[1]
def scen(cpu=49, exh=43, inlet=26, hdd=37, ssd=44, fail=0, dimm=42, dimmfail=0):
    open(H + '/scen.tmp', 'w').write(f'{cpu} {exh} {inlet} {hdd} {ssd} {fail} {dimm} {dimmfail}\n'); os.replace(H + '/scen.tmp', H + '/scen')
open(H + '/raw.log', 'w').close(); scen()
env = dict(os.environ, PATH=H + '/bin:' + os.environ['PATH'])
p = subprocess.Popen(['bash', H + '/fw-test'], env=env, stdout=open(H + '/out.log', 'w'), stderr=subprocess.STDOUT)
marks = []
def step(label, secs, **k):
    scen(**k); marks.append((time.time(), label)); time.sleep(secs)
step('idle 49C', 2)
step('full load 82C', 2, cpu=82)
for i in range(16): step('flip 81/82C', 0.45, cpu=81 if i % 2 == 0 else 82)
step('high load 75C', 2, cpu=75)
step('full load 85C', 2, cpu=85)
step('full load 88C', 2, cpu=88)
step('back to 70C', 6, cpu=70)
step('CPU 91C emergency', 1.5, cpu=91)
step('cool 70C', 8, cpu=70)
step('idle 49C, DIMM 72C', 3, dimm=72)
step('sensor read fails', 1.5, fail=1)
step('recover idle', 9)
marks.append((time.time(), 'SIGTERM')); p.send_signal(signal.SIGTERM); p.wait(timeout=5)
tl = []
for line in open(H + '/raw.log'):
    f = line.split(); t = float(f[0]); a = f[2:]
    if a[:4] == ['0x30', '0x30', '0x01', '0x01']: tl.append((t, 'auto'))
    elif a[:4] == ['0x30', '0x30', '0x02', '0xff']: tl.append((t, int(a[4], 16)))
for i, (t0, label) in enumerate(marks):
    t1 = marks[i + 1][0] if i + 1 < len(marks) else 1e18
    comp = []
    for t, v in tl:
        if t0 <= t < t1 and (not comp or comp[-1] != v): comp.append(v)
    print(f'{label:>20}: {comp}')
out = open(H + '/out.log').read().splitlines()
print('log:', [l for l in out if 'hot' in l or 'failed' in l or 'cooled' in l or 'start' in l or 'stopped' in l])
