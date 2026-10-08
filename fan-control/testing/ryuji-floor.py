#!/usr/bin/env python3
# ryuji-floor (2026-10-08): ryuji-profile with plan 'floor': BMC offsets BELOW -80 (the BMC page accepts -1..-127 for
# decreasing) at idle, 4 busy threads and full load, against -80, plus -16 and 0 at idle for the noise table. Goal:
# quieter CPU fans under light load without the new CPUs. Extra safety for the low offsets: every fan (CPU0/1_FAN,
# SYS_FAN1-4; BMC thresholds 800 warning / 600 critical) must stay at FAN_FLOOR rpm or more: the first 60 s after an
# offset change are watched every 5 s, then every 30 s; below the floor the offset goes straight back to -80 and every
# later phase below -80 is skipped. -127 is skipped if -80 and -100 at idle project a fan under the floor there.
# The BMC event log is read before and after (read-only) and new entries are noted. Room gates 26/27C (Rohit 10-07).
# ryuji-profile: thermal profile of ryuji vs BMC fan offset and CPU load. Reusable: rerun after the CPU upgrade
# with a new label and compare (analyze with scripts/analyze_ryuji_profile.py; room temp comes from makoto's
# data/room.csv, joined on the epoch column).
#   Guard stopped; for each BMC fan offset in OFFS: idle, then busy threads (stress-ng matrixprod at 100%) per LOADS;
#   then -80 idle as a drift bracket, then ryuji-fan-guard takes over again. Load steps are gated on the room (ROOM_*).
#   (07:19 and 07:30 runs on 2026-10-06 used guard / -61 / -31 / Performance blocks; replaced after the guard tripped
#   to Performance at the first load step, see STATUS-LOG.)
# Safety: load stops for the rest of a phase at SIO1 >= 80, CPU >= 82, VR >= 95, DIMM >= 80. At SIO1 >= 83 or
# CPU >= 86 the test sets Full Speed (127) and exits; the guard then holds Full until things cool. Any BMC set
# failure exits (no retries). ExecStopPost (ryuji-profile-restore.sh) kills any load and starts ryuji-fan-guard,
# which puts -80 back by itself from any non-guard offset on its first check.
# Run as root on ryuji:
#   systemd-run --unit=ryuji-profile -p ExecStopPost=/var/tmp/ryuji-profile-restore.sh python3 /var/tmp/ryuji-profile.py <label> [plan]
import glob, os, re, subprocess, sys, time

LABEL = sys.argv[1] if len(sys.argv) > 1 else 'run'
CSV = f'/var/tmp/ryuji-profile-{LABEL}.csv'
OFFSET_TOOL = ['python3', '/var/tmp/gbt-fan-offset.py', '10.0.0.118']
ENV = dict(os.environ, BMC_PWFILE='/root/.bmc-pass', BMC_USER='root')
G = None  # guard in control
# Load = number of stress-ng workers at 100% (threads busy; ryuji has 40). A few busy threads is the realistic light
# load (a small VM); duty-cycling all 40 threads keeps every core awake (40 x 10% already draws ~80 W package).
# Offsets: the BMC adds this PWM offset to its own fan curves (UI range -127..127; presets Full 127, Performance 0,
# Balance -31, Energy Saving -61). Measured: -80..-31 leave the system fans at their ~1,050 rpm floor and only move
# the CPU fans; 0 gives 4,000-5,000 rpm system fans. SIO Temp 1 follows system-fan airflow within minutes.
# This sweep maps the in-between offsets (system fans between floor and Performance), loudest first.
# Plans (pick with the 2nd argument; default "full"). Load = busy threads at 100%; FULL = one per physical core (20 on
# 2x E5-2650 v3; 44 after the E5-2696 v4 upgrade). Hyperthreads add nothing with matrixprod (measured 10-06).
#   full:     every offset (loudest first) x idle 10 min / 4 threads 6 min / FULL 6 min, then -80 idle bracket.
#   rest0806: what was left on 10-06 after sweeps 1-2 (offset 0 all loads and -24 idle/4 done earlier).
# 10-06 history: sweep 1 (07:45) cut at 08:11 by the room rule (27C then); sweep 2 (08:25) light loads only;
# 08:4x Rohit allowed a hotter room ("test harder ... leave time for it to cool off"), so full-load steps are back.
FULL = len({tuple(l.split(',')) for l in subprocess.run(['lscpu', '-p=CORE,SOCKET'], capture_output=True, text=True)
            .stdout.splitlines() if not l.startswith('#')}) or 20   # physical cores
