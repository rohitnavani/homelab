#!/usr/bin/env python3
# Fake-clock dry runs of disk-soak.py v2: a fake host (zpool, lsblk, smartctl for SAS/SATA/NVMe, fan controller state
# files, fio, /proc/diskstats), scripted events at given minutes. No real command runs.
# usage: python3 -I tests/test_disk_soak.py [-v]
import importlib.util, json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
exec(open(os.path.join(HERE, 'guard.py')).read())   # any real subprocess/network call now raises
spec = importlib.util.spec_from_file_location('disk_soak', os.path.join(HERE, '..', 'disk-soak.py'))
ds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ds)
VERBOSE = '-v' in sys.argv
T0 = 1_792_486_500.0   # 2026-10-20 05:35 EDT


class Dev:
    def __init__(self, name, serial, model, proto, temp, rota=True, wwn=None):
        self.name, self.serial, self.model, self.proto, self.temp, self.rota = name, serial, model, proto, temp, rota
        self.wwn = wwn or f'wwn-0x5000{abs(hash(serial)) % 10**12:012d}'
        self.defects, self.realloc, self.pending, self.crc, self.media, self.crit = 0, 0, 0, 0, 0, 0
        self.phy = {('1', '0'): [0, 0, 0, 0], ('2', '1'): [0, 0, 0, 0]}
        self.standby = False
        self.broken = False


class FakeProc:
    def __init__(self, env, args):
        self.env, self.args, self.start = env, args, env.t
        job = env.files[args[-1]]
        self.runtime = int([l for l in job.splitlines() if l.startswith('runtime=')][0].split('=')[1])
        self.killed = False
        self.die_at = env.fio_die_at

    def poll(self):
        if self.killed:
            return -15
        if self.die_at is not None and self.env.t - self.start >= self.die_at:
            return 1
        return 0 if self.env.t - self.start >= self.runtime else None

    def terminate(self):
        self.killed = True
        self.env.log.append((self.env.minute(), 'fio terminated'))

    def wait(self, timeout=None):
        return -15

    def kill(self):
        self.killed = True


