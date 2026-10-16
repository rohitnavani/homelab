#!/usr/bin/env python3
# mementos-steps (2026-10-06; 2026-10-13 rework for the final rack run): CPU load steps on mementos's R720xd under the
# production fan-watchdog, to see which fan level each load gets and what it costs in temperature and noise.
# Usage: mementos-steps.py <plan> [label]   plans in PLANS; CSV /var/tmp/mementos-steps-<label>.csv (20 s, 10 s in
# bursts). Load = stress-ng matrixprod on N workers at 100% (24 = every core, 48 = every thread).
# 2026-10-13 changes:
# - No IPMI reads at all while fan-watchdog runs: fan-watchdog's own iDRAC reads must never fail (a failed read sends
#   the R720 to loud iDRAC auto), and a second in-band reader can make one fail. Temperatures and the fan % come from
#   fan-watchdog's state file, each CPU package from coretemp, package power from RAPL (read only), throttling from the
#   kernel's thermal_throttle counters. No wall power here (the rack PDU in Prometheus has it).
# - No RAPL writes (Rohit: no power caps; the old 'caps' and 'v4' plans are gone).
# - Room gate on fan-watchdog's inlet (the room reference); a state file older than 120 s counts as no reading.
# - LOAD_UNTIL (epoch, env): no load step starts after it (the phase runs idle instead).
# - Stops: load off for the rest of a phase at CPU 89 (fan-watchdog v4.2 goes to iDRAC auto at 90), DIMM 75, exhaust 60,
#   HDD 50 (fan-watchdog's emergency is 52), SSD 60, iDRAC auto, room above ROOM_STOP or no room reading.
# Run: systemd-run --unit=mementos-steps-<x> -p ExecStopPost=/var/tmp/mementos-steps-restore.sh \
#      python3 /var/tmp/mementos-steps.py <plan> <label>
import glob, os, re, subprocess, sys, time


def seq(steps):
    """a designed burst sequence [(workers, minutes)] as phases (hunting check)"""
    return [(f'b{i:02d}_{w}w', w, mins) for i, (w, mins) in enumerate(steps)]


# 30 min each, the same shape as ryuji's (its 2/4/11/22/33/44 workers -> 6/6/18/24/36/48 here)
BURST_MED = [(18, 2), (0, 1.5), (6, 3), (18, 1), (0, 0.5), (12, 4), (18, 5), (0, 2), (6, 1.5), (12, 3), (0, 3), (6, 1.5),
             (18, 2)]
BURST_ALL = [(48, 1.5), (0, 2), (24, 3), (6, 2), (36, 1), (0, 1), (48, 4), (12, 2), (0, 3), (36, 2), (6, 1.5),
             (48, 0.5), (0, 1.5), (24, 5)]


PLANS = {  # label, workers (0 = idle), minutes
    'v42val': [('idle', 0, 4), ('w6', 6, 8), ('w12', 12, 8), ('w18', 18, 8), ('cool1', 0, 8), ('w48_onset', 48, 8),
               ('cool2', 0, 20)],
    # final rack run (2026-10-14/16): 20 min holds (the R720's CPUs and fans settle in 2-3 min, DIMMs and exhaust in
    # 5-8; 20 min also covers the mic's A/B comparisons), long unwinds so the last step back to 10% is seen.
    'fin_steps': [('idle', 0, 10), ('w6', 6, 20), ('w12', 12, 20), ('w18', 18, 20), ('w24', 24, 20), ('cool', 0, 25)],
    'fin_mixed': [('x_ref', 0, 10), ('x_12w', 12, 45), ('x_unwind', 0, 20)],
    'fin_burstm': [('bm_ref', 0, 5)] + seq(BURST_MED) + [('bm_unwind', 0, 20)],
    'fin_high': [('idle', 0, 5), ('w36', 36, 20), ('w48', 48, 20), ('cool1', 0, 15), ('w48_onset', 48, 15),
                 ('cool2', 0, 15)],
    # combined full tilt (Thursday): ryuji runs 44 workers from T0; mementos idle 20 min (step 1, ~10 A), 24 workers 20
    # min (step 2, ~11.5 A), 48 workers 60 min with every drive soak running (step 3, ~12.5-13 A), then the unwind.
    'fin_comb': [('c_ref', 0, 20), ('c_24w', 24, 20), ('c_48w', 48, 60), ('c_unwind', 0, 25)],
    'fin_val': [('idle', 0, 5), ('w6', 6, 15), ('w12', 12, 15), ('w18', 18, 15), ('w24', 24, 15), ('w36', 36, 15),
                ('w48', 48, 20), ('cool1', 0, 20), ('w48_onset', 48, 10), ('cool2', 0, 20)],
    'fin_burst': [('b_ref', 0, 5)] + seq(BURST_ALL) + [('b_unwind', 0, 20)],
    'fin_soak': [('s_ref', 0, 5), ('s_36w', 36, 120), ('s_unwind', 0, 25)],
    'dry': [('d_idle', 0, 1), ('d_1w', 1, 1), ('d_cool', 0, 1)],
}
LABEL = sys.argv[2] if len(sys.argv) > 2 else sys.argv[1]
CSV = f'/var/tmp/mementos-steps-{LABEL}.csv'
STATE = '/run/fan-watchdog.state'
STOP = {'cpu': 89, 'dimm': 75, 'exh': 60, 'hdd': 50, 'ssd': 60}
ROOM_START, ROOM_STOP, WAIT_MAX = 26, 27, 25 * 60   # 2026-10-08: test heat off above 27C (Rohit)
LOAD_UNTIL = float(os.environ.get('LOAD_UNTIL', 'inf'))
ZONES = sorted(glob.glob('/sys/class/powercap/intel-rapl:[01]'))
PKGT = {}
for h in glob.glob('/sys/class/hwmon/hwmon*'):
    try:
        if open(f'{h}/name').read().strip() == 'coretemp':
            m = re.match(r'Package id (\d+)', open(f'{h}/temp1_label').read())
            if m:
                PKGT[int(m.group(1))] = f'{h}/temp1_input'
    except OSError:
        pass


