#!/usr/bin/env python3
# Fake-clock dry runs of lab-load.py against fake hosts built from the S0 survey's own sensors-<host>.json (fixtures/; the real
# hwmon chips, labels, devices and thermal zones of each box), with the real profile and plan files from
# scripts/lab-load/. Fake: sysfs reads, /proc/stat, RAPL, smartctl, lsblk, zpool, ipmitool, nvidia-smi,
# systemctl --user, HTTP (HA, Prometheus), stress-ng and fio. A CPU model warms the package with the workers.
# usage: python3 -I tests/test_lab_load.py [-v]
import fnmatch, importlib.util, json, os, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
exec(open(os.path.join(HERE, 'guard.py')).read())   # any real subprocess/network call now raises
spec = importlib.util.spec_from_file_location('lab_load', os.path.join(HERE, '..', 'lab-load.py'))
ll = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ll)
VERBOSE = '-v' in sys.argv
SURVEY = os.path.join(HERE, 'fixtures')        # the 10-19 S0 survey's sensors-<host>.json (DMI removed)
PROFILE = os.path.join(HERE, '..', 'lab-load', 'lab-load-profile.json')
PLANS = {n: os.path.join(HERE, '..', 'lab-load', f'lab-load-plan-{n}.json') for n in ('t3', 't4', 'w1', 'wmk')}
T1315 = time.mktime(time.strptime('2026-10-20 13:15', '%Y-%m-%d %H:%M'))
T1425 = time.mktime(time.strptime('2026-10-20 14:25', '%Y-%m-%d %H:%M'))
T1525 = time.mktime(time.strptime('2026-10-20 15:25', '%Y-%m-%d %H:%M'))
HEAT = {'futaba': 25, 'morgana': 40, 'yusuke': 40, 'tinynas': 35, 'sojiro': 15, 'tinypc': 45, 'makoto': 20}
MK_STATE, MK_TF = '/run/makoto-fan.state', '/var/lib/prometheus/node-exporter/ipmitool_sensor.prom'
CG = '/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service'   # C at all threads
POOLS = {'tinynas': {'homePool': ['PN2338P4HASBJC', 'PN1334PCKSXVZS', 'PN2338P4H9UPLC', 'PN1334PCKSK5PS',
                                  'PN2338P4HAZR9C', 'PN2338P4HAPSEC', 'PN2334PCKTSADB', 'PN2338P4HAS7JC'],
                     'nvmePool': ['252050173620']},
         'sojiro': {'backupPool': ['X7UTK3EHFSYC', 'X7UQK5XKFSYC', 'X7UDK2CXFSYC', 'X7UQK5XJFSYC']}}


STRESS_OPTS = {'--cpu': r'[1-9]\d*', '--cpu-method': r'matrixprod', '--timeout': r'\d+s', '--temp-path': r'/\S*',
               '--quiet': None, '--dry-run': None}     # what this run's stress-ng 0.17.06 / 0.22.01 accept


def stress_argv_ok(argv):
    """True if argv (from 'stress-ng' on) uses only the options above, with valid values (no --matrixprod)."""
    a = argv[argv.index('stress-ng') + 1:]
    i = 0
    while i < len(a):
        if a[i] not in STRESS_OPTS:
            return False
        if STRESS_OPTS[a[i]] is not None:
            if i + 1 >= len(a) or not re.fullmatch(STRESS_OPTS[a[i]], a[i + 1]):
                return False
            i += 2
        else:
            i += 1
    return '--cpu' in a and '--cpu-method' in a


class FakeProc:
    def __init__(self, env, args):
        self.env, self.args, self.killed, self.t0 = env, args, False, env.t
        self.pid = 4000 + len(env.procs)
        self.leader_dies_at = None          # the main process exits early; its group may live on
        if 'stress-ng' in args and not stress_argv_ok(args):
            self.leader_dies_at = env.t     # like the real 0.17.06: "unrecognized option", rc 1, no load

    def poll(self):
        if self.killed:
            return -15
        if self.leader_dies_at is not None and self.env.t >= self.leader_dies_at:
            return 1
        return None