class FakeEnv(ds.Env):
    def __init__(self, devs, pool='dataPool', host='mementos', aux=(), events=None, fan_files=True, pool_state='ONLINE'):
        self.t = T0
        self.devs = {f'/dev/{d.name}': d for d in devs}
        self.aux = [f'/dev/{d.name}' for d in aux]
        for d in aux:
            self.devs[f'/dev/{d.name}'] = d
        self.pool, self.host, self.events = pool, host, sorted((events or {}).items())
        self.files, self.mtimes = {}, {}
        self.log, self.procs, self.outs = [], [], []
        self.sectors = 0
        self.fio_die_at = None
        self.pool_state = pool_state
        self.shelf_pct, self.r720 = 10, '10%'
        self.shelf_temps = {'drive': 49, 'backplane': 44, 'SIM': 52, 'expander': 81}
        self.md_fail = 0                 # next reads of md1200-fan's state that fail (a partial write)
        if fan_files:
            self.set_fans()

    def minute(self):
        return round((self.t - T0) / 60, 1)

    def set_fans(self, shelf=None, r720=None, age=0):
        if shelf is not None:
            self.shelf_pct = shelf
        if r720 is not None:
            self.r720 = r720
        self.files['/run/md1200-fan.state'] = json.dumps({'time': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.t - age)),
                                                          'pct': self.shelf_pct, 'rpm': 2400, 'temps': dict(self.shelf_temps)})
        self.files['/run/fan-watchdog.state'] = f'2026-10-20 09:35:00 {self.r720} (cpu=49 exh=42 inlet=23 hdd=34 ssd=43) (dimm=41)\n'
        self.mtimes['/run/md1200-fan.state'] = self.t - age
        self.mtimes['/run/fan-watchdog.state'] = self.t - age

    # clock
    def now(self):
        return self.t

    def sleep(self, s):
        end = self.t + s
        while self.events and T0 + self.events[0][0] * 60 <= end:
            m, fn = self.events.pop(0)
            self.t = max(self.t, T0 + m * 60)
            fn(self)
        self.t = end
        if any(p.poll() is None for p in self.procs):
            self.sectors += int(s * 200e6 / 512)
        # fresh controller state every minute unless a test froze it
        if not getattr(self, 'frozen', False):
            self.set_fans()

    # commands
    def run(self, args, timeout=90):
        a = list(args)
        if a[:3] == ['zpool', 'status', '-P']:
            lines = [f'  pool: {self.pool}', f' state: {self.pool_state}', 'config:', f'\t{self.pool} ONLINE 0 0 0',
                     '\t  raidz2-0 ONLINE 0 0 0']
            for p, d in self.devs.items():
                if p not in self.aux:
                    lines.append(f'\t    /dev/disk/by-id/{d.wwn}-part1  ONLINE       0     0     0')
            if self.aux:
                lines.append('\tlogs\t')
                for p in self.aux:
                    lines.append(f'\t  /dev/disk/by-id/{self.devs[p].wwn}-part1  ONLINE  0 0 0')
            return 0, '\n'.join(lines) + '\nerrors: No known data errors\n'
        if a[:3] == ['fio', '--readonly', '--parse-only']:
            job = self.files.get(a[3], '')
            self.log.append((self.minute(), 'fio parse-only'))
            return (0, '') if job.startswith('[global]') and 'direct=1' in job else (1, 'fio: bad job\n')
        if a[0] == 'lsblk':
            d = self.devs[a[-1]]
            return 0, json.dumps({'blockdevices': [{'name': d.name, 'serial': d.serial, 'model': d.model,
                                                    'rota': d.rota, 'tran': 'sas'}]})
        if a[0] == 'smartctl':
            d = self.devs[a[-1]]
            self.log.append((self.minute(), 'smartctl ' + ' '.join(a[1:-1]) + ' ' + d.name))
            if d.broken:
                return 2, 'Smartctl open device: /dev/x failed: No such device\n'
            if '-i' in a:
                return 0, {'sas': f'Product: {d.model}\nTransport protocol:   SAS (SPL-4)\n',
                           'ata': f'Device Model:     {d.model}\nSATA Version is:  SATA 3.0\n'
                                  + ('Rotation Rate:    7200 rpm\n' if d.rota else 'Rotation Rate:    Solid State Device\n'),
                           'nvme': f'Model Number:  {d.model}\nNVMe Version:  1.4\n'}[d.proto]
            if '-c' in a:
                return 0, 'Warning  Comp. Temp. Threshold:     83 Celsius\nCritical Comp. Temp. Threshold:    85 Celsius\n'
            if d.standby and '-n' in a:
                return 2, 'Device is in STANDBY mode, exit(2)\n'
            if d.proto == 'sas':
                out = (f'Current Drive Temperature:     {d.temp} C\nDrive Trip Temperature:        60 C\n'
                       f'Elements in grown defect list: {d.defects}\n')
                if 'sasphy' in a:
                    for (port, pid), v in d.phy.items():
                        out += (f'relative target port id = {port}\n  phy identifier = {pid}\n'
                                f'    Invalid DWORD count = {v[0]}\n    Running disparity error count = {v[1]}\n'
                                f'    Loss of DWORD synchronization count = {v[2]}\n    Phy reset problem count = {v[3]}\n')
                return 0, out
            if d.proto == 'ata':
                return 0, ('ID# ATTRIBUTE_NAME          FLAG     VALUE WORST THRESH TYPE      UPDATED  WHEN_FAILED RAW_VALUE\n'
                           f'  5 Reallocated_Sector_Ct   0x0033   100   100   050    Pre-fail  Always       -       {d.realloc}\n'
                           f'194 Temperature_Celsius     0x0022   100   100   000    Old_age   Always       -       {d.temp} (Min/Max 19/51)\n'
                           f'197 Current_Pending_Sector  0x0032   100   100   000    Old_age   Always       -       {d.pending}\n'
                           f'198 Offline_Uncorrectable   0x0030   100   100   000    Old_age   Offline      -       0\n'
                           f'199 UDMA_CRC_Error_Count    0x0032   200   200   000    Old_age   Always       -       {d.crc}\n')
            return 0, (f'Critical Warning:                   0x{d.crit:02x}\nTemperature:                        {d.temp} Celsius\n'
                       f'Available Spare:                    100%\nMedia and Data Integrity Errors:    {d.media}\n')
        raise AssertionError(f'unexpected command {a}')

    def read(self, path):
        if path == '/run/md1200-fan.state' and self.md_fail > 0 and path in self.files:
            self.md_fail -= 1
            return '{"time": "2026-10-20 05:3'          # caught mid-write
        if path == '/proc/diskstats':
            return '\n'.join(f'   8  0 {d.name} 100 0 {self.sectors} 0 0 0 0 0' for d in self.devs.values())
        if path not in self.files:
            raise OSError(path)
        return self.files[path]

    def mtime(self, path):
        if path not in self.mtimes:
            raise OSError(path)
        return self.mtimes[path]

    def exists(self, path):
        return path in self.files

    def write(self, path, text, mode='a'):
        self.files[path] = (self.files.get(path, '') if mode == 'a' else '') + text

    def remove(self, path):
        self.files.pop(path, None)

    def realpath(self, path):
        for p, d in self.devs.items():
            if path.endswith(d.wwn):
                return p
        return path

    def hostname(self):
        return self.host

    def killgroup(self, proc, sig):
        proc.killed = True
        self.log.append((self.minute(), f'killgroup {int(sig)}'))

    def popen(self, args):
        assert args[:2] == ['fio', '--readonly'], args
        job = self.files[args[-1]]
        assert 'direct=1' in job and 'rw=write' not in job and 'trim' not in job, job
        p = FakeProc(self, args)
        self.procs.append(p)
        self.jobs = getattr(self, 'jobs', []) + [job]
        self.log.append((self.minute(), 'fio start ' + [l for l in job.splitlines() if l.startswith('rw=')][0]))
        return p

    def out(self, text):
        self.outs.append(text)
        if VERBOSE:
            print('   |', text)


