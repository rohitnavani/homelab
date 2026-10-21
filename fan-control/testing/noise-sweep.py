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
# 2026-10-20 (new-spot run, notes ~/lab-thermal-2026-10-20): plans by argument, one box per unit:
#   shelf  T1b: shelf 10/20/10/30/10/40/10%, 3-min holds (md1200-fan stopped meanwhile; fan-watchdog untouched)
#   r720   T1b: R720 10/20/10/30/10/35/10/40/10/45/10/50/10%, 3-min holds (fan-watchdog stopped; the shelf untouched)
#   proof  T1a: R720 10/45/10/45/10%, 3-min holds: does the mirror mic see the rack?
#   both1015: the 2026-10-15 sweep (both boxes, the old levels and holds)
# - In-band reads only next to a controller this unit stopped: the SES page only while md1200-fan is stopped by it
#   (else the shelf rpm comes from md1200-fan's own state file), the iDRAC only while fan-watchdog is stopped by it.
#   Each stop is checked (systemctl is-active) before the first command; still running -> nothing is commanded.
# - The SES device is found by type (13) and model (MD1200) only: no fallback number (sg39 became sg38 on 10-13).
# - CSV /var/tmp/noise-sweep-<label>.csv (label = 2nd argument, default <plan>-<MMDD-HHMM>) and the phase boundaries
#   for the mic (epoch, phase, level, box) in /var/tmp/noise-sweep-<label>-phases.csv. R720 holds end on time.
#   systemd-run --unit=mic-shelf-sweep-<x> -p ExecStopPost=/var/tmp/noise-sweep-restore.sh \
#     python3 -I /var/tmp/noise-sweep-1020.py shelf [label]
import json, os, re, subprocess, sys, time

PORT = '/dev/ttyUSB0'   # the FTDI adapter on the TOP EMM (md1200-fan's port too); _who must say primary and active
MD_STATE, FW = '/run/md1200-fan.state', 'fan-watchdog'
PROMPT = re.compile(r'(BlueDress|RedDress)\.[0-9.]+\s*>\s*$')
RUNNING = ('active', 'activating', 'deactivating', 'reloading')


def aba(box, ref, steps, step_s, ref_s=None):
    """ref, step, ref, step, ..., ref: each step A/B/A against the reference level"""
    out = [(box, f'{box}_ref', ref, ref_s or step_s)]
    for p in steps:
        out += [(box, f'{box}_{p}', p, step_s), (box, f'{box}_ref', ref, ref_s or step_s)]
    return out


PLANS = {   # (box, phase, %, seconds)
    'shelf': aba('shelf', 10, [20, 30, 40], 180),                          # T1b 2026-10-20, 21 min
    'r720': aba('r720', 10, [20, 30, 35, 40, 45, 50], 180),                # T1b 2026-10-20, 39 min
    'proof': aba('r720', 10, [45, 45], 180),                               # T1a 2026-10-20, 15 min
    # 35/45 added 10-08 08:38: the fan map heard +6 dB(A) from 35 to 40%
    'both1015': aba('shelf', 15, [10, 20, 25, 30, 40], 150, 120) + aba('r720', 10, [15, 20, 25, 30, 35, 40, 45, 50], 120),
}
for _plan in PLANS.values():
    assert all(10 <= p <= 100 for b, _, p, _ in _plan if b == 'shelf'), 'never _shutup below 10'
    assert all(10 <= p <= 60 for b, _, p, _ in _plan if b == 'r720'), 'R720 steps 10-60% only'
PLAN = sys.argv[1] if len(sys.argv) > 1 else ''
if PLAN not in PLANS:
    sys.exit(f'usage: noise-sweep.py <{"|".join(PLANS)}> [label]')
LABEL = sys.argv[2] if len(sys.argv) > 2 else f'{PLAN}-{time.strftime("%m%d-%H%M")}'
CSV = f'/var/tmp/noise-sweep-{LABEL}.csv'
PHASES = CSV[:-4] + '-phases.csv'
ses_ok = False    # True only while this unit holds md1200-fan stopped (the SES page is md1200-fan's otherwise)
r720_ok = False   # True only while this unit holds fan-watchdog stopped

