#!/usr/bin/env python3
# shelf-exp3: overnight MD1200 / R720 thermal + fan-actuation experiment (2026-10-05/06).
# (shelf-exp2 plus a mementos CPU-load phase, DIMM temps, and load guards.)
# - Holds the MD1200 at a fixed fan % per phase (md1200-fan stopped; this script sends _shutup
#   every 2s over a serial port it keeps open, so anything the EMM prints on its own is captured).
# - Sets the R720 fan-watchdog floor per phase.
# - Logs once a minute to LOG; EMM console output that wasn't a reply goes to CONSOLE_LOG.
# Safety: a phase ends early if a shelf drive, backplane, SIM or expander reaches its ABORT limit,
# and later phases at that shelf % or lower are skipped. On any exit md1200-fan is started again
# and the R720 floor goes back to 10% (the unit's ExecStopPost does the same).
import os, re, signal, subprocess, sys, time, serial

PHASES = [  # name, minutes, shelf %, R720 floor %, mementos CPU load (stress-ng workers, % each) or None
    ('s20_r10', 60, 20, 10, None),
    ('s20_r15', 60, 20, 15, None),
    ('s20_r10b', 45, 20, 10, None),
    ('s20_heat', 60, 20, 10, (24, 50)),
    ('s20_r10c', 45, 20, 10, None),
    ('s15_r10', 60, 15, 10, None),
    ('s25_r10', 60, 25, 10, None),
]
LOAD_ABORT = {'cpu': 78, 'dimm_max': 70}   # plus: R720 fans above 25% or in auto (noise guard)
ABORT = {'drive_max': 52, 'BP': 47, 'SIM': 58, 'EXP': 88}
assert all(10 <= p[2] <= 100 for p in PHASES), 'shelf % must be 10-100 (never _shutup below 10)'
PORT, SG, WD = '/dev/ttyUSB0', '/dev/sg39', '/usr/local/sbin/fan-watchdog'
LOG, CONSOLE_LOG = '/var/tmp/shelf-exp3.csv', '/var/tmp/shelf-exp3-console.log'
RESEND, POLL = 2, 4   # seconds between _shutup re-sends / fan-speed polls
SENS_RE = r'((?:BP_|SIM|EXP)\d\[\d\]) = (\d+)c'

def run(*a):
    return subprocess.run(a, capture_output=True, text=True).stdout

def stamp():
    return time.strftime('%F %T')

class EMM:
    """Persistent serial session; text that arrives between commands is logged as unsolicited."""
    def __init__(self):
        self.s, self.unsolicited, self.errors, self.samples = None, 0, 0, 0
        self.con = open(CONSOLE_LOG, 'a', buffering=1)

    def note(self, kind, text):
        if self.con.tell() < 5_000_000:
            self.con.write(f'--- {stamp()} {kind}\n{text.rstrip()}\n')

    def _read_for(self, secs, extend=0.5):
        out, end = b'', time.time() + secs
        hard = end + 3   # never block more than a few seconds, even if the EMM keeps talking
        while time.time() < min(end, hard):
            d = self.s.read(4096)
            if d:
                out += d
                end = max(end, time.time() + extend)
        return out.decode(errors='replace')

    def cmd(self, c):
        try:
            if self.s is None or not self.s.is_open:
                self.s = serial.Serial(PORT, 38400, timeout=0.1)
                self.note('open', PORT)
            pending = self._read_for(0.15, extend=0.3)
            if re.sub(r'BlueDress[\w.]*>|\s', '', pending):
                self.unsolicited += 1
                self.note('unsolicited', pending)
            self.s.write((c + '\r').encode())
            reply = self._read_for(2 if c == '_temp_rd' else 0.4)
            if self.samples < 6:
                self.samples += 1
                self.note(f'reply to {c!r}', reply)
            return reply
        except Exception as ex:
            self.errors += 1
            self.note('error', repr(ex))
            try:
                self.s.close()
            except Exception:
                pass
            self.s = None
            return ''

def slot_devs():
    # slot -> /dev/sdX via the SES slot's SAS port address (the drive's WWN differs in the last digit)
    slots, cur = {}, None
    for line in run('sg_ses', '--join', SG).splitlines():
        m = re.match(r'\s*Slot (\d+)', line)
        if m:
            cur = int(m.group(1))
            continue
        m = re.match(r'\s+SAS address: 0x([0-9a-f]{16})', line)
        if m and cur is not None and cur not in slots:
            slots[cur] = m.group(1)[:15]
    devs = {}
    for s, pfx in slots.items():
        for name in os.listdir('/dev/disk/by-id'):
            if name.startswith('wwn-0x' + pfx) and len(name) == 22:
                devs[s] = os.path.realpath('/dev/disk/by-id/' + name)
    return [devs[s] for s in sorted(devs)]