def shelf(n=3):
    return [Dev(f'sda{chr(98 + i)}', f'ZA15{i:04d}', 'ST8000NM0075', 'sas', 45) for i in range(n)]


def run(argv, env, ev=None):
    vars_ = {'CSV_DIR': '/tmp/x', 'RUN_DIR': '/run'}
    vars_.update(ev or {})
    rc = ds.main(argv, env, vars_)
    csv = env.files.get(f'/tmp/x/disk-soak-{argv[[a for a in argv if a != "--selftest"].__len__() and 0] if argv[0] != "--selftest" else argv[1]}.csv', '')
    return rc, csv


def csv_of(env, label):
    return env.files.get(f'/tmp/x/disk-soak-{label}.csv', '')


RESULTS = []


def case(name, ok, detail=''):
    RESULTS.append((name, ok))
    print(f'{"PASS" if ok else "FAIL"}  {name}' + (f'  ({detail})' if detail and (VERBOSE or not ok) else ''))


# 1. normal two-phase run, caps on, nothing happens
e = FakeEnv(shelf())
rc = ds.main(['t1', 'dataPool', 'seq:30,rand:20', '54'], e, {'CSV_DIR': '/tmp/x', 'FAN_CAP_SHELF': '25', 'FAN_CAP_R720': '24'})
c = csv_of(e, 't1')
rows = [l for l in c.splitlines() if l and not l.startswith('#') and not l.startswith('epoch')]
starts = [x for x in e.log if x[1].startswith('fio start')]
case('normal run: exit 0, two phases, ~51 rows, done note', rc == 0 and len(starts) == 2 and 49 <= len(rows) <= 53
     and '# ' in c and ' done' in c and 'unchanged from the start' in c, f'rc {rc} rows {len(rows)} starts {starts}')
hdr = c.splitlines()[0]
case('CSV header names each device with its serial', 'sdab_ZA150000' in hdr and 'fan_shelf' in hdr, hdr)
case('fan levels logged', rows and rows[0].split(',')[8] == '10' and rows[0].split(',')[9] == '10', rows[0] if rows else '')
hc = [x for x in e.log if 'sasphy' in x[1]]
case('health reads every 10 min (sasphy at start + 5 checks + final)', 3 * 6 <= len(hc) <= 3 * 8, f'{len(hc)} sasphy reads')

# 2. temperature stop at the Exos class line (54) even with a higher CLI limit absent
e = FakeEnv(shelf(), events={12.5: lambda env: setattr(env.devs['/dev/sdac'], 'temp', 54)})
rc = ds.main(['t2', 'dataPool', 'seq:60'], e, {'CSV_DIR': '/tmp/x'})
c = csv_of(e, 't2')
case('temp stop: exit 3 at 54C, fio group sent TERM then KILL', rc == 3 and 'STOP: seq: temperature: sdac ZA150001 54C (stop 54C, 2 reads in a row)' in c
     and any(x[1] == 'killgroup 15' for x in e.log) and any(x[1] == 'killgroup 9' for x in e.log), c[-300:])

# 3. CLI limit lowers the line: 52
e = FakeEnv(shelf(), events={5.5: lambda env: setattr(env.devs['/dev/sdab'], 'temp', 52)})
rc = ds.main(['t3', 'dataPool', 'seq:60', '52'], e, {'CSV_DIR': '/tmp/x'})
case('CLI limit 52 lowers the Exos 54 line', rc == 3 and '(stop 52C, 2 reads' in csv_of(e, 't3'))

# 4. grown defect +1 -> exit 4 at the next 10-min check
e = FakeEnv(shelf(), events={13: lambda env: setattr(env.devs['/dev/sdad'], 'defects', 1)})
rc = ds.main(['t4', 'dataPool', 'seq:60'], e, {'CSV_DIR': '/tmp/x'})
c = csv_of(e, 't4')
stop_line = [l for l in c.splitlines() if 'STOP:' in l]
case('grown defect +1: exit 4 at the 20-min check', rc == 4 and 'grown defects 0 -> 1' in c and stop_line
     and abs(int(stop_line[0].split()[1]) - (T0 + 20 * 60)) <= 60, stop_line)

# 5. SAS phy: +50 no stop, +101 stop
def phy_up(n):
    def f(env):
        env.devs['/dev/sdab'].phy[('1', '0')][0] += n
    return f
