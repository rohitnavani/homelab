#!/usr/bin/env python3
# mementos-steps (2026-10-06): R720 full CPU load with RAPL package power caps, under the production fan-watchdog,
# to choose fan-watchdog v4 ("medium" fans under heavy work instead of iDRAC auto). Uncapped full load is already
# known (10-05/06: CPUs 84-85C within ~1 min at the 35% cap, then iDRAC auto), so it is not repeated.
# Usage: mementos-steps.py <plan> [cap W for plan v4]   plans in PLANS. CSV /var/tmp/mementos-steps.csv (every 20 s).
# Load = stress-ng matrixprod on N workers at 100% (48 = every thread). Steps are 8 min (CPU temps and the fan curve
# settle within ~2-3 min, DIMMs/exhaust within ~5-8).
# Room gating (Rohit: stop tests above 27C): makoto's lab-inlet-guard writes "<epoch> <inlet>" to /run/room-inlet
# every minute; a load step starts only at <= ROOM_START (waits up to WAIT_MAX, else skipped) and its load is
# dropped above ROOM_STOP or when the reading is more than 3 min old.
# Safety: load stops for the rest of a step at CPU >= 89 (84 before v4), DIMM >= 75, exhaust >= 60, or if fan-watchdog went to iDRAC
# auto. ExecStopPost (mementos-steps-restore.sh) kills stress-ng and restores RAPL PL1 130 W / PL2 156 W per socket.
# Run: systemd-run --unit=mementos-steps -p ExecStopPost=/var/tmp/mementos-steps-restore.sh python3 /var/tmp/mementos-steps.py caps
import glob, re, subprocess, sys, time

PLANS = {  # label, workers (0 = idle), RAPL PL1 cap per socket in W (None = stock 130), minutes
    'caps': [('idle', 0, None, 4), ('c100', 48, 100, 8), ('cool1', 0, None, 5), ('c90', 48, 90, 8),
             ('cool2', 0, None, 5), ('c80', 48, 80, 8), ('cool3', 0, None, 6)],
    'v4': [('idle', 0, None, 4), ('full', 48, 'arg', 8), ('cool', 0, None, 8)],
    # 10-06 11:xx Rohit: no power caps; full load may be loud, high-but-not-full load must be medium. Workers = busy
    # physical cores' worth (24 cores / 48 threads): 12 = half, 18 = three quarters, 24 = all cores.
    'steps2': [('idle', 0, None, 4), ('w12', 12, None, 8), ('cool1', 0, None, 4), ('w18', 18, None, 8), ('cool2', 0, None, 6)],
    # v4 live validation: medium loads, then a full load started straight from idle (the case that used to hit 85C
    # before the 30 s fan loop caught up and flip to iDRAC auto), then the unwind.
    'v4val': [('idle', 0, None, 4), ('w12', 12, None, 8), ('w18', 18, None, 8), ('cool1', 0, None, 8),
              ('w48_onset', 48, None, 8), ('cool2', 0, None, 10)],
    'v41val': [('idle', 0, None, 3), ('w18', 18, None, 8), ('w48', 48, None, 7), ('cool', 0, None, 8)],
    # 2026-10-08, steady room: a light load too, and a 20 min unwind so the last step back to 10% is seen.
    'v42val': [('idle', 0, None, 4), ('w6', 6, None, 8), ('w12', 12, None, 8), ('w18', 18, None, 8),
               ('cool1', 0, None, 8), ('w48_onset', 48, None, 8), ('cool2', 0, None, 20)],
}
CSV = '/var/tmp/mementos-steps.csv'
STOP = {'cpu': 89, 'dimm': 75, 'exh': 60}   # 89: just under fan-watchdog v4's iDRAC-auto point (90); iDRAC warns at 94
ROOM_FILE, ROOM_START, ROOM_STOP, WAIT_MAX = '/run/room-inlet', 26, 27, 25 * 60   # 2026-10-08: test heat off above 27C (Rohit)
ZONES = sorted(glob.glob('/sys/class/powercap/intel-rapl:[01]'))

def run(*a):
    return subprocess.run(a, capture_output=True, text=True, timeout=60).stdout

def note(m):
    with open(CSV, 'a') as f:
        f.write(f'# {int(time.time())} {time.strftime("%F %T")} {m}\n')
    print(m, flush=True)