class FakeHost(ll.Env):
    def __init__(self, host, t0=T1315, events=None):
        self.host, self.t = host, t0
        self.j = json.load(open(os.path.join(SURVEY, f'sensors-{host}.json')))
        self.threads = {'futaba': 4, 'morgana': 8, 'yusuke': 16, 'tinynas': 12, 'sojiro': 8, 'tinypc': 20, 'makoto': 8}[host]
        self.intel = host in ('futaba', 'morgana', 'sojiro', 'tinypc', 'makoto')
        self.mk = {'card': 49.0, 'ddr': 52.0, 'mb': 45.0, 'cpu': 65.0, 'fan1': 24, 'fan4': 37}   # makoto-fan state
        self.tf = {'Card Side Temp': 50.0, 'DDR4_A Temp': 53.0, 'DDR4_B Temp': 51.0, 'MB Temp': 45.0, 'CPU1 Temp': 67.0}
        self.st_age = self.tf_age = 0
        self.journal = []                # (epoch, line) in mirror-voice's journal
        self.journal_ok = True
        self.mkfan = 'active'            # systemctl is-active makoto-fan
        self.mk_emergency = False
        self.mk_drop = set()             # keys missing from makoto-fan's state
        self.events = sorted((events or {}).items())
        self.files, self.procs, self.calls, self.outs = {}, [], [], []
        self.heat = 0.0
        self.override = {}            # (chip, label) or ('zone', type) or ('drive', serial) or ('ipmi', name) -> value
        self.throttle_core = 0
        self.ha_s, self.prom_ready, self.up0 = 0.2, 200, 1
        self.user_units = {'mirror-voice-sat': 'active', 'whisper-gpu': 'active'}   # -> their cgroups (tinypc)
        self.unit_slice = {'mirror-voice-sat': 'app.slice', 'whisper-gpu': 'app.slice'}
        self.events_ok = True            # cgroup.events readable
        self.cg_reads = 0
        self.ipmi_ok = True
        self.pending = {}
        self.media = {}
        self.kills = []
        self.throttle_ok = True
        self.stat = [0, 0]
        self.energy = 0
        self.dev_of = {}
        for f in [PROFILE] + list(PLANS.values()):
            self.files[f] = open(f).read()          # the real profile and plans, served by the fake read()
        for i, d in enumerate(self.j['drives']):
            self.dev_of[d['serial']] = f'/dev/{d["dev"]}'

    # ---------- clock and physics
    def now(self):
        return self.t

    def sleep(self, s):
        end = self.t + s
        while self.events and self.events[0][0] <= end:
            at, fn = self.events.pop(0)
            self._adv(max(0, at - self.t))
            fn(self)
        self._adv(end - self.t)

    def workers(self):
        return sum(int(p.args[p.args.index('--cpu') + 1]) for p in self.procs
                   if not p.killed and '--cpu' in p.args and p.poll() is None)

    def _adv(self, dt):
        if dt <= 0:
            return
        frac = min(1.0, self.workers() / self.threads)
        target = HEAT[self.host] * frac
        k = min(1.0, dt / 60.0)
        self.heat += (target - self.heat) * k
        busy = frac
        self.stat[0] += int(100 * self.threads * dt)
        self.stat[1] += int(100 * self.threads * dt * (1 - busy))
        self.energy += int((5 + 60 * frac) * dt * 1e6)
        self.t += dt
        if self.host == 'makoto':
            self.mk['card'] = self.override.get(('mk', 'card'), 49.0 + 5 * frac)
            self.tf['Card Side Temp'] = self.override.get(('tf', 'card'), 50.0 + 5 * frac)

    # ---------- sysfs
    def _hw(self):
        return self.j['hwmon']

    def glob(self, pattern):
        paths = []
        for c in self._hw():
            h = f'/sys/class/hwmon/{c["hwmon"]}'
            paths.append(h)
            for t in c['temps']:
                paths.append(f'{h}/{t["id"]}_input')
        for z in self.j['thermal_zones']:
            paths.append(f'/sys/class/thermal/{z["zone"]}')
        for i in range(self.threads):
            paths.append(f'/sys/devices/system/cpu/cpu{i}/cpufreq/scaling_cur_freq')
            if self.intel:
                paths.append(f'/sys/devices/system/cpu/cpu{i}/thermal_throttle/core_throttle_count')
                paths.append(f'/sys/devices/system/cpu/cpu{i}/thermal_throttle/package_throttle_count')
        paths.append('/sys/class/powercap/intel-rapl:0')
        if self.host == 'tinypc':
            for u, st in self.user_units.items():
                if st != 'gone':
                    paths.append(f'{CG}/{self.unit_slice[u]}/{u}.service')
            paths.append(f'{CG}/app.slice/other.service')
        return sorted(p for p in paths if fnmatch.fnmatch(p, pattern))

    def uid(self, user):
        if user != 'rohit':
            raise KeyError(user)
        return 1000

    def read(self, path):
        if path in self.files:
            return self.files[path]
        if path.startswith(CG + '/') and self.host == 'tinypc':
            self.cg_reads += 1
            unit = path.split('/')[-2][:-len('.service')]
            st = self.user_units.get(unit, 'active' if unit == 'other' else 'gone')
            if st == 'gone':
                raise OSError(path)
            if path.endswith('cgroup.events'):
                if not self.events_ok:
                    raise OSError(path)
                return f'populated {1 if st == "active" else 0}\nfrozen 0\n'
            if path.endswith('cgroup.procs'):
                return '2154\n2201\n' if st == 'active' else ''
            raise OSError(path)
        if path == MK_STATE and self.host == 'makoto':
            d = dict(self.mk, t=int(self.t - self.st_age), nvme=48.85, emergency=self.mk_emergency)
            for k in self.mk_drop:
                d.pop(k, None)
            return json.dumps(d)
        if path == MK_TF and self.host == 'makoto':
            return ''.join(f'node_ipmi_temperature_celsius{{sensor="{k}"}} {v:.6f}\n' for k, v in self.tf.items()) + \
                'node_ipmi_speed_rpm{sensor="FAN1"} 3200.000000\n'
        if path == '/proc/stat':
            return f'cpu  {self.stat[0] - self.stat[1]} 0 0 {self.stat[1]} 0 0 0 0 0 0\ncpu0 1 1 1 1\n'
        m = re.match(r'/sys/class/hwmon/(hwmon\d+)/(name|temp(\d+)_input|temp(\d+)_label)$', path)
        if m:
            c = next(c for c in self._hw() if c['hwmon'] == m.group(1))
            if m.group(2) == 'name':
                return c['name'] + '\n'
            tid = f'temp{m.group(3) or m.group(4)}'
            t = next((t for t in c['temps'] if t['id'] == tid), None)
            if t is None:
                raise OSError(path)
            if m.group(4):
                if t['label'] is None:
                    raise OSError(path)
                return t['label'] + '\n'
            key = (c['name'], t['label'] or t['id'])
            if key in self.override:
                v = self.override[key]
            else:
                v = t['input']
                if v is not None and (c['name'] in ('coretemp', 'k10temp')):
                    v += self.heat
            if v is None:
                raise OSError(path)
            return f'{int(round(v * 1000))}\n'
        m = re.match(r'/sys/class/thermal/(thermal_zone\d+)/(type|temp)$', path)
        if m:
            z = next(z for z in self.j['thermal_zones'] if z['zone'] == m.group(1))
            if m.group(2) == 'type':
                return z['type'] + '\n'
            v = self.override.get(('zone', z['type']), z['temp'])
            if v is None:
                raise OSError(path)
            return f'{int(v * 1000)}\n'
        if path.endswith('scaling_cur_freq'):
            return '3000000\n' if self.workers() else '800000\n'
        if 'thermal_throttle' in path and not self.throttle_ok:
            raise OSError(path)
        if path.endswith('core_throttle_count'):
            return f'{self.throttle_core if path.startswith("/sys/devices/system/cpu/cpu0/") else 0}\n'
        if path.endswith('package_throttle_count'):
            return '0\n'
        if path == '/sys/class/powercap/intel-rapl:0/name':
            return 'package-0\n'
        if path == '/sys/class/powercap/intel-rapl:0/energy_uj':
            return f'{self.energy}\n'
        raise OSError(path)

    def realpath(self, path):
        m = re.match(r'/sys/class/hwmon/(hwmon\d+)/device$', path)
        if m:
            c = next(c for c in self._hw() if c['hwmon'] == m.group(1))
            return '/sys/devices/' + c['device']
        m = re.match(r'/dev/disk/by-id/wwn-(\S+)$', path)
        if m:
            return self.dev_of[m.group(1)]
        if path == '/dev/disk/by-id/nvme-eui.000000000000000100a0752550173620':
            return '/dev/nvme1n1'
        return path

    def exists(self, path):
        return path in self.files

    def mtime(self, path):
        if path == MK_STATE:
            return self.t - self.st_age
        if path == MK_TF:
            return self.t - self.tf_age
        if path in self.files:
            return self.t
        raise OSError(path)

    def write(self, path, text, mode='a'):
        self.files[path] = (self.files.get(path, '') if mode == 'a' else '') + text

    def remove(self, path):
        self.files.pop(path, None)

    def hostname(self):
        return self.host

    # ---------- commands
    def run(self, args, timeout=60):
        a = list(args)
        self.calls.append(a)
        if a[0] == 'lsblk':
            return 0, json.dumps({'blockdevices': [{'name': d['dev'], 'serial': d['serial'], 'model': d['model'],
                                                    'tran': d['tran']} for d in self.j['drives']]})
        if a[0] == 'smartctl':
            dev = a[-1]
            d = next(d for d in self.j['drives'] if f'/dev/{d["dev"]}' == dev)
            t = self.override.get(('drive', d['serial']), d['temp'])
            if t is None:
                return 2, 'Smartctl open device failed\n'
            if dev.startswith('/dev/nvme'):
                assert '-n' not in a, a
                return 0, (f'Critical Warning:                   0x00\nTemperature:                        {t} Celsius\n'
                           f'Media and Data Integrity Errors:    {self.media.get(d["serial"], 0)}\n')
            p = self.pending.get(d['serial'], 0)
            return 0, ('ID# ATTRIBUTE_NAME          FLAG     VALUE WORST THRESH TYPE      UPDATED  WHEN_FAILED RAW_VALUE\n'
                       '  5 Reallocated_Sector_Ct   0x0033   100   100   050    Pre-fail  Always       -       0\n'
                       f'194 Temperature_Celsius     0x0022   100   100   000    Old_age   Always       -       {t} (Min/Max 19/51)\n'
                       f'197 Current_Pending_Sector  0x0032   100   100   000    Old_age   Always       -       {p}\n'
                       '199 UDMA_CRC_Error_Count    0x0032   200   200   000    Old_age   Always       -       0\n')
        if a[:3] == ['zpool', 'status', '-P']:
            pool = a[3]
            if pool not in POOLS.get(self.host, {}):
                return 1, f"cannot open '{pool}': no such pool\n"
            lines = [f'  pool: {pool}', ' state: ONLINE', 'config:', f'\t{pool} ONLINE 0 0 0']
            lines += [f'\t    /dev/disk/by-id/wwn-{s}-part1  ONLINE  0 0 0' for s in POOLS[self.host][pool]]
            return 0, '\n'.join(lines) + '\n'
        if a[:2] == ['ipmitool', 'sdr']:
            if not self.ipmi_ok:
                return 1, ''
            cpu = self.override.get(('ipmi', 'CPU0_TEMP'), 66 + self.heat)
            mb = self.override.get(('ipmi', 'MB_TEMP1'), 70 + self.heat * 0.2)
            return 0, (f'CPU0_TEMP        | 21h | ok  |  3.1 | {cpu:.0f} degrees C\n'
                       'DIMM_P0_A0       | 01h | ns  |  7.1 | No Reading\n'
                       f'MB_TEMP1         | 33h | ucr |  7.5 | {mb:.0f} degrees C\n')
        if a[0] == 'stress-ng':
            assert '--dry-run' in a, a
            return (0, '') if stress_argv_ok(a) else (1, "stress-ng: unrecognized option\n")
        if a[:3] == ['fio', '--readonly', '--parse-only']:
            job = self.files.get(a[3], '')
            return (0, '') if job.startswith('[global]') and 'direct=1' in job else (1, 'fio: bad job\n')
        if a[0] == 'nvidia-smi':
            return 0, f'{self.override.get(("gpu", "temp"), 57)}, 0, 52.16, 6\n'
        if '--user' in a or '-M' in a or a[0] in ('machinectl', 'busctl', 'loginctl'):
            raise AssertionError(f'D-Bus / user-session call (fails inside a system service): {a}')
        if a[0] == 'systemctl':
            assert a[1:] == ['is-active', 'makoto-fan'] and self.host == 'makoto', f'systemctl beyond a read: {a}'
            return (0 if self.mkfan == 'active' else 3), self.mkfan + '\n'
        if a[0] == 'journalctl':
            assert a[1] == '--user-unit=mirror-voice.service' and a[2] == '--since' and a[3].startswith('@'), a
            if not self.journal_ok:
                return 1, ''
            since = int(a[3][1:])
            return 0, ''.join(line + '\n' for t, line in self.journal if t >= since)
        if a[0] == 'ipmitool' and self.host == 'makoto':
            raise AssertionError('ipmitool on makoto: makoto-fan owns the BMC')
        raise AssertionError(f'unexpected command {a}')

    def http(self, url, timeout):
        self.calls.append(['http', url])
        if '8123' in url:
            return (200, self.ha_s, b'') if self.ha_s < timeout else (None, timeout, b'')
        if url.endswith('/-/ready'):
            return self.prom_ready, 0.01, b''
        if 'count(up' in url:
            res = [] if self.up0 == 0 else [{'metric': {}, 'value': [self.t, str(self.up0)]}]
            return 200, 0.01, json.dumps({'status': 'success', 'data': {'result': res}}).encode()
        raise AssertionError(url)

    def popen(self, args):
        if 'stress-ng' in args:
            n = int(args[args.index('--cpu') + 1])
            assert n >= 1, 'stress-ng with 0 workers'
            assert args[:3] == ['nice', '-n', '19'] or args[:2] == ['nice', '-n'], args
        if 'fio' in args:
            assert '--readonly' in args, args
            job = self.files[args[-1]]
            assert 'direct=1' in job and 'write' not in job and 'trim' not in job, job
            self.last_job = job
        p = FakeProc(self, args)
        self.procs.append(p)
        return p

    def killgroup(self, proc, sig):
        proc.killed = True
        self.kills.append((proc.args[proc.args.index('nice') + 3] if 'nice' in proc.args else proc.args[0], int(sig)))

    def out(self, text):
        self.outs.append(text)
        if VERBOSE:
            print('   |', text)