e = FakeEnv(shelf(), events={5: phy_up(50)})
rc = ds.main(['t5a', 'dataPool', 'seq:30'], e, {'CSV_DIR': '/tmp/x'})
case('SAS phy +50 (under PHY_JUMP 100): no stop', rc == 0)
e = FakeEnv(shelf(), events={5: phy_up(50), 15: phy_up(51)})
rc = ds.main(['t5b', 'dataPool', 'seq:30'], e, {'CSV_DIR': '/tmp/x'})
case('SAS phy +101 over the soak: exit 4', rc == 4 and 'SAS phy p1.0.invalid_dword 0 -> 101' in csv_of(e, 't5b'))
e = FakeEnv(shelf(), events={5: phy_up(30)})
rc = ds.main(['t5c', 'dataPool', 'seq:30'], e, {'CSV_DIR': '/tmp/x', 'PHY_JUMP': '20'})
case('PHY_JUMP env 20: +30 stops', rc == 4)

# 6. SATA pending / realloc, NVMe media errors
mg = [Dev(f'sd{c}', f'X7U{c.upper()}FSYC', 'TOSHIBA MG04ACA400N', 'ata', 40) for c in 'bcde']
e = FakeEnv(mg, pool='backupPool', host='sojiro', fan_files=False,
            events={3: lambda env: setattr(env.devs['/dev/sdc'], 'pending', 8)})
rc = ds.main(['t6', 'backupPool', 'seq:60', '50'], e, {'CSV_DIR': '/tmp/x'})
case('SATA Current_Pending_Sector 0 -> 8: exit 4 at the 10-min check', rc == 4 and 'Current_Pending_Sector 0 -> 8' in csv_of(e, 't6'))
mg = [Dev(f'sd{c}', f'X7U{c.upper()}FSYC', 'TOSHIBA MG04ACA400N', 'ata', 40) for c in 'bcde']
e = FakeEnv(mg, pool='backupPool', host='sojiro', fan_files=False,
            events={3: lambda env: setattr(env.devs['/dev/sdb'], 'realloc', 1)})
rc = ds.main(['t6b', 'backupPool', 'rand:60', '50'], e, {'CSV_DIR': '/tmp/x'})
case('SATA Reallocated_Sector_Ct +1: exit 4', rc == 4)
mg = [Dev(f'sd{c}', f'X7U{c.upper()}FSYC', 'TOSHIBA MG04ACA400N', 'ata', 40) for c in 'bcde']
e = FakeEnv(mg, pool='backupPool', host='sojiro', fan_files=False,
            events={3: lambda env: setattr(env.devs['/dev/sdb'], 'temp', 50)})
rc = ds.main(['t6c', 'backupPool', 'seq:60'], e, {'CSV_DIR': '/tmp/x'})
case('MG04 at 50C: exit 3', rc == 3 and '(stop 50C, 2 reads' in csv_of(e, 't6c'))
nv = [Dev('nvme1n1', '252050173620', 'CT1000P3PSSD8', 'nvme', 31, rota=False)]
e = FakeEnv(nv, pool='nvmePool', host='tinynas', fan_files=False,
            events={4: lambda env: setattr(env.devs['/dev/nvme1n1'], 'media', 1)})
rc = ds.main(['t6d', 'nvmePool', 'rand:30'], e, {'CSV_DIR': '/tmp/x'})
c = csv_of(e, 't6d')
case('NVMe stop line = warning 83 - 5 = 78; media error +1: exit 4', rc == 4 and 'stop 78C' in c and 'NVMe media errors 0 -> 1' in c)
nvsmart = [x for x in e.log if x[1].startswith('smartctl -A') and 'standby' not in x[1]]
case('NVMe read without -n standby', len(nvsmart) > 0)

# 7. fan caps: one read over -> note only; two in a row -> exit 5; auto counts as over; stale -> exit 5
def shelf_to(p):
    return lambda env: env.set_fans(shelf=p)
e = FakeEnv(shelf(), events={10.5: shelf_to(26), 11.5: shelf_to(12)})
rc = ds.main(['t7a', 'dataPool', 'seq:30'], e, {'CSV_DIR': '/tmp/x', 'FAN_CAP_SHELF': '25'})
c = csv_of(e, 't7a')
case('shelf 26% on one read: note, no stop', rc == 0 and 'above the cap 25% (1 read; stops on the next)' in c, c[-400:])


class Hold:
    def __init__(self, **kw):
        self.kw = kw

    def __call__(self, env):
        env.set_fans(**self.kw)
        env.frozen = True
e = FakeEnv(shelf(), events={10.5: Hold(shelf=26)})
rc = ds.main(['t7b', 'dataPool', 'seq:30'], e, {'CSV_DIR': '/tmp/x', 'FAN_CAP_SHELF': '25'})
c = csv_of(e, 't7b')
case('shelf 26% on two reads in a row: exit 5', rc == 5 and 'STOP: seq: fan cap: shelf fans 26% above the cap 25%' in c, c[-300:])
e = FakeEnv(shelf(), events={7.5: Hold(r720='auto, waiting to cool')})
rc = ds.main(['t7c', 'vmPool', 'seq:30'], e, {'CSV_DIR': '/tmp/x', 'FAN_CAP_R720': '24'})
case('R720 in iDRAC auto counts as over the cap: exit 5', rc == 5 and 'in iDRAC auto' in csv_of(e, 't7c'))
e = FakeEnv(shelf(), events={7.5: lambda env: setattr(env, 'frozen', True)})
rc = ds.main(['t7d', 'vmPool', 'seq:30'], e, {'CSV_DIR': '/tmp/x', 'FAN_CAP_R720': '24'})
c = csv_of(e, 't7d')
stop = [l for l in c.splitlines() if 'STOP' in l]
case('fan-watchdog state stale (> 300 s) twice: exit 5 about 6-7 min after it froze', rc == 5 and 'stale' in c
     and stop and 13 * 60 <= int(stop[0].split()[1]) - T0 <= 15 * 60, stop)