def cap(w):
    for z in ZONES:
        open(f'{z}/constraint_0_power_limit_uw', 'w').write(str(int((w or 130) * 1e6)))
        open(f'{z}/constraint_1_power_limit_uw', 'w').write(str(int((w * 1.2 if w else 156) * 1e6)))
    got = [int(open(f'{z}/constraint_0_power_limit_uw').read()) // 10**6 for z in ZONES]
    note(f'RAPL PL1 now {got} W')

def energy():
    return sum(int(open(f'{z}/energy_uj').read()) for z in ZONES)

def room():
    try:
        t, v = open(ROOM_FILE).read().split()
        return int(v) if time.time() - int(t) < 180 else None
    except (OSError, ValueError):
        return None

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

def sample():
    st = open('/run/fan-watchdog.state').read()
    v = {k: int(x) for k, x in re.findall(r'(cpu|exh|inlet|hdd|ssd|dimm)=(\d+)', st)}
    m = re.search(r'(\d+)%', st)
    v['pct'] = int(m.group(1)) if m else ''
    v['mode'] = 'auto' if 'auto' in st else 'curve'
    t = run('ipmitool', 'sdr', 'type', 'Temperature')
    cpus = [int(x) for x in re.findall(r'^Temp\s+\|[^|]+\|[^|]+\|[^|]+\|\s*(\d+) degrees', t, re.M)]
    v['cpu0'], v['cpu1'] = (cpus + ['', ''])[:2]
    f = [int(x) for x in re.findall(r'(\d+) RPM', run('ipmitool', 'sdr', 'type', 'Fan'))]
    v['rpm'] = round(sum(f) / len(f)) if f else ''
    w = re.search(r'Instantaneous power reading:\s+(\d+)', run('ipmitool', 'dcmi', 'power', 'reading'))
    v['w'] = int(w.group(1)) if w else ''
    return v

cols = ['epoch', 'time', 'phase', 'phase_min', 'load', 'cap', 'pkg_w', 'cpu0', 'cpu1', 'cpu', 'dimm', 'exh', 'inlet', 'hdd',
        'ssd', 'pct', 'mode', 'rpm', 'w', 'room']

def log_row(label, t0, st, n, w):
    v = sample()
    e1, tn = energy(), time.time()
    v['pkg_w'] = f'{(e1 - st["e0"]) / 1e6 / (tn - st["tp"]):.0f}' if e1 >= st['e0'] else ''
    st['e0'], st['tp'] = e1, tn
    cur = n if stress and stress.poll() is None else 0
    row = dict(v, epoch=int(tn), time=time.strftime('%T'), phase=label, phase_min=f'{(tn - t0) / 60:.1f}', load=cur,
               cap=w or 130, room=room())
    with open(CSV, 'a') as f:
        f.write(','.join('' if row.get(c) is None else str(row.get(c)) for c in cols) + '\n')
    hot = [f'{k}={v[k]}' for k, lim in STOP.items() if isinstance(v.get(k), int) and v[k] >= lim]
    if cur and (hot or v['mode'] == 'auto'):
        load(0)
        note(f'{label}: load stopped ({", ".join(hot) or "fan-watchdog in iDRAC auto"})')
    if cur and (row['room'] is None or row['room'] > ROOM_STOP):
        load(0)
        note(f'{label}: load stopped (room {row["room"]}C)')

plan = sys.argv[1]
argcap = int(sys.argv[2]) if len(sys.argv) > 2 else None
try:
    open(CSV)
except OSError:
    open(CSV, 'w').write(','.join(cols) + '\n')
note(f'start plan {plan}')
try:
    for label, n, w, mins in PLANS[plan]:
        w = argcap if w == 'arg' else w
        st = {'e0': energy(), 'tp': time.time()}
        if n:
            r = room()
            if r is None or r > ROOM_START:
                note(f'{label}: room {r}C, waiting for <= {ROOM_START}C before adding load')
                tw = time.time()
                while (r is None or r > ROOM_START) and time.time() - tw < WAIT_MAX:
                    time.sleep(20)
                    log_row(label + '_wait', tw, st, 0, None)
                    r = room()
                if r is None or r > ROOM_START:
                    note(f'{label}: skipped (room {r}C after {WAIT_MAX // 60} min)')
                    continue
        cap(w)
        load(n)
        note(f'phase {label}: {n} workers, cap {w or 130} W, {mins} min, room {room()}C')
        t0 = time.time()
        while time.time() - t0 < mins * 60:
            time.sleep(20)
            log_row(label, t0, st, n, w)
    note('done')
finally:
    load(0)
    cap(None)