RESULTS = []


def case(name, ok, detail=''):
    RESULTS.append((name, ok))
    print(f'{"PASS" if ok else "FAIL"}  {name}' + (f'  ({detail})' if detail and (VERBOSE or not ok) else ''))


def go(host, plan='t3', events=None, t0=T1315, ev=None, argv_extra=()):
    e = FakeHost(host, t0, events)
    vars_ = {'CSV_DIR': '/tmp/x', 'RUN_DIR': '/run'}
    vars_.update(ev or {})
    rc = ll.main(list(argv_extra) + [f'{plan}{host}', PROFILE, PLANS[plan]], e, vars_)
    csv = e.files.get(f'/tmp/x/lab-load-{plan}{host}.csv', '')
    return rc, e, csv


def rows(csv):
    lines = [l for l in csv.splitlines() if l and not l.startswith('#')]
    if not lines:
        return []
    hdr = lines[0].split(',')
    return [dict(zip(hdr, l.split(','))) for l in lines[1:]]


def notes(csv):
    return [l for l in csv.splitlines() if l.startswith('#')]


# 1. every host: discovery from the real survey layout, a full T3 (or T4) plan without trouble, exit 0
def plan_end(host, plan):
    steps = json.load(open(PLANS[plan]))[host]
    return max(time.mktime(time.strptime(x['until'], '%Y-%m-%d %H:%M')) for x in steps)