e = FakeEnv(shelf(), events={7.5: lambda env: env.set_fans(r720='24%')})
rc = ds.main(['t7e', 'vmPool', 'seq:20'], e, {'CSV_DIR': '/tmp/x', 'FAN_CAP_R720': '24'})
case('R720 at exactly the cap (24%): no stop', rc == 0)
e = FakeEnv(shelf(), fan_files=False)
rc = ds.main(['t7f', 'dataPool', 'seq:30'], e, {'CSV_DIR': '/tmp/x', 'FAN_CAP_SHELF': '25'})
case('cap set but no controller state at the start: refused (exit 2), no fio', rc == 2 and not e.procs)
# fallback to lab_thermal.prom when the state files are missing
e = FakeEnv(shelf(), fan_files=False)
prom = '/var/lib/node_exporter/textfile_collector/lab_thermal.prom'
e.files[prom] = ('lab_controller_state_age_seconds{controller="fan-watchdog"} 12\nlab_r720_fan_auto 0\nlab_r720_fan_percent 30\n'
                 'lab_controller_state_age_seconds{controller="md1200-fan"} 5\nlab_md1200_fan_percent 11\n')
e.mtimes[prom] = T0
e.frozen = True
rc = ds.main(['t7g', 'vmPool', 'seq:30'], e, {'CSV_DIR': '/tmp/x', 'FAN_CAP_SHELF': '25', 'FAN_CAP_R720': '24'})
case('lab_thermal.prom fallback: R720 30% over 24 stops (but the prom file goes stale too)', rc == 5, csv_of(e, 't7g')[-300:])

# 8. never-touch serials and makoto
rb = [Dev('sdb', '67H5K3L0FSZC', 'TOSHIBA MG04ACA200N', 'ata', 36), Dev('sdd', 'X7UQK5XLFSYC', 'TOSHIBA MG04ACA400N', 'ata', 40)]
e = FakeEnv(rb, pool='computePool', host='ryuji', fan_files=False)
rc = ds.main(['t8', 'computePool', 'rand:30'], e, {'CSV_DIR': '/tmp/x'})
case("pool holding one of sojiro's old drives: refused, no fio, no SMART read of it", rc == 2 and not e.procs
     and not any('sdb' in x[1] and 'smartctl' in x[1] for x in e.log) and 'never-touch' in csv_of(e, 't8'))
e = FakeEnv(shelf(), host='makoto', fan_files=False)
rc = ds.main(['t8b', 'backupPool', 'seq:30'], e, {'CSV_DIR': '/tmp/x'})
case('makoto: refused', rc == 2 and not e.procs)
e = FakeEnv(shelf(), pool_state='DEGRADED')
rc = ds.main(['t8c', 'dataPool', 'seq:30'], e, {'CSV_DIR': '/tmp/x'})
case('pool not ONLINE: refused', rc == 2 and not e.procs)

# 9. LOAD_UNTIL mid-phase and before a phase
e = FakeEnv(shelf())
rc = ds.main(['t9', 'dataPool', 'seq:60,rand:60'], e, {'CSV_DIR': '/tmp/x', 'LOAD_UNTIL': str(T0 + 30 * 60 + 10)})
c = csv_of(e, 't9')
case('LOAD_UNTIL mid-phase: load off at ~31 min, exit 0, second phase never starts', rc == 0 and 'LOAD_UNTIL passed' in c
     and len([x for x in e.log if x[1].startswith('fio start')]) == 1)
e = FakeEnv(shelf())
rc = ds.main(['t9b', 'dataPool', 'seq:60'], e, {'CSV_DIR': '/tmp/x', 'LOAD_UNTIL': str(T0 - 1)})
case('past LOAD_UNTIL at start: no fio', rc == 0 and not e.procs and 'not started' in csv_of(e, 't9b'))