def drive_temp(dev):
    m = re.search(r'Current Drive Temperature:\s+(\d+)', run('smartctl', '-n', 'standby', '-A', dev))
    return int(m.group(1)) if m else None

def io_bytes(devs):
    names, total = {os.path.basename(d) for d in devs}, 0
    for line in open('/proc/diskstats'):
        f = line.split()
        if f[2] in names:
            total += (int(f[5]) + int(f[9])) * 512
    return total

def ses_state():
    out = run('sg_ses', '-p', '2', SG)
    rpm = [int(x) for x in re.findall(r'Actual speed=(\d+) rpm', out)][-4:]
    stat = {}
    for sec in out.split('Element type: ')[1:]:
        kind = sec.split(',')[0]
        if kind in ('Cooling', 'Enclosure services controller electronics', 'Power supply'):
            stat[kind] = '/'.join(re.findall(r'status: (\w+)', sec)[1:])  # [0] is the overall descriptor
    return rpm, stat

def dimm_regs():
    regs = []
    for line in run('lspci', '-D').splitlines():
        if 'Thermal Control' in line:
            dev = line.split()[0]
            for off in ('0x150', '0x154', '0x158'):
                v = int(run('setpci', '-s', dev, off + '.L').strip() or '0', 16)
                if v >> 24 == 7 and (v & 0xff) >= 10:
                    regs.append((dev, off))
    return regs

def dimm_max(regs):
    vals = [int(run('setpci', '-s', d, o + '.L').strip() or '0', 16) & 0xff for d, o in regs]
    return max(vals) if vals else ''