for host, plan in (('morgana', 't3'), ('yusuke', 't3'), ('futaba', 't3'), ('tinynas', 't3'), ('sojiro', 't3'),
                   ('tinypc', 't4')):
    t0 = T1425 if plan == 't4' else T1315
    END = plan_end(host, plan)
    rc, e, csv = go(host, plan, t0=t0)
    r = rows(csv)
    hdr = [l for l in csv.splitlines() if l and not l.startswith('#')][0].split(',') if csv else []
    stress = [p.args for p in e.procs if 'stress-ng' in p.args]
    last = r[-1] if r else {}
    case(f'{host} {plan}: exit 0, ends at its plan end ({time.strftime("%H:%M", time.localtime(END))}), unique columns, stress-ng nice 19',
         rc == 0 and abs(float(last.get('epoch', 0)) - END) <= 15 and len(hdr) == len(set(hdr)) and stress
         and all(s[:3] == ['nice', '-n', '19'] for s in stress), f'rc {rc} last {last.get("time")} stress {stress[:1]} '
         f'dupes {[c for c in hdr if hdr.count(c) > 1][:3]} notes {notes(csv)[-3:]}')
    if host == 'futaba':
        case('futaba: 2 workers (the plan says 2; max_cpu 2)', stress and stress[0][stress[0].index('--cpu') + 1] == '2')
    if host == 'tinynas':
        fios = [p.args for p in e.procs if 'fio' in p.args]
        mins = (END - T1315) / 60
        hg = [c for c in e.calls if c[0] == 'smartctl' and c[-1].startswith('/dev/sd')]
        nv = [c for c in e.calls if c[0] == 'smartctl' and c[-1] == '/dev/nvme1n1']
        case('tinynas t3: one fio (sequential homePool); 8 HGST + the NVMe read by smartctl every ~60 s', len(fios) == 1
             and 'rw=read' in e.last_job and 8 * (mins - 2) <= len(hg) <= 8 * (mins + 3) and mins - 2 <= len(nv) <= mins + 3,
             (len(fios), len(hg), len(nv), mins))
    if host == 'sojiro':
        ip = [c for c in e.calls if c[:2] == ['ipmitool', 'sdr']]
        case('sojiro: ipmitool sdr every ~30 s', 250 <= len(ip) <= 270, len(ip))
        case('sojiro: MB_TEMP1 stop = start + 8', any('bmc_mb1: start 70C -> stop 78C' in n for n in notes(csv)))
    if host == 'tinypc':
        nv = [c for c in e.calls if c[0] == 'nvidia-smi']
        case('tinypc: nvidia-smi every ~60 s, never a GPU load', 55 <= len(nv) <= 65 and all('stress-ng' not in p.args or
             '--gpu' not in ' '.join(p.args) for p in e.procs), len(nv))

# 2. futaba: plan asking 4 workers is clamped to 2 (hard rule)
tmp = '/tmp/x-plan-futaba4.json'
e = FakeHost('futaba')
e.files[tmp] = json.dumps({'futaba': [{'name': 'x', 'cpu': 4, 'min': 5}]})
e.files[PROFILE] = open(PROFILE).read()
rc = ll.main(['clamp', PROFILE, tmp], e, {'CSV_DIR': '/tmp/x'})
st = [p.args for p in e.procs if 'stress-ng' in p.args]
case('futaba: cpu 4 clamped to 2, noted', rc == 0 and st and st[0][st[0].index('--cpu') + 1] == '2'
     and 'clamped' in e.files['/tmp/x/lab-load-clamp.csv'])

# 3. futaba guards: HA slow once = note; twice = stop; Prometheus not ready twice = stop; targets down +1 twice = stop
def ha_slow(env):
    env.ha_s = 2.5
def ha_ok(env):
    env.ha_s = 0.2
rc, e, csv = go('futaba', events={T1315 + 600: ha_slow, T1315 + 605: ha_ok})
case('futaba: HA over 2 s on one check: note, no stop', rc == 0 and any('guard ha' in n for n in notes(csv)))
rc, e, csv = go('futaba', events={T1315 + 600: ha_slow})
st = [n for n in notes(csv) if 'STOP' in n]
case('futaba: HA over 2 s twice: exit 4, load killed, 5 min more logging', rc == 4 and st and 'HA frontend' in st[0]
     and all(p.killed for p in e.procs) and rows(csv)[-1]['phase'] == 'cooldown'
     and 290 <= float(rows(csv)[-1]['epoch']) - float(st[0].split()[1]) <= 320, st)
def prom_down(env):
    env.prom_ready = 503
rc, e, csv = go('futaba', events={T1315 + 900: prom_down})
case('futaba: Prometheus not ready twice: exit 4', rc == 4 and any('Prometheus /-/ready' in n for n in notes(csv) if 'STOP' in n))
def target_down(env):
    env.up0 = 2
rc, e, csv = go('futaba', events={T1315 + 900: target_down})
case('futaba: count(up==0) 1 -> 2 on 2 samples: exit 4', rc == 4 and any('targets down 2 (start 1)' in n for n in notes(csv)))

# 4. tinypc: satellite inactive at the start = refused; mid-run twice = stop; GPU hot = stop
e = FakeHost('tinypc', T1425)
e.user_units['mirror-voice-sat'] = 'inactive'
rc = ll.main(['t4x', PROFILE, PLANS['t4']], e, {'CSV_DIR': '/tmp/x'})
case('tinypc: mirror-voice-sat inactive at the start: refused (exit 2), no stress-ng', rc == 2 and not e.procs)
def sat_off(env):
    env.user_units['whisper-gpu'] = 'failed'
rc, e, csv = go('tinypc', 't4', t0=T1425, events={T1425 + 900: sat_off})
case('tinypc: whisper-gpu cgroup empty on 2 checks: exit 4', rc == 4 and any('whisper-gpu inactive (empty cgroup)' in n for n in notes(csv) if 'STOP' in n))
def gpu_hot(env):
    env.override[('gpu', 'temp')] = 89
rc, e, csv = go('tinypc', 't4', t0=T1425, events={T1425 + 900: gpu_hot})
case('tinypc: GPU at 89 (stop 88) on 2 reads 60 s apart: exit 4', rc == 4 and any('gpu 89C at its stop line' in n for n in notes(csv) if 'STOP' in n))

# 5. sojiro: MB_TEMP1 start + 8 on 2 readings; IPMI gone 3 reads; MG04 50C twice; pending sector +1
def mb_hot(env):
    env.override[('ipmi', 'MB_TEMP1')] = 78
rc, e, csv = go('sojiro', events={T1315 + 1200: mb_hot})
st = [n for n in notes(csv) if 'STOP' in n]
case('sojiro: MB_TEMP1 78 (start 70 + 8) on 2 readings: exit 4', rc == 4 and st and 'bmc_mb1 78C at its stop line 78C' in st[0], st)
def ipmi_gone(env):
    env.ipmi_ok = False