# 10. watch-only aux devices (log/cache SSD): read, never loaded; a hot watched SSD still stops at its class line
aux = [Dev('sdc', '2MW3LJMA', 'HUSMM8080ASS20', 'sas', 43, rota=False)]
e = FakeEnv(shelf(2), aux=aux, events={6: lambda env: setattr(env.devs['/dev/sdc'], 'temp', 60)})
rc = ds.main(['t10', 'vmPool', 'seq:30'], e, {'CSV_DIR': '/tmp/x'})
c = csv_of(e, 't10')
job = [x for x in e.log if x[1].startswith('fio start')]
case('log/cache SSD watched only (not in the fio job), watch-list note, stops at HUSMM 60C', rc == 3 and 'watched only' in c
     and 'WATCH LIST: mementos rear SSD' in c and 'sdc 2MW3LJMA 60C (stop 60C, 2 reads' in c)
case('fio job never names the watched SSD', e.jobs and all('sdc' not in j for j in e.jobs) and all('/dev/sdab' in j for j in e.jobs))

# 11. a loaded disk that stops answering SMART: two failed health reads -> exit 4; no temperature 3x -> exit 3
def brk(env):
    env.devs['/dev/sdab'].broken = True
e = FakeEnv(shelf(), events={2: brk})
rc = ds.main(['t11', 'dataPool', 'seq:60'], e, {'CSV_DIR': '/tmp/x'})
c = csv_of(e, 't11')
case('loaded disk without temperature for 3 reads: exit 3', rc == 3 and 'no temperature for 3 reads' in c, c[-300:])

# 12. drive in standby at the start: baseline filled later, no false stop
mg = [Dev(f'sd{c}', f'X7U{c.upper()}FSYC', 'TOSHIBA MG04ACA400N', 'ata', 40) for c in 'bcde']
mg[0].standby = True
e = FakeEnv(mg, pool='backupPool', host='sojiro', fan_files=False, events={0.5: lambda env: setattr(env.devs['/dev/sdb'], 'standby', False)})
rc = ds.main(['t12', 'backupPool', 'seq:30'], e, {'CSV_DIR': '/tmp/x'})
case('drive in standby at the start: no false stop', rc == 0, csv_of(e, 't12')[-300:])

# 13. fio dies early: noted, next phase runs
e = FakeEnv(shelf())
e.fio_die_at = 120
rc = ds.main(['t13', 'dataPool', 'seq:30,rand:10'], e, {'CSV_DIR': '/tmp/x'})
case('fio ending early is noted ("ended early")', 'ended early' in csv_of(e, 't13'))

# 14. selftest: no fio, no files written
e = FakeEnv(shelf(), aux=[Dev('sdc', '2MW3LJMA', 'HUSMM8080ASS20', 'sas', 43, rota=False)])
rc = ds.main(['--selftest', 'st', 'dataPool', 'seq:60', '54'], e, {'CSV_DIR': '/tmp/x', 'FAN_CAP_SHELF': '25'})
case('selftest: exit 0, no fio, no CSV, prints devices and the job', rc == 0 and not e.procs and not csv_of(e, 'st')
     and any('fio job' in o for o in e.outs) and any('ZA150000' in o for o in e.outs))
case('selftest: fio --readonly --parse-only on the job (rc 0), job file removed', any(x[1] == 'fio parse-only' for x in e.log)
     and any('argv check seq: fio --readonly --parse-only rc 0' in o for o in e.outs) and not any(k.endswith('.fio') for k in e.files))

# 15. glitch: one read at the stop line, then back down: no stop; one read at stop + 5: immediate abort
def glitch_on(env):
    env.devs['/dev/sdab'].temp = 54
def glitch_off(env):
    env.devs['/dev/sdab'].temp = 46
e = FakeEnv(shelf(), events={5.5: glitch_on, 6.5: glitch_off})
rc = ds.main(['t15', 'dataPool', 'seq:20'], e, {'CSV_DIR': '/tmp/x'})
c = csv_of(e, 't15')
case('one read at the stop line (glitch): noted, no stop', rc == 0 and '(1 read; stops on the next)' in c, c[-300:])
e = FakeEnv(shelf(), events={5.5: lambda env: setattr(env.devs['/dev/sdab'], 'temp', 59)})
rc = ds.main(['t15b', 'dataPool', 'seq:20'], e, {'CSV_DIR': '/tmp/x'})
c = csv_of(e, 't15b')
stop = [l for l in c.splitlines() if 'STOP' in l]
case('one read at stop + 5 (59C, the abort line): immediate exit 3', rc == 3 and 'abort line 59C' in c
     and stop and int(stop[0].split()[1]) - T0 <= 6 * 60 + 30, stop)

# 16. a watched (not loaded) SSD that vanishes for 3 reads stops; a watched HDD asleep does not
aux = [Dev('sdc', '2MW3LJMA', 'HUSMM8080ASS20', 'sas', 43, rota=False)]
e = FakeEnv(shelf(2), aux=aux, events={4: lambda env: setattr(env.devs['/dev/sdc'], 'broken', True)})
rc = ds.main(['t16', 'vmPool', 'seq:30'], e, {'CSV_DIR': '/tmp/x'})
case('watched SSD without temperature for 3 reads: exit 3', rc == 3 and 'sdc 2MW3LJMA: no temperature' in csv_of(e, 't16'))
spare = Dev('sdz', 'SPARE001', 'ST1200MM0007', 'sas', 30)
e = FakeEnv(shelf(2), aux=[spare], events={2: lambda env: setattr(env.devs['/dev/sdz'], 'standby', True)})
rc = ds.main(['t16b', 'vmPool', 'seq:20'], e, {'CSV_DIR': '/tmp/x'})
case('watched HDD asleep (standby) is not a vanished sensor', rc == 0, csv_of(e, 't16b')[-300:])