STEPS = [(0, 10), (4, 6), (FULL, 6)]
LOW = 'LOW'   # resolved at run time: the lowest offset (-127, then -100) that has not hit the fan floor
PLANS = {
    'floor': [('o-80_0t', -80, 0, 8), ('o-100_0t', -100, 0, 10), ('o-127_0t', -127, 0, 10), ('o-80_0t_b', -80, 0, 6),
              ('o-80_4t', -80, 4, 6), ('o-100_4t', -100, 4, 6), ('o-127_4t', -127, 4, 6), ('o-80_4t_b', -80, 4, 4),
              ('oLOW_full', LOW, FULL, 6), ('o-80_full', -80, FULL, 6),
              ('o-16_0t', -16, 0, 6), ('o0_0t', 0, 0, 6), ('R80_idle', -80, 0, 8)],
    # 2026-10-07 19:30, Rohit winding down for bed: idle and 4 threads only (no full load, no -16/0), quietest first,
    # under noise-guard-ryuji (+3 dB(A) at the mic -> load killed, then the test stopped)
    'night': [('o-80_0t', -80, 0, 6), ('o-100_0t', -100, 0, 10), ('o-127_0t', -127, 0, 10), ('o-80_0t_b', -80, 0, 6),
              ('o-127_4t', -127, 4, 6), ('o-100_4t', -100, 4, 6), ('o-80_4t', -80, 4, 4), ('R80_idle', -80, 0, 8)],
    # 2026-10-08 daytime (the idle offsets were measured the evening before): the loads, -80 brackets, -16 and 0 idle
    'day': [('o-80_0t', -80, 0, 5), ('o-80_4t', -80, 4, 6), ('o-100_4t', -100, 4, 6), ('o-127_4t', -127, 4, 6),
            ('o-80_4t_b', -80, 4, 4), ('o-80_0t_c', -80, 0, 4), ('oLOW_full', LOW, FULL, 6), ('o-80_full', -80, FULL, 6),
            ('o-16_0t', -16, 0, 6), ('o0_0t', 0, 0, 6), ('R80_idle', -80, 0, 8)],
    # 2026-10-08 12:0x: -100 vs -80 under 4 threads again, alternating (A/B/A/B) with the idle right after each load
    # (the day plan: -100 ~0.3 dB quieter but without the ~700 Hz tone; the post-load idle at 2,600 rpm rang it)
    'ab': [('a1_4t', -80, 4, 5), ('a1_idle', -80, 0, 4), ('b1_4t', -100, 4, 5), ('b1_idle', -100, 0, 4),
           ('a2_4t', -80, 4, 5), ('a2_idle', -80, 0, 4), ('b2_4t', -100, 4, 5), ('b2_idle', -100, 0, 4),
           ('R80_idle', -80, 0, 6)],
    # guard in control (offset None): its live validation under light and full load, and the unwind afterwards
    'guardval': [('g_idle', None, 0, 5), ('g_4t', None, 4, 10), ('g_full', None, FULL, 10), ('g_unwind', None, 0, 20)],
    'full': [(f'o{o}_{w}t', o, w, m) for o in (0, -8, -16, -24, -80) for w, m in STEPS] + [('R80_idle', -80, 0, 8)],
    'rest0806': ([(f'o{o}_{w}t', o, w, m) for o in (-16, -8) for w, m in STEPS]
                 + [(f'o-24_{FULL}t', -24, FULL, 6)]
                 + [(f'o-80_{w}t', -80, w, m) for w, m in ((0, 8), (4, 6), (FULL, 6))]
                 + [('R80_idle', -80, 0, 8)]),
}
PLAN = PLANS[sys.argv[2] if len(sys.argv) > 2 else 'floor']
# Room gating. makoto's lab-inlet-guard writes "<epoch> <mementos inlet>" to ROOM_FILE every minute. A load step
# starts only at <= ROOM_START (waits up to WAIT_MAX, else it is skipped) and its load is dropped above ROOM_STOP or
# if the reading is more than 3 min old. 10-06: Rohit's 27C rule until 08:4x, then up to 29C allowed.
ROOM_FILE, ROOM_START, ROOM_STOP, WAIT_MAX = '/run/room-inlet', 26, 27, 25 * 60
FAN_FLOOR = 1000
floor_hit = set()   # offsets that took a fan under FAN_FLOOR
LOAD_STOP = {'sio1': 80, 'cpu': 82, 'vr': 95, 'dimm': 80}
ABORT = {'sio1': 83, 'cpu': 86}