rc, e, csv = go('sojiro', events={T1315 + 1200: ipmi_gone})
case('sojiro: no IPMI reading 3 times in a row: exit 4', rc == 4 and any('no reading 3 times' in n for n in notes(csv) if 'STOP' in n))
def mg_hot(env):
    env.override[('drive', 'X7UQK5XKFSYC')] = 50
rc, e, csv = go('sojiro', events={T1315 + 1200: mg_hot})
case('sojiro: MG04 at 50 on 2 reads (60 s apart): exit 4, fio killed', rc == 4 and any('mg04.sdc.X7UQK5XKFSYC 50C at its stop line' in n
     for n in notes(csv) if 'STOP' in n) and all(p.killed for p in e.procs))
def pend(env):
    env.pending['X7UDK2CXFSYC'] = 1
rc, e, csv = go('sojiro', events={T1315 + 1500: pend})
case('sojiro: Current_Pending_Sector +1 at the 10-min check: exit 4', rc == 4 and any('Current_Pending_Sector 0 -> 1' in n for n in notes(csv)))

# 6. Intel throttle event: immediate stop; AMD: none exists, clocks logged
def thr(env):
    env.throttle_core = 1
rc, e, csv = go('morgana', events={T1315 + 1800: thr})
st = [n for n in notes(csv) if 'STOP' in n]
case('morgana: one thermal throttle event: immediate exit 4', rc == 4 and st and 'thermal throttle' in st[0]
     and float(st[0].split()[1]) - (T1315 + 1800) <= 15, st)
rc, e, csv = go('yusuke')
case('yusuke (AMD): no throttle columns, clocks logged', rc == 0 and rows(csv)[5]['thr_core'] == '' and rows(csv)[5]['mhz_mean'] == '3000')

# 7. sensor lines: stop on 2 readings, abort on one, n=3 on morgana's CPU, vanished 3x
def tskn(v):
    def f(env):
        env.override[('zone', 'TSKN')] = v
    return f
rc, e, csv = go('morgana', events={T1315 + 1200: tskn(50), T1315 + 1205: tskn(40)})
case('morgana: TSKN 50 for one reading: note, no stop', rc == 0 and any('skin_tskn 50C at its stop line 50C (1 of 2' in n for n in notes(csv)))
rc, e, csv = go('morgana', events={T1315 + 1200: tskn(55)})
st = [n for n in notes(csv) if 'STOP' in n]
case('morgana: TSKN 55 (abort): one reading stops', rc == 4 and st and 'abort line 55C' in st[0]
     and float(st[0].split()[1]) - (T1315 + 1200) <= 15, st)
def cpu95(env):
    env.override[('coretemp', 'Package id 0')] = 96
def cpu80(env):
    env.override[('coretemp', 'Package id 0')] = 80
rc, e, csv = go('morgana', events={T1315 + 1200: cpu95, T1315 + 1215: cpu80})
case('morgana: CPU 96 for 2 readings (PL2 burst, n=3): no stop', rc == 0)
rc, e, csv = go('morgana', events={T1315 + 1200: cpu95})
case('morgana: CPU 96 for 3 readings: exit 4', rc == 4 and any('cpu_pkg 96C at its stop line 95C (3 readings' in n for n in notes(csv)))
def nvme_gone(env):
    env.override[('nvme', 'Composite')] = None
rc, e, csv = go('morgana', events={T1315 + 1200: nvme_gone})
case('morgana: NVMe gives no reading 3 times: exit 4', rc == 4 and any('nvme: no reading 3 times' in n for n in notes(csv)))

# 8. LOAD_UNTIL mid-step: load off, exit 0; past LOAD_UNTIL at start: no load at all
rc, e, csv = go('yusuke', ev={'LOAD_UNTIL': str(T1315 + 1800)})
case('LOAD_UNTIL 13:45: load off then, exit 0', rc == 0 and all(p.killed for p in e.procs)
     and abs(float(rows(csv)[-1]['epoch']) - (T1315 + 1800)) <= 15, rows(csv)[-1]['time'] if rows(csv) else '')
rc, e, csv = go('yusuke', ev={'LOAD_UNTIL': str(T1315 - 60)})
case('past LOAD_UNTIL at the start: no stress-ng at all', rc == 0 and not e.procs)

# 9. cpu 0 step: no stress-ng process (stress-ng's own 0 = one worker per CPU)
e = FakeHost('tinynas')
e.files[PROFILE] = open(PROFILE).read()
e.files['/tmp/p0.json'] = json.dumps({'tinynas': [{'name': 'idle', 'cpu': 0, 'min': 5},
                                                  {'name': 'disk', 'cpu': 0, 'fio': {'mode': 'seq', 'pool': 'homePool'}, 'min': 5}]})
rc = ll.main(['zero', PROFILE, '/tmp/p0.json'], e, {'CSV_DIR': '/tmp/x'})
case('cpu 0: no stress-ng process at all (fio alone in the disk step)', rc == 0 and not [p for p in e.procs if 'stress-ng' in p.args]
     and len([p for p in e.procs if 'fio' in p.args]) == 1)

# 10. refusals: fio device without a stop line; never-touch drive; makoto
e = FakeHost('tinynas')
e.files[PROFILE] = open(PROFILE).read()
e.files['/tmp/p1.json'] = json.dumps({'tinynas': [{'name': 'x', 'cpu': 1, 'fio': {'mode': 'rand', 'devices': ['/dev/sdz']}, 'min': 5}]})
rc = ll.main(['nostop', PROFILE, '/tmp/p1.json'], e, {'CSV_DIR': '/tmp/x'})
case('fio on a device with no stop line: refused, nothing started', rc == 2 and not e.procs)
e = FakeHost('sojiro')
prof = json.load(open(PROFILE))
prof['hosts']['sojiro']['drives'].append({'name': 'old', 'serial': '67H5K3L0FSZC', 'stop': 50})
e.j['drives'].append({'dev': 'sdf', 'serial': '67H5K3L0FSZC', 'model': 'MG04ACA200N', 'tran': 'sata', 'temp': 36})
e.files['/tmp/prof2.json'] = json.dumps(prof)
rc = ll.main(['deny', '/tmp/prof2.json', PLANS['t3']], e, {'CSV_DIR': '/tmp/x'})
case("a never-touch serial in a profile: refused", rc == 2 and not e.procs)

# 11. selftest on each host: no process, no file, exit 0, prints every sensor
for host in ('futaba', 'morgana', 'yusuke', 'tinynas', 'sojiro', 'tinypc'):
    e = FakeHost(host, T1425 if host == 'tinypc' else T1315)
    rc = ll.main(['--selftest', 'st', PROFILE, PLANS['t4' if host == 'tinypc' else 't3']], e, {'CSV_DIR': '/tmp/x'})
    case(f'{host} selftest: exit 0, no load, no file', rc == 0 and not e.procs and not any(k.startswith('/tmp/x/') for k in e.files)
         and any('step ' in o for o in e.outs), e.outs[-3:])

