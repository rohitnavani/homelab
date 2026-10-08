#!/usr/bin/env python3
# noise-sweep (2026-10-08): step the MD1200 shelf and the R720 fans through fixed levels at idle, one box at a time,
# A/B/A against a reference level, so morgana's mic log (analyze_mic_phases.py <mic.csv> <this CSV>) gives the sound
# of each level. Runs as root on mementos while the house is empty (Rohit at work).
#   Shelf (md1200-fan stopped): ref 15% 120 s, then each of SHELF_STEPS for 150 s with ref 15% 120 s after each.
#     Only the EMM on the cable, which must answer _who "primary and active" (the TOP one), is ever commanded; never
#     below 10%; _shutup is re-sent every 2 s. md1200-fan starts again at the end.
#   R720 (fan-watchdog stopped): ref 10% 120 s, then each of R720_STEPS for 120 s with ref 10% 120 s after each, with
#     the same documented Dell commands fan-watchdog uses. A CPU at 75C or more (idle, so it should never happen), a
#     failed read or a failed command -> iDRAC auto and stop. fan-watchdog starts again at the end.
# A row every 10 s to CSV (epoch, time, phase, box, pct, shelf rpm, R720 rpm, CPU, inlet). ExecStopPost
# (noise-sweep-restore.sh) starts md1200-fan and fan-watchdog whatever happens.
import re, subprocess, sys, time

CSV = '/var/tmp/noise-sweep.csv'
PORT = '/dev/ttyUSB0'
SHELF_REF, SHELF_STEPS = 15, [10, 20, 25, 30, 40]
R720_REF, R720_STEPS = 10, [15, 20, 25, 30, 35, 40, 45, 50]   # 35/45 added 10-08 08:38: the fan map heard +6 dB(A) from 35 to 40%
PROMPT = re.compile(r'(BlueDress|RedDress)\.[0-9.]+\s*>\s*$')
assert all(10 <= p <= 100 for p in SHELF_STEPS + [SHELF_REF]), 'never _shutup below 10'

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

class Shelf:
    def __init__(self):
        import serial
        run('systemctl', 'stop', 'md1200-fan')
        time.sleep(2)
        self.s = serial.Serial(PORT, 38400, timeout=0.1)
        who = self.cmd('_who', 3)
        if not re.search(r'I.?m\s+primary\s+and\s+active', who, re.I):
            raise SystemExit(f'EMM on the cable is not primary and active; not commanding it: {who!r}')
        note('EMM on the cable is primary and active')

    def cmd(self, c, secs=0.6):
        self.s.read(4096)
        self.s.write((c + '\r').encode())
        buf, end = b'', time.time() + secs
        while time.time() < end:
            d = self.s.read(4096)
            if d:
                buf += d
                if PROMPT.search(buf.decode(errors='replace')):
                    break
        return buf.decode(errors='replace')

    def hold(self, phase, pct, secs):
        note(f'phase {phase}: shelf {pct}%')
        t0 = nxt = time.time()
        while time.time() - t0 < secs:
            self.cmd(f'_shutup {pct}')
            if time.time() >= nxt:
                row(phase, 'shelf', pct); nxt += 10
            time.sleep(2)

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
    note(f'start (SES {SG})')
    sh = None
    try:
        sh = Shelf()
        sh.hold('shelf_ref', SHELF_REF, 120)
        for p in SHELF_STEPS:
            sh.hold(f'shelf_{p}', p, 150)
            sh.hold('shelf_ref', SHELF_REF, 120)
    finally:
        try:
            sh.s.close()
        except Exception:
            pass
        run('systemctl', 'start', 'md1200-fan')   # also when Shelf() refused a non-primary EMM
        note('md1200-fan started')
    time.sleep(60)   # let md1200-fan settle before the R720 steps
    run('systemctl', 'stop', 'fan-watchdog')
    note('fan-watchdog stopped')
    try:
        r720_hold('r720_ref', R720_REF, 120)
        for p in R720_STEPS:
            r720_hold(f'r720_{p}', p, 120)
            r720_hold('r720_ref', R720_REF, 120)
    finally:
        run('systemctl', 'start', 'fan-watchdog')
        note('fan-watchdog started; done')