def sh(*a, **k):
    return subprocess.run(a, capture_output=True, text=True, timeout=60, **k)

def note(msg):
    with open(CSV, 'a') as f:
        f.write(f'# {int(time.time())} {time.strftime("%F %T %Z")} {msg}\n')
    print(msg, flush=True)

def set_offset(o):
    r = sh(*OFFSET_TOOL, 'set', str(o), env=ENV)
    got = re.search(r'now (-?\d+)', r.stdout)
    if r.returncode != 0 or not got or int(got.group(1)) != o:
        note(f'BMC set {o} failed (rc {r.returncode}: {r.stdout.strip()} {r.stderr.strip()[-200:]}); stopping')
        sys.exit(2)
    note(f'BMC offset set to {o}')

HDDS = [l.split()[0] for l in sh('lsblk', '-dno', 'NAME,ROTA,TYPE').stdout.splitlines()
        if l.split()[1:] == ['1', 'disk']]

def hdd_max():
    m = None
    for d in HDDS:
        o = sh('smartctl', '-n', 'standby', '-A', f'/dev/{d}').stdout
        x = re.search(r'^194 Temperature_Celsius(?:\s+\S+){7}\s+(\d+)', o, re.M)
        if x:
            m = max(m or 0, int(x.group(1)))
    return m

def sensors():
    t = {}
    for typ in ('Temperature', 'Fan'):
        for line in sh('ipmitool', 'sdr', 'type', typ).stdout.splitlines():
            f = [x.strip() for x in line.split('|')]
            m = re.match(r'(\d+) (degrees|RPM)', f[4]) if len(f) >= 5 else None
            if m:
                t[f[0]] = int(m.group(1))
    w = re.search(r'Instantaneous power reading:\s+(\d+)', sh('ipmitool', 'dcmi', 'power', 'reading').stdout)
    sysf = [v for k, v in t.items() if k.startswith('SYS_FAN')]
    fans = [v for k, v in t.items() if k.endswith('_FAN') or k.startswith('SYS_FAN')]
    return {
        'fan_min': min(fans) if fans else None,
        'cpu0': t.get('CPU0_TEMP'), 'cpu1': t.get('CPU1_TEMP'), 'sio1': t.get('SIO Temp 1'), 'sio2': t.get('SIO Temp 2'),
        'pch': t.get('PCH_TEMP'), 'vr': max((v for k, v in t.items() if k.startswith('VR_')), default=None),
        'dimm': max((v for k, v in t.items() if k.startswith('DIMM_')), default=None),
        'cpu_fan0': t.get('CPU0_FAN'), 'cpu_fan1': t.get('CPU1_FAN'),
        'sys_fan': round(sum(sysf) / len(sysf)) if sysf else None,
        'dcmi_w': int(w.group(1)) if w else None,
    }

ZONES = sorted(glob.glob('/sys/class/powercap/intel-rapl:[01]'))
def energy():
    return [int(open(f'{z}/energy_uj').read()) for z in ZONES]