# 12. review B3: an NVMe that fio reads is SMART-read: a media error stops the load (old code never read it)
NV_PLAN = '/tmp/plan-nvme-rand.json'
NV_DOC = json.dumps({'tinynas': [
    {'name': 'seq', 'cpu': 12, 'fio': {'mode': 'seq', 'pool': 'homePool'}, 'min': 70, 'until': '2026-10-20 14:25'},
    {'name': 'rand', 'cpu': 12, 'fio': {'mode': 'rand', 'pool': 'homePool',
                                        'devices': ['/dev/disk/by-id/nvme-eui.000000000000000100a0752550173620']},
     'min': 60, 'until': '2026-10-20 15:25'}]})
def media(env):
    env.media['252050173620'] = 1
e = FakeHost('tinynas', T1315, {T1425 + 900: media})
e.files[NV_PLAN] = NV_DOC
rc = ll.main(['nvrand', PROFILE, NV_PLAN], e, {'CSV_DIR': '/tmp/x'})
csv = e.files.get('/tmp/x/lab-load-nvrand.csv', '')
fios = [p.args for p in e.procs if 'fio' in p.args]
case('tinynas seq then rand at 14:25, the rand job reads the NVMe', len(fios) == 2 and 'nvme1n1' in e.last_job
     and 'rw=randread' in e.last_job, fios)
case('review B3: tinynas t4rand NVMe media error +1: exit 4', rc == 4 and any('NVMe media errors 0 -> 1' in n for n in notes(csv) if 'STOP' in n),
     [n for n in notes(csv) if 'STOP' in n])
e = FakeHost('tinynas')
prof = json.load(open(PROFILE))
prof['hosts']['tinynas']['drives'] = [x for x in prof['hosts']['tinynas']['drives'] if x.get('proto') != 'nvme']
e.files['/tmp/prof-nonvme.json'] = json.dumps(prof)
e.files[NV_PLAN] = NV_DOC
rc = ll.main(['nonvme', '/tmp/prof-nonvme.json', NV_PLAN], e, {'CSV_DIR': '/tmp/x'})
case('review B3: an NVMe fio target that is not a profile drive is refused', rc == 2 and not e.procs)

# 13. review B4: fio's leader exits early, its readers live on; the next stop kills the whole group (TERM and KILL)
def leader_dies(env):
    for p in env.procs:
        if 'fio' in p.args:
            p.leader_dies_at = env.t
def hot_hgst(env):
    env.override[('drive', 'PN2338P4HASBJC')] = 60
rc, e, csv = go('tinynas', events={T1315 + 600: leader_dies, T1315 + 1200: hot_hgst})
fk = [k for k in e.kills if k[0] == 'fio']
case('review B4: dead fio leader: noted once, and the stop still sends TERM and KILL to its group', rc == 4
     and (('fio', 15) in fk and ('fio', 9) in fk) and sum('fio ended early' in n for n in notes(csv)) == 1, (fk, rc))

# 14. review M13: unknown guard key refuses
e = FakeHost('futaba')
prof = json.load(open(PROFILE))
prof['hosts']['futaba']['guards'] = {'futaba-ha': {}}
e.files['/tmp/prof-guard.json'] = json.dumps(prof)
rc = ll.main(['badguard', '/tmp/prof-guard.json', PLANS['t3']], e, {'CSV_DIR': '/tmp/x'})
case('review M13: guard key typo (futaba-ha) refuses', rc == 2 and not e.procs)

# 15. review M14: Intel throttle counters unreadable at the start refuses
e = FakeHost('morgana')
e.throttle_ok = False
rc = ll.main(['nothr', PROFILE, PLANS['t3']], e, {'CSV_DIR': '/tmp/x'})
case('review M14: Intel host without throttle counters at the start refuses', rc == 2 and not e.procs)

# 16. review M15: a warm sojiro start cannot raise MB_TEMP1's line above 78
e = FakeHost('sojiro')
e.override[('ipmi', 'MB_TEMP1')] = 75
rc = ll.main(['--selftest', 'warm', PROFILE, PLANS['t3']], e, {'CSV_DIR': '/tmp/x'})
case('review M15: MB_TEMP1 start 75 -> stop 78 (not 83), abort 82', any('bmc_mb1' in o and 'stop   78.0' in o and 'abort   82.0' in o
     for o in e.outs), [o for o in e.outs if 'bmc_mb1' in o])

# 17. review M16: futaba is clamped to 2 in code even if the profile loses max_cpu
e = FakeHost('futaba')
prof = json.load(open(PROFILE))
prof['hosts']['futaba'].pop('max_cpu')
e.files['/tmp/prof-nomax.json'] = json.dumps(prof)
e.files['/tmp/p4.json'] = json.dumps({'futaba': [{'name': 'x', 'cpu': 4, 'min': 5}]})
rc = ll.main(['nomax', '/tmp/prof-nomax.json', '/tmp/p4.json'], e, {'CSV_DIR': '/tmp/x'})
st = [p.args for p in e.procs if 'stress-ng' in p.args]
case('review M16: futaba without max_cpu in the profile still runs 2 workers', rc == 0 and st and st[0][st[0].index('--cpu') + 1] == '2', st)

# ---------- Wednesday: tinypc W3, makoto W1 / W2
TW = lambda hm: time.mktime(time.strptime(f'2026-10-21 {hm}', '%Y-%m-%d %H:%M'))
TP = json.load(open(PLANS['w1']))['tinypc'][0]          # the coordinator moves this block: derive the times
TP_UNTIL = time.mktime(time.strptime(TP['until'], '%Y-%m-%d %H:%M'))
TP_START = TP_UNTIL - TP['min'] * 60 - 180                    # 3 min of slack, like a timer at the hour
rc, e, csv = go('tinypc', 'w1', t0=TP_START)
st = [p.args for p in e.procs if 'stress-ng' in p.args]
case(f'tinypc {TP["name"]}: 20 workers nice 19 for {TP["min"]} min, guard read from cgroups, exit 0', rc == 0 and st
     and st[0][st[0].index('--cpu') + 1] == '20' and abs(float(rows(csv)[-1]['epoch']) - (TP_START + TP['min'] * 60)) <= 15
     and e.cg_reads > 100 and rows(csv)[5].get('mirror-voice-sat') == 'active', (rc, rows(csv)[-1]['time'] if rows(csv) else ''))
rc, e, csv = go('tinypc', 'w1', t0=TP_UNTIL - 20 * 60)
case(f'tinypc {TP["name"]} started late: ends at its until {TP["until"][-5:]}', rc == 0 and abs(float(rows(csv)[-1]['epoch']) - TP_UNTIL) <= 15)

