#!/usr/bin/env python3
# mementos-fixedfan-night (2026-10-07 21:10): the light half of the map for the early morning of 10-08, after Rohit
# allowed slightly louder night tests ("you can go a little bit louder than now"; ceiling about -67 dB(A) at the
# mic). Differences from the day script: PLAN is 6 and 12 workers at fixed 10-20% only; a CPU at 85C stops the load
# with no fan boost, and only a CPU at 88C raises the fans, to NIGHT_MAX (24%, the night cap) instead of 60%; a failed
# sensor read is retried once before going to iDRAC auto; CSV /var/tmp/mementos-fixedfan-night.csv.
# mementos-fixedfan (2026-10-06): hold the R720 fans at a fixed % while running a fixed CPU load, to see which fan
# level each load needs (Rohit: "could it handle full load at 50% fans? if so, then high load ought to be fine at 30%").
# Owns the fans while it runs: stops fan-watchdog first (whose exit puts the iDRAC in auto for a moment), then sets
# manual fan speed with the same Dell commands fan-watchdog uses (ipmitool raw 0x30 0x30 ...).
# Safety: CPU >= 88C -> fans 60% and the load stops for the rest of the step; CPU >= 92C, a failed sensor read, or a
# failed fan command -> iDRAC auto and exit. Exhaust >= 60C or DIMM >= 75C -> load off. Room (makoto's
# /run/room-inlet) above 29C or stale -> load off. ExecStopPost (mementos-fixedfan-restore.sh) kills stress-ng and
# starts fan-watchdog again. CSV /var/tmp/mementos-fixedfan.csv every 15 s.
# Run: systemd-run --unit=mementos-fixedfan -p ExecStopPost=/var/tmp/mementos-fixedfan-restore.sh python3 /var/tmp/mementos-fixedfan.py
import glob, re, subprocess, sys, time

PLAN = [  # label, fan %, stress-ng matrixprod workers (of 48 threads), minutes
    ('w6_15', 15, 6, 7), ('w6_12', 12, 6, 7), ('w6_10', 10, 6, 7), ('cool_15', 15, 0, 3),
    ('w12_20', 20, 12, 7), ('w12_15', 15, 12, 7), ('cool_15b', 15, 0, 3)]
NIGHT_MAX = 24
assert all(10 <= p[1] <= 20 for p in PLAN) and all(p[2] <= 12 for p in PLAN), 'night caps'
CSV = '/var/tmp/mementos-fixedfan-night.csv'
ZONES = sorted(glob.glob('/sys/class/powercap/intel-rapl:[01]'))

def run(*a):
    return subprocess.run(a, capture_output=True, text=True, timeout=60)

def note(m):
    with open(CSV, 'a') as f:
        f.write(f'# {int(time.time())} {time.strftime("%F %T")} {m}\n')
    print(m, flush=True)

def auto_and_exit(why):
    run('ipmitool', 'raw', '0x30', '0x30', '0x01', '0x01')
    note(f'{why}: iDRAC auto, exiting'); load(0); sys.exit(3)

def set_fans(p):
    a = run('ipmitool', 'raw', '0x30', '0x30', '0x01', '0x00')
    b = run('ipmitool', 'raw', '0x30', '0x30', '0x02', '0xff', f'0x{p:02x}')
    if a.returncode or b.returncode:
        auto_and_exit(f'fan command failed ({a.stderr.strip()} {b.stderr.strip()})')