# 17. review B2: a disk at its stop line whose reads fail every other minute still stops (old code reset the count)
def flaky_hot(env):
    d = env.devs['/dev/sdab']
    d.temp = 55
    env.flaky = True
class FlakyEnv(FakeEnv):
    def run(self, args, timeout=90):
        if getattr(self, 'flaky', False) and args[0] == 'smartctl' and args[-1] == '/dev/sdab' and '-A' in args:
            self.flip = not getattr(self, 'flip', False)
            if self.flip:
                return 2, 'read failed\n'
        return super().run(args, timeout)
e = FlakyEnv(shelf(), events={5.5: flaky_hot})
rc = ds.main(['t17', 'dataPool', 'seq:30'], e, {'CSV_DIR': '/tmp/x'})
c = csv_of(e, 't17')
case('review B2: at the stop line with every other read missing: still stops (exit 3)', rc == 3 and '2 reads in a row' in c, c[-300:])

# 18. review M9: a set value that does not parse refuses
e = FakeEnv(shelf())
rc = ds.main(['t18', 'dataPool', 'seq:30'], e, {'CSV_DIR': '/tmp/x', 'FAN_CAP_SHELF': '25%'})
case('review M9: FAN_CAP_SHELF=25% refuses (exit 2), no fio', rc == 2 and not e.procs and 'do not parse' in csv_of(e, 't18'))
e = FakeEnv(shelf())
rc = ds.main(['t18b', 'dataPool', 'seq:30'], e, {'CSV_DIR': '/tmp/x', 'LOAD_UNTIL': '2026-10-20 15:58'})
case('review M9: LOAD_UNTIL as a date string refuses', rc == 2 and not e.procs)

# 19. review M10: fan-watchdog state missing, textfile in iDRAC auto (no percent line): no crash, auto = over the cap
e = FakeEnv(shelf(), fan_files=False)
prom = '/var/lib/node_exporter/textfile_collector/lab_thermal.prom'
e.files[prom] = ('lab_controller_state_age_seconds{controller="fan-watchdog"} 12\nlab_r720_fan_auto 1\n'
                 'lab_controller_state_age_seconds{controller="md1200-fan"} 5\nlab_md1200_fan_percent 11\n')
e.mtimes[prom] = T0
class FreshProm(FakeEnv):
    pass
def touch(env):
    env.mtimes[prom] = env.t
e.events = sorted({m / 2: touch for m in range(1, 60)}.items())
e.frozen = True        # keep the state files absent: the textfile is the only source
try:
    rc = ds.main(['t19', 'vmPool', 'seq:30'], e, {'CSV_DIR': '/tmp/x', 'FAN_CAP_R720': '24'})
    ok = rc == 5 and 'in iDRAC auto' in csv_of(e, 't19')
except TypeError as ex:
    ok, rc = False, f'TypeError {ex}'
case('review M10: textfile fallback in iDRAC auto: no crash, exit 5 on 2 reads', ok, rc)

# 20. review M11: fio runtime capped at LOAD_UNTIL
e = FakeEnv(shelf())
rc = ds.main(['t20', 'dataPool', 'seq:60'], e, {'CSV_DIR': '/tmp/x', 'LOAD_UNTIL': str(T0 + 1200)})
case('review M11: fio runtime = time to LOAD_UNTIL (1200 s), not the 3600 s phase', e.jobs and 'runtime=1200' in e.jobs[0], e.jobs[0][:200] if e.jobs else '')

# 21. review M12: a loaded disk with no serial refuses
nos = shelf()
nos[1].serial = ''
e = FakeEnv(nos)
rc = ds.main(['t21', 'dataPool', 'seq:30'], e, {'CSV_DIR': '/tmp/x'})
case('review M12: a data disk with no serial refuses', rc == 2 and not e.procs and 'no serial' in csv_of(e, 't21'))

# 22. shelf enclosure stop lines from md1200-fan's state (dataPool only): backplane 48 / SIM 60 / expander 88 on 2 reads,
#     52 / 64 / 92 on one; a stale or missing state stops after 60 s blind; refused without a fresh state at the start
def shelf_set(**kw):
    def f(env):
        env.shelf_temps.update(kw)
    return f
e = FakeEnv(shelf(), events={8.5: shelf_set(backplane=48)})
rc = ds.main(['t22', 'dataPool', 'seq:30'], e, {'CSV_DIR': '/tmp/x'})
c = csv_of(e, 't22')
st = [l for l in c.splitlines() if 'STOP' in l]
case('shelf backplane 48 on 2 reads: exit 3', rc == 3 and st and 'shelf backplane 48C (stop 48C, 2 reads in a row)' in st[0]
     and 9 * 60 <= int(st[0].split()[1]) - T0 <= 11 * 60, st)
