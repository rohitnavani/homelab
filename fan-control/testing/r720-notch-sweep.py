#!/usr/bin/env python3
# r720-notch-sweep (2026-10-08): find the edges of the ~700 Hz resonance that makes the R720 at 40% louder than at
# 45% (noise sweep 10:30: +12.0 vs +9.7 dB(A); the fans' blade-pass tone, 5 x rpm/60, is ~693 Hz at 40%). R720 only,
# idle, fan-watchdog stopped: ref 10% 60 s, then each of R720_STEPS for 90 s with ref 10% 60 s after each, with the
# same documented Dell commands fan-watchdog uses. A CPU at 75C or more, a failed read or a failed command -> iDRAC
# auto and stop. fan-watchdog starts again at the end. Never touches the shelf. CSV /var/tmp/r720-notch.csv
# (epoch, time, phase, box, pct, shelf rpm, R720 rpm, CPU, inlet); analyze with analyze_mic_phases.py.
# Run as unit mic-r720-notch (the v3 alert rules stay quiet for mic-r720*); ExecStopPost starts fan-watchdog.
# 2026-10-20 (new-spot run, notes ~/lab-thermal-2026-10-20): plans by argument:
#   notch (default)  T1b: 10% anchor 3 min, 38..44% in 1% steps of 90 s, 10% anchor 3 min (16.5 min)
#   notch1015        the 2026-10-15 sweep (36..44%, 90 s, a 60 s 10% reference after each)
# - No SES read at all (md1200-fan runs the whole time; the shelf rpm column comes from its state file), iDRAC reads
#   and fan commands only after this unit stopped fan-watchdog and checked it is down (still running -> nothing sent).
# - CSV /var/tmp/r720-notch-<label>.csv (label = 2nd argument, default <plan>-<MMDD-HHMM>; the old fixed name collected
#   the 10-13 and 10-15 runs in one file) and the phase boundaries for the mic (epoch, phase, level, box) in
#   /var/tmp/r720-notch-<label>-phases.csv. Holds end on time.
#   systemd-run --unit=mic-r720-notch-<x> -p ExecStopPost=/var/tmp/r720-notch-restore.sh \
#     python3 -I /var/tmp/r720-notch-sweep-1020.py [notch [label]]
import json, os, re, subprocess, sys, time

MD_STATE, FW = '/run/md1200-fan.state', 'fan-watchdog'
RUNNING = ('active', 'activating', 'deactivating', 'reloading')
PLANS = {   # (phase, %, seconds); phases ending in _ref are the anchors sweep-aba.py compares against
    'notch': [('r720_ref', 10, 180)] + [(f'r720_{p}', p, 90) for p in range(38, 45)] + [('r720_ref', 10, 180)],
    'notch1015': [('r720_ref', 10, 60)] + [x for p in range(36, 45) for x in ((f'r720_{p}', p, 90), ('r720_ref', 10, 60))],
}
for _plan in PLANS.values():
    assert all(10 <= p <= 60 for _, p, _ in _plan)
PLAN = sys.argv[1] if len(sys.argv) > 1 else 'notch'
if PLAN not in PLANS:
    sys.exit(f'usage: r720-notch-sweep.py [{"|".join(PLANS)} [label]]')
LABEL = sys.argv[2] if len(sys.argv) > 2 else f'{PLAN}-{time.strftime("%m%d-%H%M")}'
CSV = f'/var/tmp/r720-notch-{LABEL}.csv'
PHASES = CSV[:-4] + '-phases.csv'
r720_ok = False   # True only while this unit holds fan-watchdog stopped

def run(*a):
    return subprocess.run(a, capture_output=True, text=True, timeout=60)

def note(msg):
    with open(CSV, 'a') as f:
        f.write(f'# {int(time.time())} {time.strftime("%F %T")} {msg}\n')
    print(msg, flush=True)

