#!/usr/bin/env python3
# r720-notch-sweep (2026-10-08): find the edges of the ~700 Hz resonance that makes the R720 at 40% louder than at
# 45% (noise sweep 10:30: +12.0 vs +9.7 dB(A); the fans' blade-pass tone, 5 x rpm/60, is ~693 Hz at 40%). R720 only,
# idle, fan-watchdog stopped: ref 10% 60 s, then each of R720_STEPS for 90 s with ref 10% 60 s after each, with the
# same documented Dell commands fan-watchdog uses. A CPU at 75C or more, a failed read or a failed command -> iDRAC
# auto and stop. fan-watchdog starts again at the end. Never touches the shelf. CSV /var/tmp/r720-notch.csv
# (epoch, time, phase, box, pct, shelf rpm, R720 rpm, CPU, inlet); analyze with analyze_mic_phases.py.
# Run as unit mic-r720-notch (the v3 alert rules stay quiet for mic-r720*); ExecStopPost starts fan-watchdog.
import re, subprocess, sys, time

CSV = '/var/tmp/r720-notch.csv'
PORT = '/dev/ttyUSB0'
R720_REF, R720_STEPS = 10, [36, 37, 38, 39, 40, 41, 42, 43, 44]
STEP_S, REF_S = 90, 60
PROMPT = re.compile(r'(BlueDress|RedDress)\.[0-9.]+\s*>\s*$')
assert all(10 <= p <= 60 for p in R720_STEPS + [R720_REF])

def run(*a):
    return subprocess.run(a, capture_output=True, text=True, timeout=60)

def note(msg):
    with open(CSV, 'a') as f:
        f.write(f'# {int(time.time())} {time.strftime("%F %T")} {msg}\n')
    print(msg, flush=True)

def ses_dev():
    import os
    for n in sorted(os.listdir('/sys/class/scsi_generic'), key=lambda x: int(re.sub(r'\D', '', x) or 0)):
        try:
            d = f'/sys/class/scsi_generic/{n}/device'
            if open(f'{d}/type').read().strip() == '13' and 'MD1200' in open(f'{d}/model').read():
                return '/dev/' + n
        except OSError:
            pass
    return '/dev/sg39'

SG = ses_dev()

def shelf_rpm():
    r = [int(x) for x in re.findall(r'Actual speed=(\d+) rpm', run('sg_ses', '-p', '2', SG).stdout)][-4:]
    return round(sum(r) / len(r)) if r else ''

def r720():
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
    r720_set(pct)
    note(f'phase {phase}: R720 {pct}%')
    t0 = time.time()
    while time.time() - t0 < secs:
        cpu, inlet, rrpm = r720()
        if cpu is None or cpu >= 75:
            run('ipmitool', 'raw', '0x30', '0x30', '0x01', '0x01')
            raise SystemExit(f'R720 CPU {cpu}: iDRAC auto, stopping')
        row(phase, 'r720', pct, cpu, inlet, rrpm)
        time.sleep(10)

if __name__ == '__main__':
    try:
        open(CSV)
    except OSError:
        open(CSV, 'w').write('epoch,time,phase,box,pct,shelf_rpm,r720_rpm,cpu,inlet\n')
    note(f'start (SES {SG}; shelf not touched)')
    run('systemctl', 'stop', 'fan-watchdog')
    note('fan-watchdog stopped')
    try:
        r720_hold('r720_ref', R720_REF, REF_S)
        for p in R720_STEPS:
            r720_hold(f'r720_{p}', p, STEP_S)
            r720_hold('r720_ref', R720_REF, REF_S)
    finally:
        run('systemctl', 'start', 'fan-watchdog')
        note('fan-watchdog started; done')