def run(*a):
    return subprocess.run(a, capture_output=True, text=True, timeout=60)

def note(msg):
    with open(CSV, 'a') as f:
        f.write(f'# {int(time.time())} {time.strftime("%F %T")} {msg}\n')
    print(msg, flush=True)

def phase_mark(phase, level, box):
    new = not os.path.exists(PHASES)
    with open(PHASES, 'a') as f:
        if new:
            f.write('epoch,phase,level,box\n')
        f.write(f'{int(time.time())},{phase},{level},{box}\n')

def stopped(unit):
    """stop a controller and check it is down (also cancels a pending auto-restart)"""
    run('systemctl', 'stop', unit)
    st = run('systemctl', 'is-active', unit).stdout.strip()
    if st in RUNNING:
        raise SystemExit(f'{unit} is still {st} after the stop: nothing commanded')
    note(f'{unit} stopped')

def ses_devs():
    out = []
    try:
        names = os.listdir('/sys/class/scsi_generic')
    except OSError:
        return out
    for n in sorted(names, key=lambda x: int(re.sub(r'\D', '', x) or 0)):
        try:
            d = f'/sys/class/scsi_generic/{n}/device'
            if open(f'{d}/type').read().strip() == '13' and 'MD1200' in open(f'{d}/model').read():
                out.append('/dev/' + n)
        except OSError:
            pass
    return out

SES_ALL = ses_devs()
SG = SES_ALL[0] if SES_ALL else None   # md1200-fan's choice (the first by number); none -> no SES reads

def shelf_rpm():
    if ses_ok:   # md1200-fan is stopped by this unit: the SES page is ours (its state file is old news then)
        if not SG:
            return ''
        r = [int(x) for x in re.findall(r'Actual speed=(\d+) rpm', run('sg_ses', '-p', '2', SG).stdout)][-4:]
        return round(sum(r) / len(r)) if r else ''
    try:   # md1200-fan runs: its own reading (state file, every 10 s); no second SES reader next to it
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

class Shelf:
    def __init__(self):
        global ses_ok
        import serial
        stopped('md1200-fan')
        ses_ok = True
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
        if pct < 10:
            raise SystemExit('never _shutup below 10')
        note(f'phase {phase}: shelf {pct}%')
        t0 = nxt = time.time()
        first = True
        while time.time() - t0 < secs:
            self.cmd(f'_shutup {pct}')
            if first:
                phase_mark(phase, pct, 'shelf')
                first = False
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
    if not r720_ok:
        raise SystemExit('bug: an R720 fan command while fan-watchdog runs')
    r720_set(pct)
    note(f'phase {phase}: R720 {pct}%')
    phase_mark(phase, pct, 'r720')
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
    note(f'start plan {PLAN} ({sum(s[3] for s in steps) / 60:g} min of holds); SES {SG or "not found"}'
         + (f' (all MD1200 enclosures: {" ".join(SES_ALL)})' if len(SES_ALL) > 1 else ''))
    groups = []
    for s in steps:
        if groups and groups[-1][0] == s[0]:
            groups[-1][1].append(s)
        else:
            groups.append((s[0], [s]))
    for gi, (box, part) in enumerate(groups):
        if box == 'shelf':
            sh = None
            try:
                sh = Shelf()
                for _, phase, pct, secs in part:
                    sh.hold(phase, pct, secs)
            finally:
                ses_ok = False
                try:
                    sh.s.close()
                except Exception:
                    pass
                run('systemctl', 'start', 'md1200-fan')   # also when Shelf() refused a non-primary EMM
                note('md1200-fan started')
                phase_mark('md1200-fan', 'controller', 'shelf')
        else:
            stopped(FW)
            r720_ok = True
            try:
                for _, phase, pct, secs in part:
                    r720_hold(phase, pct, secs)
            finally:
                r720_ok = False
                run('systemctl', 'start', FW)
                note('fan-watchdog started')
                phase_mark('fan-watchdog', 'controller', 'r720')
        if gi < len(groups) - 1:
            time.sleep(60)   # let the restarted controller settle before the next box
    note('done')