def note(m):
    with open(CSV, 'a') as f:
        f.write(f'# {int(time.time())} {time.strftime("%F %T %Z")} {m}\n')
    print(m, flush=True)


def energy():
    return [int(open(f'{z}/energy_uj').read()) for z in ZONES]


def state():
    """fan-watchdog's state, or None if it is older than 120 s"""
    try:
        if time.time() - os.stat(STATE).st_mtime > 120:
            return None
        st = open(STATE).read()
    except OSError:
        return None
    v = {k: int(x) for k, x in re.findall(r'(cpu|exh|inlet|hdd|ssd|dimm)=(\d+)', st)}
    m = re.search(r'(\d+)%', st)
    v['pct'] = int(m.group(1)) if m else None
    v['mode'] = 'auto' if 'auto' in st.lower() else 'curve'
    return v


def room():
    s = state()
    return s.get('inlet') if s else None


def throttles():
    core = pkg = 0
    seen = set()
    for d in glob.glob('/sys/devices/system/cpu/cpu[0-9]*'):
        try:
            core += int(open(f'{d}/thermal_throttle/core_throttle_count').read())
            p = open(f'{d}/topology/physical_package_id').read().strip()
            if p not in seen:
                seen.add(p)
                pkg += int(open(f'{d}/thermal_throttle/package_throttle_count').read())
        except (OSError, ValueError):
            pass
    return core, pkg


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


cols = ['epoch', 'time', 'phase', 'phase_min', 'load', 'pkg0_w', 'pkg1_w', 'pkg0_t', 'pkg1_t', 'cpu', 'dimm', 'exh',
        'inlet', 'hdd', 'ssd', 'pct', 'mode', 'thr_core', 'thr_pkg', 'room']


def log_row(label, t0, st, n):
    v = state() or {}
    e1, tn = energy(), time.time()
    pw = [f'{(b - a) / 1e6 / (tn - st["tp"]):.1f}' if b >= a else '' for a, b in zip(st['e0'], e1)]
    st['e0'], st['tp'] = e1, tn
    pt = {}
    for p, f in PKGT.items():
        try:
            pt[p] = int(open(f).read()) // 1000
        except (OSError, ValueError):
            pass
    tc, tpk = throttles()
    cur = n if stress and stress.poll() is None else 0
    row = dict(v, epoch=int(tn), time=time.strftime('%T'), phase=label, phase_min=f'{(tn - t0) / 60:.1f}', load=cur,
               pkg0_w=pw[0] if pw else '', pkg1_w=pw[1] if len(pw) > 1 else '', pkg0_t=pt.get(0), pkg1_t=pt.get(1),
               thr_core=tc, thr_pkg=tpk, room=v.get('inlet'))
    with open(CSV, 'a') as f:
        f.write(','.join('' if row.get(c) is None else str(row.get(c)) for c in cols) + '\n')
    if not cur:
        return
    hot = [f'{k}={v[k]}' for k, lim in STOP.items() if isinstance(v.get(k), int) and v[k] >= lim]
    hot += [f'pkg{p}={t}' for p, t in pt.items() if t >= STOP['cpu']]
    if not v:
        load(0)
        note(f'{label}: load stopped (fan-watchdog state missing or stale)')
    elif hot or v.get('mode') == 'auto':
        load(0)
        note(f'{label}: load stopped ({", ".join(hot) or "fan-watchdog in iDRAC auto"})')
    elif row['room'] is None or row['room'] > ROOM_STOP:
        load(0)
        note(f'{label}: load stopped (room {row["room"]}C)')


plan = sys.argv[1]
if not os.path.exists(CSV):
    with open(CSV, 'w') as f:
        f.write(','.join(cols) + '\n')
note(f'start plan {plan} ({sum(m for _, _, m in PLANS[plan]):.0f} min); coretemp packages {sorted(PKGT)}; '
     f'LOAD_UNTIL {time.strftime("%F %T", time.localtime(LOAD_UNTIL)) if LOAD_UNTIL != float("inf") else "none"}')
try:
    for label, n, mins in PLANS[plan]:
        st = {'e0': energy(), 'tp': time.time()}
        if n and time.time() > LOAD_UNTIL:
            note(f'{label}: past LOAD_UNTIL, running it idle')
            n = 0
        if n:
            r = room()
            if r is None or r > ROOM_START:
                note(f'{label}: room {r}C, waiting for <= {ROOM_START}C before adding load')
                tw = time.time()
                while (r is None or r > ROOM_START) and time.time() - tw < WAIT_MAX:
                    time.sleep(20)
                    log_row(label + '_wait', tw, st, 0)
                    r = room()
                if r is None or r > ROOM_START:
                    note(f'{label}: skipped (room {r}C after {WAIT_MAX // 60} min)')
                    continue
        load(n)
        note(f'phase {label}: {n} workers, {mins} min, room {room()}C')
        t0 = time.time()
        step = 10 if label.startswith('b') else 20
        while time.time() - t0 < mins * 60:
            time.sleep(min(step, max(1, mins * 60 - (time.time() - t0))))
            log_row(label, t0, st, n)
    note('done')
finally:
    load(0)