e = FakeHost('makoto', time.mktime(time.strptime('2026-10-20 15:59', '%Y-%m-%d %H:%M')))
rc = ll.main(['w1makoto', PROFILE, PLANS['w1']], e, {'CSV_DIR': '/tmp/x'})
case('makoto before Tue 16:00: refused (exit 2), nothing started', rc == 2 and not e.procs
     and 'no load before 2026-10-20 16:00' in e.files.get('/tmp/x/lab-load-w1makoto.csv', ''))
prof = json.load(open(PROFILE))
mk = prof['hosts'].pop('makoto')
prof['hosts']['default'] = mk.copy()
prof['hosts']['default'].pop('host')
e = FakeHost('makoto', TW('08:00'))
e.files['/tmp/prof-default.json'] = json.dumps(prof)
rc = ll.main(['w1makoto', '/tmp/prof-default.json', PLANS['w1']], e, {'CSV_DIR': '/tmp/x'})
case('makoto through a "default" profile entry: refused (explicit makoto entry only)', rc == 2 and not e.procs)

rc, e, csv = go('makoto', 'w1', t0=TW('08:00'))
st = [p.args for p in e.procs if 'stress-ng' in p.args]
r = rows(csv)
case('makoto W1: 2 workers nice 19 to 10:00, exit 0, no ipmitool', rc == 0 and len(st) == 1 and st[0][:3] == ['nice', '-n', '19']
     and st[0][st[0].index('--cpu') + 1] == '2' and abs(float(r[-1]['epoch']) - TW('10:00')) <= 15
     and not any(c[0] == 'ipmitool' for c in e.calls), (rc, st[:1]))
case('makoto W1: Card Side and DDR read from makoto-fan\'s state (49-54, 52), journal checked every ~30 s',
     49 <= float(r[5]['card_side']) <= 54 and r[5]['ddr'] == '52'
     and 230 <= len([c for c in e.calls if c[0] == 'journalctl']) <= 250, (r[5].get('card_side'), r[5].get('ddr')))

rc, e, csv = go('makoto', 'wmk', t0=TW('10:30'))
st = [p.args[p.args.index('--cpu') + 1] for p in e.procs if 'stress-ng' in p.args]
alive_max = max(sum(1 for p in e.procs if not p.killed and 'stress-ng' in p.args) for _ in [0])
case('makoto W2 (wmk): 2 then 4 workers, then 20 min idle, exit 0', rc == 0 and st == ['2', '4']
     and abs(float(rows(csv)[-1]['epoch']) - (TW('10:30') + 80 * 60)) <= 15, st)

e = FakeHost('makoto', TW('10:30'))
e.files['/tmp/p-mk8.json'] = json.dumps({'makoto': [{'name': 'x', 'cpu': 8, 'nice': 0, 'min': 5}]})
rc = ll.main(['mk8', PROFILE, '/tmp/p-mk8.json'], e, {'CSV_DIR': '/tmp/x'})
st = [p.args for p in e.procs if 'stress-ng' in p.args]
case('makoto: a cpu 8 / nice 0 step runs 4 workers at nice 19 (B4), noted', rc == 0 and st and st[0][2] == '19'
     and st[0][st[0].index('--cpu') + 1] == '4' and 'clamped' in e.files['/tmp/x/lab-load-mk8.csv'])
e = FakeHost('makoto', TW('10:30'))
e.files['/tmp/p-mkfio.json'] = json.dumps({'makoto': [{'name': 'x', 'cpu': 2, 'min': 5, 'fio': {'mode': 'seq', 'devices': ['/dev/sda']}}]})
rc = ll.main(['mkfio', PROFILE, '/tmp/p-mkfio.json'], e, {'CSV_DIR': '/tmp/x'})
case('makoto: a fio step refuses', rc == 2 and not e.procs)

def card57(env):
    env.override[('mk', 'card')] = 57.0
rc, e, csv = go('makoto', 'w1', t0=TW('08:00'), events={TW('08:30'): card57})
case('makoto: Card Side 57 (state file) on 2 readings: exit 4', rc == 4 and any('card_side 57C at its stop line 57C' in n for n in notes(csv) if 'STOP' in n))
def no_card(env):
    env.mk_drop = {'card'}
rc, e, csv = go('makoto', 'w1', t0=TW('08:00'), events={TW('08:30'): no_card})
r = rows(csv)
late = [x for x in r if float(x['epoch']) > TW('08:31')]
case('makoto: a key missing from makoto-fan\'s state: the ipmitool textfile is used (51.25 there, 50.25 in the state)', rc == 0
     and late and late[3]['card_side'] == '51.25' and r[5]['card_side'] == '50.25', (late[3].get('card_side') if late else None, r[5].get('card_side')))
def stale_state(env):
    env.st_age = 400
rc, e, csv = go('makoto', 'w1', t0=TW('08:00'), events={TW('08:30'): stale_state})
st = [n for n in notes(csv) if 'STOP' in n]
case('makoto_fan guard: state 400 s old on 2 samples: exit 4, load killed', rc == 4 and st and 'makoto-fan active, state age 4' in st[0]
     and all(p.killed for p in e.procs) and float(st[0].split()[1]) - TW('08:30') <= 25, st)

def wake(env):
    env.journal.append((int(env.t), 'wake (hey_claude 0.81)'))
e = FakeHost('makoto', TW('08:00'), {TW('09:00'): wake})
e.journal.append((int(TW('07:55')), 'heard: what time is it'))      # before the start: the gate's business, not a stop
rc = ll.main(['w1makoto', PROFILE, PLANS['w1']], e, {'CSV_DIR': '/tmp/x'})
csv = e.files['/tmp/x/lab-load-w1makoto.csv']
st = [n for n in notes(csv) if 'STOP' in n]
case('makoto: a wake in mirror-voice\'s journal mid-run stops at once (exit 4); one before the start does not', rc == 4 and st
     and 'mirror-voice in use' in st[0] and TW('09:00') <= float(st[0].split()[1]) <= TW('09:00') + 40, st)
def journal_down(env):
    env.journal_ok = False
rc, e, csv = go('makoto', 'w1', t0=TW('08:00'), events={TW('08:30'): journal_down})
case('makoto: mirror-voice journal unreadable twice: exit 4', rc == 4 and any('journal unreadable' in n for n in notes(csv) if 'STOP' in n))