hdr = c.splitlines()[0].split(',')
row = [l for l in c.splitlines() if l and not l.startswith('#')][3].split(',')
case('CSV logs shelf_backplane / shelf_sim / shelf_expander', 'shelf_backplane' in hdr and row[hdr.index('shelf_expander')] == '81'
     and row[hdr.index('shelf_sim')] == '52', dict(zip(hdr, row)))
e = FakeEnv(shelf(), events={8.5: shelf_set(backplane=48), 9.5: shelf_set(backplane=45)})
rc = ds.main(['t22b', 'dataPool', 'seq:20'], e, {'CSV_DIR': '/tmp/x'})
case('shelf backplane 48 on one read: note, no stop', rc == 0 and 'shelf backplane 48C at its stop line 48C (1 read' in csv_of(e, 't22b'))
for k, v, label in (('SIM', 64, 'SIM 64'), ('expander', 92, 'expander 92'), ('backplane', 52, 'backplane 52')):
    e = FakeEnv(shelf(), events={8.5: shelf_set(**{k: v})})
    rc = ds.main(['t22c', 'dataPool', 'seq:20'], e, {'CSV_DIR': '/tmp/x'})
    st = [l for l in csv_of(e, 't22c').splitlines() if 'STOP' in l]
    case(f'shelf {label} (abort line): one read stops (exit 3)', rc == 3 and st and f'shelf {label}C (abort line' in st[0]
         and int(st[0].split()[1]) - T0 <= 9 * 60 + 30, st)
    e.files.pop('/tmp/x/disk-soak-t22c.csv', None)
e = FakeEnv(shelf(), events={8.5: shelf_set(SIM=60), 9.5: shelf_set(SIM=61)})
rc = ds.main(['t22d', 'dataPool', 'seq:20'], e, {'CSV_DIR': '/tmp/x'})
case('shelf SIM 60 then 61: exit 3 on the 2nd read', rc == 3 and 'shelf SIM 61C (stop 60C, 2 reads in a row)' in csv_of(e, 't22d'))
e = FakeEnv(shelf(), events={8.5: lambda env: setattr(env, 'frozen', True)})
rc = ds.main(['t22e', 'dataPool', 'seq:30'], e, {'CSV_DIR': '/tmp/x'})
st = [l for l in csv_of(e, 't22e').splitlines() if 'STOP' in l]
case('md1200-fan state stops updating: stale after 120 s, then 60 s blind stops (exit 3)', rc == 3 and st
     and 'no fresh md1200-fan state' in st[0] and int(st[0].split()[1]) - T0 <= 12 * 60, st)
def md_gone(env):
    env.frozen = True
    env.files.pop('/run/md1200-fan.state', None)
e = FakeEnv(shelf(), events={8.5: md_gone})
rc = ds.main(['t22f', 'dataPool', 'seq:30'], e, {'CSV_DIR': '/tmp/x'})
st = [l for l in csv_of(e, 't22f').splitlines() if 'STOP' in l]
case('md1200-fan state file gone: stops on the next sample (blind 60 s)', rc == 3 and st and 'no fresh md1200-fan state' in st[0]
     and int(st[0].split()[1]) - T0 <= 10 * 60, st)
def partial(env):
    env.md_fail = 1
e = FakeEnv(shelf(), events={m + 0.5: partial for m in range(2, 20, 3)})
rc = ds.main(['t22g', 'dataPool', 'seq:20'], e, {'CSV_DIR': '/tmp/x'})
case('a state caught mid-write is read again (3 tries): no stop', rc == 0, csv_of(e, 't22g')[-300:])
e = FakeEnv(shelf(), fan_files=False)
e.frozen = True        # the fake must not create the state during the read retries
rc = ds.main(['t22h', 'dataPool', 'seq:30'], e, {'CSV_DIR': '/tmp/x'})
case('dataPool soak without md1200-fan state at the start: refused (exit 2), no fio', rc == 2 and not e.procs
     and 'backplane/SIM/expander stop lines could not act' in csv_of(e, 't22h'))
e = FakeEnv(shelf(), events={5.5: shelf_set(backplane=55)})
rc = ds.main(['t22i', 'vmPool', 'seq:20'], e, {'CSV_DIR': '/tmp/x'})
case('vmPool soak: shelf enclosure lines not applied (exit 0), columns empty', rc == 0
     and [l for l in csv_of(e, 't22i').splitlines() if l and not l.startswith('#')][2].split(',')[10] == '')

bad = [n for n, ok in RESULTS if not ok]
print(f'\n{len(RESULTS) - len(bad)}/{len(RESULTS)} passed' + (f'; FAILED: {bad}' if bad else ''))
sys.exit(1 if bad else 0)
