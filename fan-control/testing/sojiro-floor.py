#!/usr/bin/env python3
# sojiro-floor (2026-10-14): idle step test of sojiro's BMC fan offset (Gigabyte MB10-series board, Avocent MergePoint 8.65 at
# 10.0.0.14; the same "PWM offset" as ryuji, set through the BMC's web calls by gbt-fan-offset.py). sojiro has no fan
# controller: the BMC's own curves run the fans and the offset shifts them (on ryuji a negative offset moved only the CPU
# fans at idle; the curves still ramp with temperature). Its noise is the CPU fan (3,400 rpm at idle at offset 0).
# usage (root, on sojiro): sojiro-floor.py <label> [plan]   CSV /var/tmp/sojiro-floor-<label>.csv (every 20 s)
# Safety: back to offset 0 at once and exit if SYS_FAN1 reads under 600 rpm or not at all (it idles at 600, its BMC
# lower-critical), CPU0_FAN under 1,000 rpm, CPU0_TEMP 85C or more (Xeon D-1521: coretemp high 92, crit 102) or
# MB_TEMP1 75C or more (it idles at 65-67C; BMC thresholds 55/60 are wrong for this board and never acted on).
# Any BMC set that fails exits (no retries). The end of the plan and any stop leave the offset at 0 (the BMC default);
# ExecStopPost sojiro-floor-restore.sh does the same if the unit is stopped. The first set switches the BMC to user mode.
import os, re, subprocess, sys, time

LABEL = sys.argv[1] if len(sys.argv) > 1 else 'run'
PLANS = {
    'steps': [('o0_a', 0, 6), ('o31', -31, 6), ('o61', -61, 6), ('o80', -80, 6), ('o100', -100, 6), ('o127', -127, 6),
              ('o0_b', 0, 6)],
    'dry': [('d0', 0, 0.5), ('d61', -61, 0.5), ('d0b', 0, 0.5)],
}
PLAN = PLANS[sys.argv[2] if len(sys.argv) > 2 else 'steps']
CSV = f'/var/tmp/sojiro-floor-{LABEL}.csv'
TOOL = ['python3', '-W', 'ignore', '/var/tmp/gbt-fan-offset.py', '10.0.0.14']
ENV = dict(os.environ, BMC_PWFILE='/root/.bmc-pass', BMC_USER='root')
STOP = {'cpu_fan_min': 1000, 'sys_fan_min': 600, 'cpu': 85, 'mb': 75}


def sh(*a, **k):
    return subprocess.run(a, capture_output=True, text=True, timeout=60, **k)


def note(m):
    with open(CSV, 'a') as f:
        f.write(f'# {int(time.time())} {time.strftime("%F %T %Z")} {m}\n')
    print(m, flush=True)


def set_offset(o):
    r = sh(*TOOL, 'set', str(o), env=ENV)
    got = re.search(r'now (-?\d+)', r.stdout)
    if r.returncode != 0 or not got or int(got.group(1)) != o:
        note(f'BMC set {o} failed (rc {r.returncode}: {r.stdout.strip()[-120:]} {r.stderr.strip()[-160:]})')
        return False
    note(f'BMC offset set to {o}')
    return True


def sensors():
    v = {}
    for line in sh('ipmitool', 'sensor').stdout.splitlines():
        f = [x.strip() for x in line.split('|')]
        if len(f) < 3:
            continue
        try:
            v[f[0]] = float(f[1])
        except ValueError:
            v[f[0]] = None
    pk = None
    for h in os.listdir('/sys/class/hwmon'):
        try:
            if open(f'/sys/class/hwmon/{h}/name').read().strip() == 'coretemp':
                pk = int(open(f'/sys/class/hwmon/{h}/temp1_input').read()) // 1000
        except OSError:
            pass
    return {'cpu': v.get('CPU0_TEMP'), 'pkg': pk, 'mb': v.get('MB_TEMP1'), 'cpu_fan': v.get('CPU0_FAN'),
            'sys_fan': v.get('SYS_FAN1')}


cols = ['epoch', 'time', 'phase', 'phase_min', 'offset', 'cpu', 'pkg', 'mb', 'cpu_fan', 'sys_fan']
if not os.path.exists(CSV):
    with open(CSV, 'w') as f:
        f.write(','.join(cols) + '\n')
note(f'start {LABEL} ({sum(m for _, _, m in PLAN)} min)')
ok = True
try:
    for label, off, mins in PLAN:
        if not set_offset(off):
            ok = False
            break
        note(f'phase {label}: offset {off}, {mins} min')
        t0 = time.time()
        while time.time() - t0 < mins * 60:
            time.sleep(10 if mins < 2 else 20)
            s = sensors()
            with open(CSV, 'a') as f:
                f.write(','.join(str(x) for x in [int(time.time()), time.strftime('%T'), label,
                                                  f'{(time.time() - t0) / 60:.1f}', off] +
                        ['' if s[k] is None else s[k] for k in ('cpu', 'pkg', 'mb', 'cpu_fan', 'sys_fan')]) + '\n')
            bad = []
            if s['sys_fan'] is None or s['sys_fan'] < STOP['sys_fan_min']:
                bad.append(f'SYS_FAN1 {s["sys_fan"]}')
            if s['cpu_fan'] is None or s['cpu_fan'] < STOP['cpu_fan_min']:
                bad.append(f'CPU0_FAN {s["cpu_fan"]}')
            if (s['cpu'] or 0) >= STOP['cpu']:
                bad.append(f'CPU0_TEMP {s["cpu"]}')
            if (s['mb'] or 0) >= STOP['mb']:
                bad.append(f'MB_TEMP1 {s["mb"]}')
            if bad and off != 0:
                note(f'{label}: STOP ({", ".join(bad)}): back to 0')
                ok = False
                break
        if not ok:
            break
    note('done' if ok else 'ended early')
finally:
    set_offset(0)