stress = None
def load(pct):
    global stress
    if stress and stress.poll() is None:
        stress.terminate()
        try:
            stress.wait(15)
        except subprocess.TimeoutExpired:
            stress.kill()
    stress = None
    if pct:
        stress = subprocess.Popen(['nice', '-n', '10', 'stress-ng', '--cpu', str(pct), '--cpu-method', 'matrixprod',
                                   '--quiet'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def guard(on):
    sh('systemctl', 'start' if on else 'stop', 'ryuji-fan-guard')
    note(f'ryuji-fan-guard {"started" if on else "stopped"}')

def guard_offset():
    try:
        return re.search(r'"offset": (-?\d+)', open('/run/ryuji-fan-guard.state').read()).group(1)
    except (OSError, AttributeError):
        return ''

def room():
    try:
        t, v = open(ROOM_FILE).read().split()
        return int(v) if time.time() - int(t) < 180 else None
    except (OSError, ValueError):
        return None

cols = ['epoch', 'time_utc', 'phase', 'phase_min', 'offset', 'load', 'cpu0', 'cpu1', 'sio1', 'sio2', 'pch', 'vr', 'dimm',
        'hdd', 'cpu_fan0', 'cpu_fan1', 'sys_fan', 'fan_min', 'dcmi_w', 'pkg0_w', 'pkg1_w', 'room']

def fan_min_now():
    vals = []
    for line in sh('ipmitool', 'sdr', 'type', 'Fan').stdout.splitlines():
        f = [x.strip() for x in line.split('|')]
        m = re.match(r'(\d+) RPM', f[4]) if len(f) >= 5 else None
        if m:
            vals.append(int(m.group(1)))
    return min(vals) if vals else None

def floor_check(off, label):
    """True if the fans are fine at this offset; else back to -80 at once and mark the offset."""
    global current
    if off is None or off >= -80:
        return True
    fm = fan_min_now()
    if fm is not None and fm < FAN_FLOOR:
        set_offset(-80); current = -80
        floor_hit.add(off)
        note(f'{label}: a fan read {fm} rpm (< {FAN_FLOOR}) at offset {off}: back to -80; offsets <= {off} skipped')
        return False
    return True

def sel_count():
    m = re.search(r'Entries\s*:\s*(\d+)', sh('ipmitool', 'sel', 'info').stdout)
    return int(m.group(1)) if m else None
if not os.path.exists(CSV):
    with open(CSV, 'w') as f:
        f.write(','.join(cols) + '\n')

def log_row(label, off, t0, st, workers):
    """one sample: log it, apply the safety limits. st carries the energy counter between samples."""
    s = sensors()
    s['hdd'] = hdd_max()
    e1, tn = energy(), time.time()
    pw = [f'{(b - a) / 1e6 / (tn - st["tp"]):.1f}' if b >= a else '' for a, b in zip(st['e0'], e1)]
    st['e0'], st['tp'] = e1, tn
    cur = workers if stress and stress.poll() is None else 0
    row = dict(s, epoch=int(tn), time_utc=time.strftime('%T'), phase=label, phase_min=f'{(tn - t0) / 60:.1f}',
               offset=f'g{guard_offset()}' if off is None else off, load=cur,
               pkg0_w=pw[0] if pw else '', pkg1_w=pw[1] if len(pw) > 1 else '', room=room())
    with open(CSV, 'a') as f:
        f.write(','.join('' if row.get(c) is None else str(row.get(c)) for c in cols) + '\n')
    if s['sio1'] is None or s['cpu0'] is None:
        note('sensor read failed; stopping'); sys.exit(3)
    vals = dict(s, cpu=max(s['cpu0'] or 0, s['cpu1'] or 0))
    hot = [f'{k}={vals[k]}' for k, lim in ABORT.items() if vals[k] is not None and vals[k] >= lim]
    if hot:
        load(0)
        if guard_on:
            note(f'ABORT at {", ".join(hot)} (guard in control)')
        else:
            note(f'ABORT at {", ".join(hot)}: setting Full Speed'); set_offset(127)
        sys.exit(4)
    warm = [f'{k}={vals[k]}' for k, lim in LOAD_STOP.items() if vals[k] is not None and vals[k] >= lim]
    if warm and cur:
        load(0)
        note(f'{label}: load stopped ({", ".join(warm)})')
    r = row['room']
    if cur and (r is None or r > ROOM_STOP):
        load(0)
        note(f'{label}: load stopped (room {r}C)')

note(f'start {LABEL}; HDDs {HDDS}')
sel0 = sel_count()
note(f'BMC SEL entries at start: {sel0}')
fan_idle = {}   # offset -> median idle fan_min
guard_on = sh('systemctl', 'is-active', 'ryuji-fan-guard').stdout.strip() == 'active'
current = None   # offset this script last set (one BMC login per change, not per phase)
try:
    for label, off, pct, mins in PLAN:
        if off == LOW:
            off = next((o for o in (-127, -100) if o not in floor_hit and not any(h >= o for h in floor_hit)), None)
            if off is None:
                note('oLOW_full: skipped (no offset below -80 passed; o-80_full follows)')
                continue
            label = f'o{off}_full'
        if off is not None and off < -80 and any(h >= off for h in floor_hit):
            note(f'{label}: skipped (offset {off} is at or below one that hit the fan floor)')
            continue
        if off == -127 and -100 in fan_idle and -80 in fan_idle:
            proj = fan_idle[-100] - (fan_idle[-80] - fan_idle[-100]) * 27 / 20
            if proj < FAN_FLOOR:
                note(f'{label}: skipped (idle fans {fan_idle[-80]} at -80, {fan_idle[-100]} at -100 project {proj:.0f} rpm at -127)')
                floor_hit.add(-127)
                continue
        if off is None and not guard_on:
            guard(True); guard_on = True; current = None
        if off is not None:
            if guard_on:
                guard(False); guard_on = False
            if off != current:
                set_offset(off); current = off
                ok = True
                for _ in range(12):   # watch the first 60 s closely below -80
                    if off >= -80:
                        break
                    time.sleep(5)
                    if not floor_check(off, label):
                        ok = False
                        break
                if not ok:
                    continue
        st = {'e0': energy(), 'tp': time.time()}
        if pct:
            r = room()
            if r is None or r > ROOM_START:
                note(f'{label}: room {r}C, waiting for <= {ROOM_START}C before adding load')
                tw = time.time()
                while (r is None or r > ROOM_START) and time.time() - tw < WAIT_MAX:
                    time.sleep(30)
                    log_row(label + '_wait', off, tw, st, 0)
                    r = room()
                if r is None or r > ROOM_START:
                    note(f'{label}: skipped (room {r}C after {WAIT_MAX // 60} min)')
                    continue
        load(pct)
        note(f'phase {label}: offset {"guard" if off is None else off}, {pct} busy threads, {mins} min, room {room()}C')
        t0 = time.time()
        fm_samples = []
        while time.time() - t0 < mins * 60:
            time.sleep(30)
            log_row(label, off, t0, st, pct)
            if not floor_check(off, label):
                break
            fmv = fan_min_now()
            if fmv is not None and time.time() - t0 > (mins - 4) * 60:
                fm_samples.append(fmv)
        if pct == 0 and off is not None and fm_samples and label.startswith(f'o{off}_0t'):
            fan_idle[off] = sorted(fm_samples)[len(fm_samples) // 2]
            note(f'{label}: idle fan_min median {fan_idle[off]} rpm')
    if current is not None and current != -80:
        set_offset(-80); current = -80
    if not guard_on:
        guard(True)
    sel1 = sel_count()
    note(f'BMC SEL entries at end: {sel1} (start {sel0})')
    if sel0 is not None and sel1 is not None and sel1 > sel0:
        new = sh('ipmitool', 'sel', 'list').stdout.strip().splitlines()[-(sel1 - sel0):]
        note('new SEL entries: ' + ' || '.join(new))
    note('done')
finally:
    load(0)