def phase_mark(phase, level, box='r720'):
    new = not os.path.exists(PHASES)
    with open(PHASES, 'a') as f:
        if new:
            f.write('epoch,phase,level,box\n')
        f.write(f'{int(time.time())},{phase},{level},{box}\n')

def shelf_rpm():
    """md1200-fan's own reading (its state file, every 10 s): no second SES reader next to it"""
    try:
        if time.time() - os.stat(MD_STATE).st_mtime > 60:
            return ''
        rpm = json.loads(open(MD_STATE).read()).get('rpm')
        return round(rpm) if isinstance(rpm, (int, float)) else ''
    except (OSError, ValueError):
        return ''

def r720():
    if not r720_ok:
        raise SystemExit('bug: an iDRAC read while fan-watchdog runs')
    t = run('ipmitool', 'sdr', 'type', 'Temperature').stdout
    cpus = [int(x) for x in re.findall(r'^Temp\s+\|[^|]+\|[^|]+\|[^|]+\|\s*(\d+) degrees', t, re.M)]
    inl = re.search(r'Inlet Temp\s+\|[^|]+\|[^|]+\|[^|]+\|\s*(\d+)', t)
    f = [int(x) for x in re.findall(r'(\d+) RPM', run('ipmitool', 'sdr', 'type', 'Fan').stdout)]
    return (max(cpus) if cpus else None), (int(inl.group(1)) if inl else ''), (round(sum(f) / len(f)) if f else '')

def row(phase, box, pct, cpu='', inlet='', rrpm=''):
    with open(CSV, 'a') as f:
        f.write(f'{int(time.time())},{time.strftime("%T")},{phase},{box},{pct},{shelf_rpm()},{rrpm},{cpu},{inlet}\n')

def r720_set(p):
    a = run('ipmitool', 'raw', '0x30', '0x30', '0x01', '0x00')
    b = run('ipmitool', 'raw', '0x30', '0x30', '0x02', '0xff', f'0x{p:02x}')
    if a.returncode or b.returncode:
        run('ipmitool', 'raw', '0x30', '0x30', '0x01', '0x01')
        raise SystemExit(f'R720 fan command failed: iDRAC auto ({a.stderr.strip()} {b.stderr.strip()})')

def r720_hold(phase, pct, secs):
    if not r720_ok:
        raise SystemExit('bug: an R720 fan command while fan-watchdog runs')
    r720_set(pct)
    note(f'phase {phase}: R720 {pct}%')
    phase_mark(phase, pct)
    t0 = time.time()
    while True:
        cpu, inlet, rrpm = r720()
        if cpu is None or cpu >= 75:
            run('ipmitool', 'raw', '0x30', '0x30', '0x01', '0x01')
            raise SystemExit(f'R720 CPU {cpu}: iDRAC auto, stopping')
        row(phase, 'r720', pct, cpu, inlet, rrpm)
        left = secs - (time.time() - t0)
        if left <= 0:
            break
        time.sleep(min(10, left))   # 2026-10-20: the hold ends on time

if __name__ == '__main__':
    steps = PLANS[PLAN]
    if not os.path.exists(CSV):
        open(CSV, 'w').write('epoch,time,phase,box,pct,shelf_rpm,r720_rpm,cpu,inlet\n')
    note(f'start plan {PLAN} ({sum(s[2] for s in steps) / 60:g} min of holds; shelf not touched, no SES read)')
    run('systemctl', 'stop', FW)
    st = run('systemctl', 'is-active', FW).stdout.strip()
    if st in RUNNING:
        raise SystemExit(f'fan-watchdog is still {st} after the stop: nothing commanded')
    note('fan-watchdog stopped')
    r720_ok = True
    try:
        for phase, pct, secs in steps:
            r720_hold(phase, pct, secs)
    finally:
        r720_ok = False
        run('systemctl', 'start', FW)
        note('fan-watchdog started; done')
        phase_mark('fan-watchdog', 'controller')