stress = None
def load(n):
    global stress
    if stress and stress.poll() is None:
        stress.terminate()
        try:
            stress.wait(15)
        except subprocess.TimeoutExpired:
            stress.kill()
    stress = None
    if n:
        stress = subprocess.Popen(['stress-ng', '--cpu', str(n), '--cpu-method', 'matrixprod', '--quiet'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def room():
    try:
        t, v = open('/run/room-inlet').read().split()
        return int(v) if time.time() - int(t) < 180 else None
    except (OSError, ValueError):
        return None

def dimm():
    try:   # dimm-log.service: time,?,max,avg,per-DIMM (one line per minute)
        last = open('/var/tmp/dimm-log.csv').read().splitlines()[-1].split(',')
        return int(last[2])
    except (OSError, ValueError, IndexError):
        return None

def energy():
    return sum(int(open(f'{z}/energy_uj').read()) for z in ZONES)

def sample(retry=True):
    t = run('ipmitool', 'sdr', 'type', 'Temperature').stdout
    cpus = [int(x) for x in re.findall(r'^Temp\s+\|[^|]+\|[^|]+\|[^|]+\|\s*(\d+) degrees', t, re.M)]
    inl = re.search(r'Inlet Temp\s+\|[^|]+\|[^|]+\|[^|]+\|\s*(\d+)', t)
    exh = re.search(r'Exhaust Temp\s+\|[^|]+\|[^|]+\|[^|]+\|\s*(\d+)', t)
    f = [int(x) for x in re.findall(r'(\d+) RPM', run('ipmitool', 'sdr', 'type', 'Fan').stdout)]
    w = re.search(r'Instantaneous power reading:\s+(\d+)', run('ipmitool', 'dcmi', 'power', 'reading').stdout)
    if len(cpus) < 2 or not inl or not exh:
        if retry:
            time.sleep(3)
            return sample(False)
        auto_and_exit('sensor read failed')
    return {'cpu0': cpus[0], 'cpu1': cpus[1], 'cpu': max(cpus), 'inlet': int(inl.group(1)), 'exh': int(exh.group(1)),
            'rpm': round(sum(f) / len(f)) if f else '', 'w': int(w.group(1)) if w else ''}

cols = ['epoch', 'time', 'phase', 'phase_min', 'fan_pct', 'workers', 'pkg_w', 'cpu0', 'cpu1', 'exh', 'inlet', 'dimm', 'rpm',
        'w', 'room']
try:
    open(CSV)
except OSError:
    open(CSV, 'w').write(','.join(cols) + '\n')
note('start')
run('systemctl', 'stop', 'fan-watchdog')
note('fan-watchdog stopped')
try:
    for label, pct, n, mins in PLAN:
        set_fans(pct)
        r = room()
        load(n if (r is not None and r <= 26) else 0)
        note(f'phase {label}: fans {pct}%, {n} workers, {mins} min, room {r}C' + ('' if n == 0 or (r is not None and r <= 26) else ' (load held: room)'))
        t0 = tp = time.time(); e0 = energy(); fan = pct
        while time.time() - t0 < mins * 60:
            time.sleep(15)
            v = sample(); d = dimm(); r = room()
            e1, tn = energy(), time.time()
            pw = (e1 - e0) / 1e6 / (tn - tp) if e1 >= e0 else None
            e0, tp = e1, tn
            cur = n if stress and stress.poll() is None else 0
            row = dict(v, epoch=int(tn), time=time.strftime('%T'), phase=label, phase_min=f'{(tn - t0) / 60:.1f}', fan_pct=fan,
                       workers=cur, pkg_w=f'{pw:.0f}' if pw else '', dimm=d, room=r)
            with open(CSV, 'a') as f:
                f.write(','.join('' if row.get(c) is None else str(row.get(c)) for c in cols) + '\n')
            if v['cpu'] >= 92:
                auto_and_exit(f'CPU {v["cpu"]}C')
            if v['cpu'] >= 85 and cur:
                load(0); note(f'{label}: CPU {v["cpu"]}C -> load off (night: no fan boost)')
            if v['cpu'] >= 88 and fan < NIGHT_MAX:
                fan = NIGHT_MAX; set_fans(fan); load(0); note(f'{label}: CPU {v["cpu"]}C -> fans {NIGHT_MAX}%, load off')
            reasons = [x for x, bad in (('exhaust', v['exh'] >= 60), ('dimm', d is not None and d >= 75),
                                        ('room', r is None or r > 27)) if bad]
            if cur and reasons:
                load(0); note(f'{label}: load off ({", ".join(reasons)})')
    note('done')
finally:
    load(0)