stress = None
def start_load(load, minutes):
    global stress
    stop_load()
    if load:
        stress = subprocess.Popen(['stress-ng', '--cpu', str(load[0]), '--cpu-load', str(load[1]),
                                   '--timeout', f'{minutes * 60 + 60}s', '--quiet'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def stop_load():
    global stress
    if stress and stress.poll() is None:
        stress.terminate()
        try:
            stress.wait(10)
        except subprocess.TimeoutExpired:
            stress.kill()
    stress = None

def set_floor(p):
    if re.search(rf'^MIN_PCT={p};', open(WD).read(), re.M):
        return
    subprocess.run(['sed', '-i', f's/^MIN_PCT=[0-9]*;/MIN_PCT={p};/', WD], check=True)
    subprocess.run(['systemctl', 'restart', 'fan-watchdog'])

def restore():
    stop_load()
    try:
        set_floor(10)
    finally:
        subprocess.run(['systemctl', 'start', 'md1200-fan'])

def r720_state():
    st = open('/run/fan-watchdog.state').read() if os.path.exists('/run/fan-watchdog.state') else ''
    m = re.search(r'(?:(\d+)% )?\(cpu=(\d+) exh=(\d+) inlet=(\d+) hdd=(\d+) ssd=(\d+)\)', st)
    vals = list(m.groups()) if m else [''] * 6
    if 'auto' in st:
        vals[0] = 'auto'
    pw = re.search(r'Instantaneous power reading:\s+(\d+)', run('ipmitool', 'dcmi', 'power', 'reading'))
    frpm = [int(x) for x in re.findall(r'\|\s*(\d+) RPM', run('ipmitool', 'sdr', 'type', 'fan'))]
    return dict(zip(['r720_pct', 'cpu', 'exh', 'inlet', 'int_hdd', 'ssd'], vals),
                r720_w=pw.group(1) if pw else '', r720_rpm=round(sum(frpm) / len(frpm)) if frpm else '')

COLS = ['time', 'phase', 'phase_min', 'shelf_set', 'rpm_avg', 'rpm_min', 'rpm_max'] + \
       [f's{i}' for i in range(12)] + \
       ['drive_max', 'drive_avg', 'SIM', 'BP', 'EXP', 'r720_floor', 'r720_pct', 'cpu', 'exh', 'inlet',
        'int_hdd', 'ssd', 'dimm_max', 'load', 'r720_w', 'r720_rpm', 'shelf_io_mb', 'unsolicited', 'serial_errors',
        'fan_status', 'emm_status', 'psu_status', 'emm_raw']

def main():
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
    devs = slot_devs()
    if len(devs) != 12:
        print('expected 12 shelf drives, found', devs, flush=True)
        return
    emm = EMM()
    regs = dimm_regs()
    subprocess.run(['systemctl', 'stop', 'md1200-fan'])
    new = not os.path.exists(LOG)
    log = open(LOG, 'a', buffering=1)
    if new:
        log.write(','.join(COLS) + '\n')
    log.write(f'# {stamp()} start, slots 0-11 -> {" ".join(os.path.basename(d) for d in devs)}\n')
    skip_at_or_below, last_io = None, io_bytes(devs)
    for name, mins, spct, floor, load in PHASES:
        if skip_at_or_below is not None and spct <= skip_at_or_below:
            log.write(f'# {stamp()} skip {name}: shelf {spct}% already reached a limit\n')
            continue
        set_floor(floor)
        start_load(load, mins)
        log.write(f'# {stamp()} phase {name}: shelf {spct}%, R720 floor {floor}%, load {load}\n')
        start, next_log, next_poll, rpms = time.time(), time.time() + 60, 0, []
        while time.time() - start < mins * 60:
            emm.cmd('_shutup %d' % spct)
            if time.time() >= next_poll:
                next_poll = time.time() + POLL
                rpm, _ = ses_state()
                if rpm:
                    rpms.append(sum(rpm) / len(rpm))
            if time.time() >= next_log:
                next_log = time.time() + 60
                temps = [drive_temp(d) for d in devs]
                emm.cmd('_shutup %d' % spct)
                raw = emm.cmd('_temp_rd')
                sens = {}
                for k, v in re.findall(SENS_RE, raw):
                    sens.setdefault(re.match(r'[A-Z]+', k).group(0), []).append(int(v))
                rpm, stat = ses_state()
                io = io_bytes(devs)
                good = [t for t in temps if t]
                row = dict(time=time.strftime('%T'), phase=name, phase_min=round((time.time() - start) / 60, 1),
                           shelf_set=spct, r720_floor=floor,
                           rpm_avg=round(sum(rpms) / len(rpms)) if rpms else '',
                           rpm_min=round(min(rpms)) if rpms else '', rpm_max=round(max(rpms)) if rpms else '',
                           drive_max=max(good) if good else '',
                           drive_avg=round(sum(good) / len(good), 2) if good else '',
                           SIM=max(sens['SIM']) if 'SIM' in sens else '',
                           BP=max(sens['BP']) if 'BP' in sens else '',
                           EXP=max(sens['EXP']) if 'EXP' in sens else '',
                           shelf_io_mb=round((io - last_io) / 1e6, 1),
                           unsolicited=emm.unsolicited, serial_errors=emm.errors,
                           fan_status=stat.get('Cooling', ''),
                           emm_status=stat.get('Enclosure services controller electronics', ''),
                           psu_status=stat.get('Power supply', ''),
                           emm_raw=' '.join(f'{k}={v}' for k, v in re.findall(SENS_RE, raw)),
                           dimm_max=dimm_max(regs),
                           load=(f'{load[0]}x{load[1]}' if load and stress and stress.poll() is None else ''),
                           **{f's{i}': (t or '') for i, t in enumerate(temps)}, **r720_state())
                last_io, rpms = io, []
                log.write(','.join(str(row.get(c, '')) for c in COLS) + '\n')
                hot = [k for k, lim in ABORT.items() if isinstance(row.get(k), int) and row[k] >= lim]
                if hot:
                    log.write(f'# {stamp()} {name} ended early: {", ".join(hot)} at limit\n')
                    skip_at_or_below = spct
                    break
                if stress:
                    def num(v):
                        try:
                            return float(v)
                        except (TypeError, ValueError):
                            return None
                    why = [f'{k}={row[k]}' for k, lim in LOAD_ABORT.items() if num(row.get(k)) is not None and num(row[k]) >= lim]
                    if row.get('r720_pct') == 'auto' or (num(row.get('r720_pct')) or 0) > 25:
                        why.append(f"r720 fans {row.get('r720_pct')}")
                    if why:
                        stop_load()
                        log.write(f'# {stamp()} {name}: load stopped ({", ".join(why)})\n')
            time.sleep(RESEND)
        stop_load()
    log.write(f'# {stamp()} done\n')

if __name__ == '__main__':
    try:
        main()
    finally:
        restore()