# ---------- 04:4x urgent: the stress-ng argv (stress-ng has no --matrixprod option)
L = ll.Load(['x', PROFILE, PLANS['t3']], FakeHost('morgana'), {'CSV_DIR': '/tmp/x'})
case('stress-ng argv pinned: nice -n 19 stress-ng --cpu 8 --cpu-method matrixprod --timeout 60s --temp-path /tmp --quiet',
     L.stress_cmd(8, 19, 60) == ['nice', '-n', '19', 'stress-ng', '--cpu', '8', '--cpu-method', 'matrixprod', '--timeout', '60s',
                                 '--temp-path', '/tmp', '--quiet'], L.stress_cmd(8, 19, 60))
rc, e, csv = go('morgana')
case('every stress-ng started in a full T3 run parses (the fake rejects --matrixprod like 0.17.06) and none ended early',
     rc == 0 and all(stress_argv_ok(p.args) for p in e.procs if 'stress-ng' in p.args) and 'ended early' not in csv)
for host, plan in (('morgana', 't3'), ('tinynas', 'w1'), ('sojiro', 't3'), ('tinypc', 't4'), ('futaba', 'w1'), ('makoto', 'wmk')):
    t0 = TW('10:30') if host == 'makoto' else (T1425 if plan == 't4' else T1315)
    e = FakeHost(host, t0)
    rc = ll.main(['--selftest', 'st', PROFILE, PLANS[plan]], e, {'CSV_DIR': '/tmp/x'})
    dry = [c for c in e.calls if c[0] == 'stress-ng']
    fpo = [c for c in e.calls if c[:3] == ['fio', '--readonly', '--parse-only']]
    case(f'{host} selftest: stress-ng --dry-run on the exact argv{" and fio --parse-only" if fpo else ""}, rc 0, job file removed',
         rc == 0 and dry and all('--dry-run' in c and stress_argv_ok(c) for c in dry) and not any(k.endswith('.fio') for k in e.files)
         and not e.procs, (rc, dry[:1], fpo[:1]))
L = ll.Load(['x', PROFILE, PLANS['t3']], FakeHost('morgana'), {'CSV_DIR': '/tmp/x'})
L.setup()
L.stress_args = lambda cpu, secs: ['stress-ng', '--matrixprod', str(cpu)]
case('selftest argv check fails loudly on a bad argv (the old --matrixprod)', any('stress-ng rc 1' in b for b in L.argv_check()))

# ---------- 06:2x: makoto_fan guard (read-only) and tinypc's W3 end
e = FakeHost('makoto', TW('08:00'))
e.mkfan = 'inactive'
rc = ll.main(['w1makoto', PROFILE, PLANS['w1']], e, {'CSV_DIR': '/tmp/x'})
case('makoto_fan guard: makoto-fan inactive at the start: refused (exit 2), nothing started', rc == 2 and not e.procs
     and 'no makoto load without its controller' in e.files.get('/tmp/x/lab-load-w1makoto.csv', ''))
def fan_failed(env):
    env.mkfan = 'failed'
rc, e, csv = go('makoto', 'w1', t0=TW('08:00'), events={TW('08:30'): fan_failed})
st = [n for n in notes(csv) if 'STOP' in n]
case('makoto_fan guard: makoto-fan failed mid-run: stop on the 2nd sample (exit 4)', rc == 4 and st and 'makoto-fan failed' in st[0]
     and 10 <= float(st[0].split()[1]) - TW('08:30') <= 25, st)
def fan_blip(env):
    env.mkfan = 'activating'
def fan_back(env):
    env.mkfan = 'active'
rc, e, csv = go('makoto', 'w1', t0=TW('08:00'), events={TW('08:30'): fan_blip, TW('08:30') + 5: fan_back})
case('makoto_fan guard: one bad sample (restart blip): note, no stop', rc == 0 and any('guard makoto_fan' in n for n in notes(csv)))
def emergency(env):
    env.mk_emergency = True
rc, e, csv = go('makoto', 'w1', t0=TW('08:00'), events={TW('08:30'): emergency})
case('makoto_fan guard: makoto-fan in emergency on 2 samples: exit 4', rc == 4 and any('EMERGENCY' in n for n in notes(csv) if 'STOP' in n))
prof = json.load(open(PROFILE))
prof['hosts']['makoto']['guards'].pop('makoto_fan')
e = FakeHost('makoto', TW('08:00'))
e.files['/tmp/prof-noguard.json'] = json.dumps(prof)
rc = ll.main(['w1makoto', '/tmp/prof-noguard.json', PLANS['w1']], e, {'CSV_DIR': '/tmp/x'})
case('makoto profile without the makoto_fan guard: refused', rc == 2 and not e.procs)
rc, e, csv = go('makoto', 'w1', t0=TW('08:00'))
sc = [c for c in e.calls if c[0] == 'systemctl']
case('makoto_fan guard: only systemctl is-active, about once per sample (~720 in 2 h)', rc == 0 and sc
     and all(c[1:] == ['is-active', 'makoto-fan'] for c in sc) and 700 <= len(sc) <= 740, len(sc))

rc, e, csv = go('tinypc', 'w1', t0=TP_UNTIL + 300)
case(f'tinypc {TP["name"]} starting after its until: no load at all (skipped), exit 0', rc == 0
     and not [p for p in e.procs if 'stress-ng' in p.args] and 'skipped' in csv)

# ---------- 07:0x: tinypc_sat reads the user units' cgroups (no D-Bus: systemctl --user -M fails inside a service)
e = FakeHost('tinypc', TP_START)
e.user_units['mirror-voice-sat'] = 'gone'
rc = ll.main(['w0tinypc', PROFILE, PLANS['w1']], e, {'CSV_DIR': '/tmp/x'})
case('tinypc_sat: no mirror-voice-sat cgroup at the start: refused (no cgroup)', rc == 2 and not e.procs
     and 'mirror-voice-sat is inactive (no cgroup) at the start' in e.files.get('/tmp/x/lab-load-w0tinypc.csv', ''))
e = FakeHost('tinypc', TP_START)
e.unit_slice['whisper-gpu'] = 'app.slice/app-gpu.slice'
e.events_ok = False
rc = ll.main(['--selftest', 'st', PROFILE, PLANS['w1']], e, {'CSV_DIR': '/tmp/x'})
case('tinypc_sat: a unit nested deeper is found, and cgroup.procs answers when cgroup.events cannot', rc == 0
     and any("'whisper-gpu': 'active'" in o and "'mirror-voice-sat': 'active'" in o for o in e.outs), [o for o in e.outs if 'guards' in o])
L = ll.Load(['x', PROFILE, PLANS['w1']], FakeHost('tinypc', TP_START), {'CSV_DIR': '/tmp/x'})
case('tinypc_sat: an unknown user reads as inactive, never an exception', L.user_unit_state('nobody', 'mirror-voice-sat').startswith('inactive'))

bad = [n for n, ok in RESULTS if not ok]
print(f'\n{len(RESULTS) - len(bad)}/{len(RESULTS)} passed' + (f'; FAILED: {bad}' if bad else ''))
sys.exit(1 if bad else 0)
