#!/usr/bin/env python3
# lab-load (2026-10-20): per-host CPU (and read-only disk) load runner with the host's own stop lines, for the boxes
# without a fan controller: futaba, morgana, yusuke, tinynas, tinypc and sojiro.
# usage (root): lab-load.py [--selftest] LABEL PROFILE.json PLAN.json
#   PROFILE: one host's profile, or {"hosts": {name: profile}} / {name: profile} picked by this host's name.
#   PLAN: a list of steps, or {name: [steps]} picked by host name ("default" as a fallback). A step:
#     {"name": "t3", "cpu": 8, "nice": 19, "fio": {"mode": "seq"|"rand", "pool": "homePool"} or
#      {"mode": ..., "devices": ["/dev/disk/by-id/..."]}, "min": 70, "until": "2026-10-20 14:25"}
#     cpu = stress-ng cpu workers with --cpu-method matrixprod (0 = no stress-ng process at all; stress-ng's own
#     --cpu 0 means one per CPU),
#     clamped to the profile's max_cpu (futaba 2); the step ends after "min" minutes or at "until", whichever is first.
#   --selftest: read-only discovery: every sensor with its stop lines, drives, guards, throttle counters, clocks,
#     power, the plan as it would run (commands included). Starts no load, writes no file.
# Every SAMPLE_S (10) s one CSV row to /var/tmp/lab-load-<LABEL>.csv: epoch, time, phase, phase_min, cpu workers, fio,
# busy %, mean / max MHz, package W (RAPL), throttle counts (Intel), then every sensor, drive and guard value
# (columns discovered at start). SATA/SAS drives by smartctl -A at most every 60 s, one at a time; NVMe from hwmon.
# Stop lines (all load off, a "STOP:" note, logging goes on for 5 min, exit 4):
#   - any sensor at its stop line on 2 samples in a row (or "n"), or at its abort line on one; a sensor that gives
#     no reading 3 times in a row
#   - Intel: any new thermal_throttle core or package event since the start (AMD has none: clocks are logged)
#   - SMART on the drives being read: any new grown defect, reallocated or pending sector, NVMe media error, or a
#     link counter up by more than PHY_JUMP (100), checked every 10 min
#   - guards (profile "guards"): futaba_ha (HA frontend over 2 s twice; local Prometheus not ready twice; count(up==0)
#     up by 1+ on 2 samples), tinypc_sat (rohit's user units mirror-voice-sat and whisper-gpu must stay active, read
#     from their cgroups under user@<uid>.service, no D-Bus: 2 checks in a row inactive), sojiro_ipmi (`ipmitool sdr type temperature` every 30 s in-band: CPU0_TEMP 92C,
#     MB_TEMP1 its value at the start + 8C), mirror_voice (makoto: a "wake (" or "heard " line in mirror-voice's
#     journal since the start stops the load at once; a failed journal read twice in a row too), makoto_fan (makoto:
#     `systemctl is-active makoto-fan` must say active, /run/makoto-fan.state must be fresh by its own "t" (120 s)
#     and not in emergency, on every sample: refused at the start, stopped on 2 bad samples in a row; read-only, it
#     never starts, stops or restarts makoto-fan or any makoto-* unit)
# Sensor kinds: hwmon (chip + label regex), zone (thermal zone type), battery, nvidia, ipmi, file (a value from another
# program's state: a JSON file with its own timestamp, or a node_exporter textfile line; first fresh source wins, so
# makoto's Card Side and DDR come from makoto-fan's state, never from ipmitool). A required sensor with no reading at
# the start refuses the run.
# makoto: refused before 2026-10-20 16:00 and without an explicit "makoto" profile entry; nice 19 and at most 4
# workers whatever the plan says; no fio.
# LOAD_UNTIL (env epoch): no load after it (the running step is stopped, exit 0). SIGTERM: load killed, exit 0.
# stress-ng and fio run in their own process group inside this unit's cgroup and are killed as a group; no pkill.
# fio is read-only (--readonly on the command line, O_DIRECT, raw disks) and refuses makoto and the never-touch drives.
import fnmatch, glob as globmod, json, os, pwd, re, signal, socket, subprocess, sys, time, urllib.error, urllib.request

SAMPLE_S, SMART_S, GUARD_S, HEALTH_S, TAIL_S = 10, 60, 30, 600, 300
# makoto belongs to the fan-control-makoto-bmc session until its handoff: no load there before this (2026-10-20 16:00
# EDT), and only through an explicit "makoto" profile entry; then B4: nice 19, at most 4 of 8 threads, no disk load.
MAKOTO_FROM = 1792526400
MAKOTO_MAX_CPU = 4
DENY = {'2152E5F70B12', '2016E29B77F7', '2007E28BD0DA',                    # makoto backupPool
        '67H5K3L0FSZC', '67H4K4ELFSZC', '28NXK3O0FSYC', '28OYK4BFFSYC'}    # sojiro's old pool, in ryuji
PHY_KINDS = {'Invalid DWORD count': 'invalid_dword', 'Running disparity error count': 'disparity',
             'Loss of DWORD synchronization count': 'loss_sync', 'Phy reset problem count': 'reset_problem'}


class Env:
    def now(self):
        return time.time()

    def sleep(self, s):
        time.sleep(s)

    def read(self, path):
        with open(path) as f:
            return f.read()

    def glob(self, pattern):
        return sorted(globmod.glob(pattern, recursive='**' in pattern))

    def uid(self, user):
        return pwd.getpwnam(user).pw_uid

    def mtime(self, path):
        return os.path.getmtime(path)

    def exists(self, path):
        return os.path.exists(path)

    def write(self, path, text, mode='a'):
        with open(path, mode) as f:
            f.write(text)

    def remove(self, path):
        try:
            os.remove(path)
        except OSError:
            pass

    def realpath(self, path):
        return os.path.realpath(path)

    def hostname(self):
        return socket.gethostname().split('.')[0].lower()

    def run(self, args, timeout=60):
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
            return r.returncode, r.stdout
        except (OSError, subprocess.TimeoutExpired) as e:
            return 255, f'{type(e).__name__}: {e}'

    def http(self, url, timeout):
        """-> (status or None, seconds, body)"""
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                body = r.read(200000)
                return r.status, time.monotonic() - t0, body
        except urllib.error.HTTPError as e:
            return e.code, time.monotonic() - t0, b''
        except Exception:   # noqa: BLE001 (timeout, refused, DNS: all count as a failed check)
            return None, time.monotonic() - t0, b''

    def popen(self, args):
        # own process group, so the whole stress-ng / fio tree is killed together; still in this unit's cgroup
        return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    def killgroup(self, proc, sig):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass

    def out(self, text):
        print(text, flush=True)


def first_int(s):
    m = re.search(r'-?\d+', s.replace(',', ''))
    return int(m.group(0)) if m else None


def parse_smart(text, proto):
    """smartctl -A [-l sasphy] -> temp and health fields (as disk-soak.py)."""
    d = {}
    if re.search(r'Device is in (STANDBY|SLEEP|IDLE)', text):
        d['standby'] = True
    if proto == 'nvme':
        m = re.search(r'^Temperature:\s+(\d+) Celsius', text, re.M)
        if m:
            d['temp'] = int(m.group(1))
        m = re.search(r'^Media and Data Integrity Errors:\s+([\d,]+)', text, re.M)
        if m:
            d['media_errors'] = first_int(m.group(1))
        m = re.search(r'^Critical Warning:\s+(0x[0-9a-fA-F]+)', text, re.M)
        if m:
            d['crit_warning'] = int(m.group(1), 16)
        return d
    if proto == 'ata':
        attrs = {}
        for line in text.splitlines():
            m = re.match(r'\s*(\d+)\s+(\S+)\s+0x[0-9a-fA-F]+\s+\d+\s+\d+\s+\S+\s+\S+\s+\S+\s+\S+\s+(.+)$', line)
            if m:
                attrs[int(m.group(1))] = m.group(3)
        for i in (194, 190):
            if i in attrs:
                t = first_int(attrs[i])
                if t is not None and 0 < t < 100:
                    d['temp'] = t
                    break
        for i, k in ((5, 'realloc'), (197, 'pending'), (199, 'crc')):
            if i in attrs:
                d[k] = first_int(attrs[i])
        return d
    m = re.search(r'Current Drive Temperature:\s+(\d+)', text)
    if m:
        d['temp'] = int(m.group(1))
    m = re.search(r'Elements in grown defect list:\s+([\d,]+)', text)
    if m:
        d['defects'] = first_int(m.group(1))
    phy, port, pid = {}, None, None
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r'relative target port id = (\d+)', s)
        if m:
            port = m.group(1)
            continue
        m = re.match(r'phy identifier = (\d+)', s)
        if m:
            pid = m.group(1)
            continue
        m = re.match(r'(.+?) = (\d+)$', s)
        if m and m.group(1) in PHY_KINDS:
            phy[f'p{port}.{pid}.{PHY_KINDS[m.group(1)]}'] = int(m.group(2))
    if phy:
        d['phy'] = phy
    return d


def health_problems(base, cur, phy_jump):
    out = []
    for k, label in (('defects', 'grown defects'), ('realloc', 'Reallocated_Sector_Ct'),
                     ('pending', 'Current_Pending_Sector'), ('media_errors', 'NVMe media errors')):
        if k in base and k in cur and cur[k] > base[k]:
            out.append(f'{label} {base[k]} -> {cur[k]}')
    if 'crit_warning' in cur and cur['crit_warning'] & ~base.get('crit_warning', 0):
        out.append(f'NVMe critical warning 0x{base.get("crit_warning", 0):02x} -> 0x{cur["crit_warning"]:02x}')
    if 'crc' in base and 'crc' in cur and cur['crc'] - base['crc'] > phy_jump:
        out.append(f'UDMA_CRC_Error_Count {base["crc"]} -> {cur["crc"]}')
    for k, v in cur.get('phy', {}).items():
        b = base.get('phy', {}).get(k)
        if b is not None and v - b > phy_jump:
            out.append(f'SAS phy {k} {b} -> {v}')
    return out


def pick(doc, host, what):
    """A profile/plan document for this host: direct, under "hosts", by host name, or "default"."""
    if isinstance(doc, dict) and 'hosts' in doc:
        doc = doc['hosts']
    if isinstance(doc, dict) and not ({'sensors', 'steps'} & set(doc)):
        for k in (host, 'default'):
            if k in doc:
                return doc[k]
        raise RuntimeError(f'{what} has no entry for host {host!r} (keys: {sorted(doc)})')
    return doc


def parse_until(v):
    if v is None or v == '':
        return None
    if isinstance(v, (int, float)) or re.fullmatch(r'\d{9,}(\.\d+)?', str(v)):
        return float(v)
    return time.mktime(time.strptime(str(v), '%Y-%m-%d %H:%M'))


class Sensor:
    """One numeric reading with its stop lines. kind: hwmon | zone | file | ipmi | nvidia | drive | battery."""

    def __init__(self, name, kind, src, stop=None, abort=None, n=2, target=None, log_only=False, optional=False):
        self.name, self.kind, self.src = name, kind, src
        self.stop, self.abort, self.n, self.target = stop, abort, n, target
        self.log_only, self.optional = log_only, optional
        self.over = self.missing = 0
        self.value = None
        self.dev = ''
        self.fresh = True


class Load:
    def __init__(self, argv, env=None, env_vars=None):
        self.env = env or Env()
        self.ev = os.environ if env_vars is None else env_vars
        args = [a for a in argv if a != '--selftest']
        self.selftest = len(args) != len(argv)
        if len(args) != 3:
            raise SystemExit('usage: lab-load.py [--selftest] LABEL PROFILE.json PLAN.json')
        self.label, self.profile_path, self.plan_path = args
        self.load_until = float(self.ev.get('LOAD_UNTIL', '') or 'inf')
        self.phy_jump = float(self.ev.get('PHY_JUMP', '') or 100)
        self.tail_s = float(self.ev.get('TAIL_S', '') or TAIL_S)
        self.csv = f'{self.ev.get("CSV_DIR", "/var/tmp")}/lab-load-{self.label}.csv'
        self.job = f'{self.ev.get("RUN_DIR", "/run")}/lab-load-{self.label}.fio'
        self.host = self.env.hostname()
        self.stress = self.fio = None
        self.cur = None             # (cpu, fio desc) running now
        self.sensors, self.drives, self.notes_pending = [], [], []
        self.stat0 = self.rapl0 = None
        self.thr0 = None
        self.smart_t = self.guard_t = self.health_t = self.nv_t = self.ipmi_t = -1e18
        self.judging = True
        self.guard_state = {}
        self.guard_vals = {}
        self.drive_base = {}
        self.cols = None
        self.early = []
        self.early_noted = set()
        self.mv_since = None

    # ---------- output
    def note(self, m):
        t = self.env.now()
        line = f'# {int(t)} {time.strftime("%F %T %Z", time.localtime(t))} {m}\n'
        if self.selftest:
            pass
        elif self.cols is None:
            self.early.append(line)      # before the CSV header exists: written right after it
        else:
            self.env.write(self.csv, line)
        self.env.out(m)

    # ---------- setup
    def load_docs(self):
        prof = pick(json.loads(self.env.read(self.profile_path)), self.host, 'PROFILE')
        plan = pick(json.loads(self.env.read(self.plan_path)), self.host, 'PLAN')
        if isinstance(plan, dict):
            plan = plan['steps']
        self.prof = prof
        self.max_cpu = int(prof.get('max_cpu', prof.get('threads', 1)))
        if self.host == 'futaba':
            self.max_cpu = min(self.max_cpu, 2)      # HA, DNS and Prometheus: never above 2 threads, whatever the profile says
        if self.host == 'makoto':
            if prof.get('host') != 'makoto':
                raise RuntimeError('makoto runs only from an explicit "makoto" profile entry')
            allow = max(MAKOTO_FROM, parse_until(prof.get('allow_from')) or 0)
            if self.env.now() < allow:
                raise RuntimeError(f'makoto: no load before {time.strftime("%F %H:%M", time.localtime(allow))} '
                                   '(fan-control-makoto-bmc owns it until its handoff)')
            self.max_cpu = min(self.max_cpu, MAKOTO_MAX_CPU)     # B4: at least 4 of 8 threads free
        self.vendor = prof.get('vendor', 'intel')
        steps = []
        for i, st in enumerate(plan):
            cpu = int(st.get('cpu', 0))
            if cpu < 0:
                raise RuntimeError(f'step {i}: cpu {cpu} < 0')
            if cpu > self.max_cpu:
                self.notes_pending.append(f'step {st.get("name", i)}: cpu {cpu} clamped to this host\'s max {self.max_cpu}')
                cpu = self.max_cpu
            mins = float(st.get('min', 0) or 0)
            until = parse_until(st.get('until'))
            if mins <= 0 and until is None:
                raise RuntimeError(f'step {i}: needs "min" or "until"')
            fio = st.get('fio')
            if fio and fio.get('mode') not in ('seq', 'rand'):
                raise RuntimeError(f'step {i}: fio mode must be seq or rand')
            nice = int(st.get('nice', 19))
            if self.host == 'makoto':
                if fio:
                    raise RuntimeError('makoto: no disk load (its pools are backupPool and the boot NVMe)')
                if nice != 19:
                    self.notes_pending.append(f'step {st.get("name", i)}: nice {nice} -> 19 on makoto (B4)')
                nice = 19
            steps.append({'name': st.get('name', f'step{i}'), 'cpu': cpu, 'nice': nice,
                          'fio': fio, 'min': mins, 'until': until})
        self.steps = steps

    def hwmon_index(self):
        """[(chip, label, path, devname)] for every temp input."""
        out = []
        for h in self.env.glob('/sys/class/hwmon/hwmon*'):
            try:
                chip = self.env.read(f'{h}/name').strip()
            except OSError:
                continue
            dev = ''
            try:
                dev = os.path.basename(self.env.realpath(f'{h}/device'))
            except OSError:
                pass
            for inp in self.env.glob(f'{h}/temp*_input'):
                idx = re.search(r'temp(\d+)_input$', inp).group(1)
                try:
                    lab = self.env.read(f'{h}/temp{idx}_label').strip()
                except OSError:
                    lab = f'temp{idx}'
                out.append((chip, lab, inp, dev))
        return out

    def build_sensors(self):
        hw = self.hwmon_index()
        sens = []
        for spec in self.prof.get('sensors', []):
            kind = spec.get('kind', 'hwmon')
            base = dict(stop=spec.get('stop'), abort=spec.get('abort'), n=int(spec.get('n', 2)),
                        target=spec.get('target'), log_only=bool(spec.get('log_only')),
                        optional=bool(spec.get('optional')))
            if spec.get('log_only'):
                base['stop'] = base['abort'] = None
            if kind == 'hwmon':
                hits = [x for x in hw if re.fullmatch(spec['chip'], x[0]) and re.fullmatch(spec.get('label', '.*'), x[1])]
                if not hits and not spec.get('optional'):
                    raise RuntimeError(f'sensor {spec["name"]}: no hwmon chip {spec["chip"]!r} label {spec.get("label")!r}')
                devs = [dev or chip for chip, lab, path, dev in hits]
                for chip, lab, path, dev in hits:
                    nm = spec['name']
                    slug = re.sub(r'[^a-z0-9]+', '_', lab.lower()).strip('_')
                    if len(hits) > 1:      # unique column names: by label on one device, else device (+ label)
                        if len(set(devs)) == 1:
                            nm += f'.{slug}'
                        else:
                            nm += f'.{dev or chip}'
                            if devs.count(dev or chip) > 1:
                                nm += f'.{slug}'
                    sens.append(Sensor(nm, 'hwmon', path, **base))
                    sens[-1].dev = dev
            elif kind == 'zone':
                hits = []
                for z in self.env.glob('/sys/class/thermal/thermal_zone*'):
                    try:
                        if self.env.read(f'{z}/type').strip() == spec['zone']:
                            hits.append(f'{z}/temp')
                    except OSError:
                        pass
                if not hits and not spec.get('optional'):
                    raise RuntimeError(f'sensor {spec["name"]}: no thermal zone {spec["zone"]!r}')
                for p in hits[:1]:
                    sens.append(Sensor(spec['name'], 'zone', p, **base))
            elif kind == 'battery':
                hits = [p for p in self.env.glob('/sys/class/power_supply/BAT*/temp')]
                if not hits:
                    self.notes_pending.append(f'sensor {spec["name"]}: no battery temperature exposed on this host')
                for p in hits:
                    sens.append(Sensor(f'{spec["name"]}.{p.split("/")[-2]}', 'battery', p, **base))
            elif kind == 'nvidia':
                sens.append(Sensor(spec['name'], 'nvidia', None, **base))
            elif kind == 'file':
                srcs = spec.get('sources') or []
                if not srcs or not all('path' in x and ('json' in x or 'metric' in x) for x in srcs):
                    raise RuntimeError(f'sensor {spec["name"]}: kind file needs sources with path and json or metric')
                sens.append(Sensor(spec['name'], 'file', srcs, **base))
                sens[-1].max_age = float(spec.get('max_age', 180))
            elif kind == 'ipmi':
                sens.append(Sensor(spec['name'], 'ipmi', spec['sensor'], **base))
                if spec.get('stop_over_start') is not None:
                    sens[-1].stop_over_start = float(spec['stop_over_start'])
                    sens[-1].abort_over_start = float(spec.get('abort_over_start', spec['stop_over_start'] + 4))
                    sens[-1].stop_max = float(spec.get('stop_max', 1e9))     # a warm start must not raise the line
                    sens[-1].abort_max = float(spec.get('abort_max', 1e9))
            else:
                raise RuntimeError(f'sensor {spec["name"]}: unknown kind {kind}')
        self.sensors = sens

    def build_drives(self):
        rc, out = self.env.run(['lsblk', '-J', '-d', '-o', 'NAME,SERIAL,MODEL,TRAN'])
        try:
            blk = {str(b.get('serial') or '').strip(): b for b in json.loads(out)['blockdevices']}
        except (ValueError, KeyError, TypeError):
            blk = {}
        drives = []
        for spec in self.prof.get('drives', []):
            b = blk.get(spec['serial'])
            if b is None:
                raise RuntimeError(f'drive {spec["serial"]} not found (lsblk)')
            if spec['serial'] in DENY:
                raise RuntimeError(f'drive {spec["serial"]} is on the never-touch list')
            dev = f'/dev/{b["name"]}'
            proto = spec.get('proto', 'ata')
            s = Sensor(f'{spec.get("name", "drive")}.{b["name"]}.{spec["serial"]}', 'drive', dev,
                       stop=spec.get('stop'), abort=spec.get('abort'), n=int(spec.get('n', 2)))
            s.proto, s.serial = proto, spec['serial']
            drives.append(s)
        self.drives = drives

    def resolve_fio(self, fio):
        """-> list of /dev nodes for a fio spec; every one must be a profile drive (so it has stop lines)."""
        if self.host == 'makoto':
            raise RuntimeError('no disk load on makoto')
        devs = []
        if fio.get('pool'):
            rc, out = self.env.run(['zpool', 'status', '-P', fio['pool']])
            if rc != 0 or not re.search(r'^\s*state:\s+ONLINE\s*$', out, re.M):
                raise RuntimeError(f'pool {fio["pool"]}: not found or not ONLINE')
            if re.search(r'(resilver|scrub) in progress', out):
                raise RuntimeError(f'pool {fio["pool"]}: a scrub or resilver is running')
            section = 'data'
            for line in out.splitlines():
                s = line.strip()
                if s.split() and s.split()[0] in ('logs', 'cache', 'spares', 'special', 'dedup'):
                    section = s.split()[0]
                    continue
                m = re.match(r'(/dev/\S+)\s+(\S+)', s)
                if m and section == 'data':
                    if m.group(2) != 'ONLINE':
                        raise RuntimeError(f'{m.group(1)} is {m.group(2)}')
                    dev = self.env.realpath(re.sub(r'-part\d+$', '', m.group(1)))
                    dev = re.sub(r'^(/dev/sd[a-z]+)\d+$', r'\1', dev)
                    dev = re.sub(r'^(/dev/nvme\d+n\d+)p\d+$', r'\1', dev)
                    if dev not in devs:
                        devs.append(dev)
        for p in fio.get('devices', []):
            dev = self.env.realpath(p)
            if dev not in devs:
                devs.append(dev)
        if not devs:
            raise RuntimeError(f'fio {fio}: no devices')
        watched = {d.src for d in self.drives}
        for dev in devs:      # every disk fio reads must be a profile drive: stop lines and SMART health (NVMe too)
            if dev not in watched:
                raise RuntimeError(f'{dev} would be loaded but is not a profile drive (add it to "drives" with its proto)')
        return devs

    # ---------- readings
    def read_temp(self, s):
        try:
            if s.kind in ('hwmon', 'zone'):
                return int(self.env.read(s.src).strip()) / 1000.0
            if s.kind == 'battery':
                return int(self.env.read(s.src).strip()) / 10.0
            if s.kind == 'file':
                return self.read_file_sensor(s)
        except (OSError, ValueError):
            return None
        return None

    def read_file_sensor(self, s):
        """First fresh value among the sources (JSON state with a time key, or a textfile metric line), else None."""
        now = self.env.now()
        for src in s.src:
            try:
                text = self.env.read(src['path'])
                if 'json' in src:
                    d = json.loads(text)
                    v = d
                    for k in str(src['json']).split('.'):
                        v = v[k]
                    tk = src.get('time_key')
                    age = now - float(d[tk]) if tk and tk in d else now - self.env.mtime(src['path'])
                    if v is None or isinstance(v, bool):
                        continue
                    v = float(v)
                else:
                    age = now - self.env.mtime(src['path'])
                    lab = src.get('label', 'sensor')
                    vals = []
                    for line in text.splitlines():
                        m = re.match(re.escape(src['metric']) + r'\{([^}]*)\}\s+(-?[\d.eE+]+)\s*$', line.strip())
                        if not m:
                            continue
                        lv = re.search(re.escape(lab) + r'="([^"]*)"', m.group(1))
                        if lv and re.fullmatch(src.get('match', '.*'), lv.group(1)):
                            vals.append(float(m.group(2)))
                    if not vals:
                        continue
                    v = max(vals)
                if 0 <= age <= s.max_age:
                    return v
            except (OSError, ValueError, KeyError, TypeError, IndexError):
                continue
        return None

    def read_nvidia(self):
        rc, out = self.env.run(['nvidia-smi', '--query-gpu=temperature.gpu,fan.speed,power.draw,utilization.gpu',
                                '--format=csv,noheader,nounits'], timeout=20)
        try:
            f = [x.strip() for x in out.strip().splitlines()[0].split(',')]
            return {'gpu_temp': float(f[0]), 'gpu_fan_pct': f[1], 'gpu_w': f[2], 'gpu_util': f[3]}
        except (IndexError, ValueError):
            return {}

    def read_ipmi(self):
        rc, out = self.env.run(['ipmitool', 'sdr', 'type', 'temperature'], timeout=30)
        vals = {}
        for line in out.splitlines():
            f = [x.strip() for x in line.split('|')]
            if len(f) >= 5:
                m = re.match(r'(-?\d+(?:\.\d+)?) degrees C', f[4])
                if m:
                    vals[f[0]] = float(m.group(1))
        return vals

    def read_drive(self, d, health):
        if d.proto == 'nvme':
            args = ['smartctl', '-A', d.src]           # NVMe: no standby check
        else:
            args = ['smartctl', '-n', 'standby', '-A'] + (['-l', 'sasphy'] if health and d.proto == 'sas' else []) + [d.src]
        rc, out = self.env.run(args)
        return parse_smart(out, 'scsi' if d.proto == 'sas' else d.proto)

    def throttle(self):
        core = pkg = 0
        n = 0
        for p in self.env.glob('/sys/devices/system/cpu/cpu[0-9]*/thermal_throttle/core_throttle_count'):
            try:
                core += int(self.env.read(p).strip())
                n += 1
            except (OSError, ValueError):
                pass
        for p in self.env.glob('/sys/devices/system/cpu/cpu[0-9]*/thermal_throttle/package_throttle_count'):
            try:
                pkg = max(pkg, int(self.env.read(p).strip()))
            except (OSError, ValueError):
                pass
        return (core, pkg) if n else (None, None)

    def cpustat(self):
        try:
            f = [int(x) for x in self.env.read('/proc/stat').splitlines()[0].split()[1:]]
            return sum(f), f[3] + (f[4] if len(f) > 4 else 0)
        except (OSError, ValueError, IndexError):
            return None

    def mhz(self):
        v = []
        for p in self.env.glob('/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq'):
            try:
                v.append(int(self.env.read(p).strip()) / 1000.0)
            except (OSError, ValueError):
                pass
        return (sum(v) / len(v), max(v)) if v else (None, None)

    def rapl(self):
        tot = 0
        zones = [z for z in self.env.glob('/sys/class/powercap/intel-rapl:[0-9]')
                 if self.safe_read(f'{z}/name').startswith('package')]
        if not zones:
            return None
        for z in zones:
            try:
                tot += int(self.env.read(f'{z}/energy_uj').strip())
            except (OSError, ValueError):
                return None
        return tot

    def safe_read(self, p):
        try:
            return self.env.read(p).strip()
        except OSError:
            return ''

    # ---------- guards
    def check_guards(self, now, first=False):
        """-> list of stop reasons (each guard needs 2 bad checks in a row)."""
        g = self.prof.get('guards', {})
        probs = []

        def bad(key, is_bad, why):
            c = self.guard_state.get(key, 0) + 1 if is_bad else 0
            self.guard_state[key] = c
            if c >= 2:
                probs.append(f'{why} ({c} checks in a row)')
            elif c == 1:
                self.note(f'guard {key}: {why} (1 check; stops on the next)')

        if 'futaba_ha' in g:
            cfg = g['futaba_ha']
            st, secs, _ = self.env.http(cfg.get('ha_url', 'http://10.0.0.11:8123/'), 3)
            self.guard_vals['ha_s'] = f'{secs:.2f}' if st else 'fail'
            bad('ha', st is None or st >= 500 or secs > cfg.get('ha_max_s', 2.0), f'HA frontend {self.guard_vals["ha_s"]} s')
            st, secs, _ = self.env.http(cfg.get('prom_ready', 'http://localhost:9090/-/ready'), 3)
            self.guard_vals['prom_ready'] = st or 'fail'
            bad('prom_ready', st != 200, f'Prometheus /-/ready {st}')
            st, secs, body = self.env.http(cfg.get('prom_query', 'http://localhost:9090/api/v1/query?query=count(up%3D%3D0)'), 5)
            n = None
            try:
                res = json.loads(body)['data']['result']
                n = int(float(res[0]['value'][1])) if res else 0
            except (ValueError, KeyError, IndexError, TypeError):
                pass
            self.guard_vals['up0'] = '' if n is None else n
            if first and n is not None:
                self.guard_vals['up0_base'] = n
            base = self.guard_vals.get('up0_base')
            if base is None and n is not None:
                self.guard_vals['up0_base'] = base = n
            bad('up0', n is None or (base is not None and n >= base + 1), f'targets down {n} (start {base})')
        if 'makoto_fan' in g:      # every sample: the production controller must be running and current
            cfg = g['makoto_fan']
            unit, path = cfg.get('unit', 'makoto-fan'), cfg.get('state', '/run/makoto-fan.state')
            rc, out = self.env.run(['systemctl', 'is-active', unit], timeout=20)
            state = (out.strip().splitlines() or [f'rc{rc}'])[0]
            age, emerg = None, None
            try:
                d = json.loads(self.env.read(path))
                age = now - float(d['t']) if 't' in d else now - self.env.mtime(path)
                emerg = bool(d.get('emergency', False))
            except (OSError, ValueError, KeyError, TypeError):
                pass
            fine = state == 'active' and age is not None and age <= float(cfg.get('max_age', 120)) and not emerg
            self.guard_vals['makoto_fan'] = state
            self.guard_vals['makoto_fan_age'] = '' if age is None else int(age)
            why = f'{unit} {state}, state age {"?" if age is None else int(age)} s{", EMERGENCY" if emerg else ""}'
            if first and not fine:
                raise RuntimeError(f'{why}: no makoto load without its controller')
            bad('makoto_fan', not fine, why)
        if 'mirror_voice' in g and (first or now - self.guard_t >= GUARD_S - 1):
            since = int(self.mv_since if self.mv_since is not None else now) - 5    # small overlap: a repeat is harmless
            rc, out = self.env.run(['journalctl', '--user-unit=mirror-voice.service', '--since', f'@{since}',
                                    '--no-pager', '-o', 'cat'], timeout=30)
            if first:
                self.mv_since = now
            bad('mirror_voice_read', rc != 0, f'mirror-voice journal unreadable (rc {rc})')
            if rc == 0:
                hits = [l for l in out.splitlines() if 'wake (' in l or 'heard ' in l]
                self.guard_vals['voice_hits'] = len(hits)
                if hits and not first:
                    probs.append(f'mirror-voice in use (B4): {hits[-1].strip()[:100]}')
                self.mv_since = now
        if 'tinypc_sat' in g and (first or now - self.guard_t >= GUARD_S):
            for u in g['tinypc_sat'].get('units', ['mirror-voice-sat', 'whisper-gpu']):
                state = self.user_unit_state(g['tinypc_sat'].get('user', 'rohit'), u)
                self.guard_vals[f'{u}'] = state
                if first and state != 'active':
                    raise RuntimeError(f'{u} is {state} at the start: refusing (the load must not be what breaks it)')
                bad(u, state != 'active', f'{u} {state}')
        return probs

    def user_unit_state(self, user, unit):
        """'active' if the user's unit has a populated cgroup, else why not. Read-only and without D-Bus: inside a
        system service `systemctl --user -M user@` fails (no session bus: "Transport endpoint is not connected")."""
        try:
            uid = self.env.uid(user)
        except (KeyError, OSError):
            return f'inactive (no user {user})'
        base = f'/sys/fs/cgroup/user.slice/user-{uid}.slice/user@{uid}.service'
        name = unit if unit.endswith('.service') else unit + '.service'
        hits = self.env.glob(f'{base}/**/{name}')
        if not hits:
            return 'inactive (no cgroup)'
        for h in hits:
            try:
                if re.search(r'^populated 1\s*$', self.env.read(f'{h}/cgroup.events'), re.M):
                    return 'active'
            except OSError:
                pass
            try:
                if self.env.read(f'{h}/cgroup.procs').strip():
                    return 'active'
            except OSError:
                pass
        return 'inactive (empty cgroup)'

    # ---------- load control
    def stop_load(self):
        """TERM to each load's whole process group, wait up to 10 s, then KILL to the group whether or not the leader is
        still alive (fio's job processes and stress-ng's workers can outlive their main process)."""
        for attr in ('stress', 'fio'):
            p = getattr(self, attr)
            if p is not None:
                self.env.killgroup(p, signal.SIGTERM)
                for _ in range(20):
                    if p.poll() is not None:
                        break
                    self.env.sleep(0.5)
                self.env.killgroup(p, signal.SIGKILL)
            setattr(self, attr, None)
        self.early_noted = set()
        self.cur = None
        self.env.remove(self.job)

    def stress_args(self, cpu, secs):
        assert cpu >= 1, 'stress-ng with 0 workers means one per CPU: never started'
        # --cpu N --cpu-method matrixprod, as ryuji-floor.py and mementos-steps.py (there is no --matrixprod option:
        # stress-ng 0.17.06 exits rc 1 on it, which on 10-20 04:32 left a step with no load)
        return ['stress-ng', '--cpu', str(cpu), '--cpu-method', 'matrixprod', '--timeout', f'{int(secs)}s',
                '--temp-path', '/tmp', '--quiet']

    def stress_cmd(self, cpu, nice, secs):
        return ['nice', '-n', str(nice)] + self.stress_args(cpu, secs)

    def argv_check(self):
        """--selftest: the host's own stress-ng and fio parse this plan's exact arguments (stress-ng --dry-run, fio
        --parse-only on the job file written to its runtime path and removed); no load runs. -> list of failures."""
        bad = []
        for st in self.steps:
            if st['cpu'] >= 1:
                rc, out = self.env.run(self.stress_args(st['cpu'], 60) + ['--dry-run'], timeout=30)
                self.env.out(f'  argv check {st["name"]}: stress-ng --dry-run rc {rc}')
                if rc != 0:
                    bad.append(f'{st["name"]}: stress-ng rc {rc}: {out.strip()[-160:]}')
            if st['fio']:
                self.env.write(self.job, self.fio_job(st['fio']['mode'], st['fio_devs'], 60), 'w')
                try:
                    rc, out = self.env.run(['fio', '--readonly', '--parse-only', self.job], timeout=30)
                finally:
                    self.env.remove(self.job)
                self.env.out(f'  argv check {st["name"]}: fio --readonly --parse-only rc {rc}')
                if rc != 0:
                    bad.append(f'{st["name"]}: fio rc {rc}: {out.strip()[-160:]}')
        return bad

    def fio_job(self, mode, devs, secs):
        opts = {'seq': 'rw=read\nbs=1M\niodepth=4', 'rand': 'rw=randread\nbs=64k\niodepth=16'}[mode]
        txt = f'[global]\ndirect=1\nioengine=libaio\n{opts}\ntime_based=1\nruntime={int(secs)}\ngroup_reporting=0\n'
        for d in devs:
            txt += f'[{os.path.basename(d)}]\nfilename={d}\n'
        return txt

    def start_step(self, st, secs):
        self.stop_load()
        if st['cpu'] >= 1:
            self.stress = self.env.popen(self.stress_cmd(st['cpu'], st['nice'], secs + 120))
        fdesc = ''
        if st['fio']:
            self.env.write(self.job, self.fio_job(st['fio']['mode'], st['fio_devs'], secs + 60), 'w')
            self.fio = self.env.popen(['nice', '-n', str(st['nice']), 'fio', '--readonly', self.job])
            fdesc = f'{st["fio"]["mode"]}:{len(st["fio_devs"])}'
        self.cur = (st['cpu'], fdesc)

    # ---------- one sample
    def sample(self, now, phase, t0, first=False):
        stops, row = [], {}
        st = self.cpustat()
        busy = None
        if st and self.stat0:
            dt, di = st[0] - self.stat0[0], st[1] - self.stat0[1]
            busy = 100.0 * (1 - di / dt) if dt > 0 else None
        self.stat0 = st
        e = self.rapl()
        pw = None
        if e is not None and self.rapl0 is not None and now > self.rapl0[0]:
            d = e - self.rapl0[1]
            pw = d / 1e6 / (now - self.rapl0[0]) if d >= 0 else None
        self.rapl0 = (now, e) if e is not None else None
        mean, mx = self.mhz()
        core, pkg = self.throttle()
        if first:
            if self.vendor == 'intel' and core is None:
                raise RuntimeError('thermal_throttle counters unreadable at the start on an Intel host: the throttle stop would be off')
            self.thr0 = (core, pkg)
        if self.vendor == 'intel' and core is not None and self.thr0 and self.thr0[0] is not None:
            if core > self.thr0[0] or pkg > self.thr0[1]:
                stops.append(f'thermal throttle events since the start: core {core - self.thr0[0]}, package {pkg - self.thr0[1]}')
        row.update({'busy_pct': '' if busy is None else f'{busy:.0f}', 'mhz_mean': '' if mean is None else f'{mean:.0f}',
                    'mhz_max': '' if mx is None else f'{mx:.0f}', 'pkg_w': '' if pw is None else f'{pw:.1f}',
                    'thr_core': '' if core is None else core, 'thr_pkg': '' if pkg is None else pkg})
        # sensors
        nvidia = ipmi = None
        nv_due = first or now - self.nv_t >= SMART_S - 1
        ipmi_due = first or now - self.ipmi_t >= GUARD_S - 1
        if nv_due:
            self.nv_t = now
        if ipmi_due:
            self.ipmi_t = now
        for s in self.sensors:
            if s.kind == 'nvidia':
                s.fresh = nv_due
                if nv_due:
                    nvidia = nvidia if nvidia is not None else self.read_nvidia()
                    s.value = nvidia.get('gpu_temp')
                    for k in ('gpu_fan_pct', 'gpu_w', 'gpu_util'):
                        self.guard_vals[k] = nvidia.get(k, '')
                v = s.value
            elif s.kind == 'ipmi':
                if ipmi_due:
                    ipmi = ipmi if ipmi is not None else self.read_ipmi()
                    s.value = ipmi.get(s.src)
                    if first and getattr(s, 'stop_over_start', None) is not None:
                        if s.value is None:
                            raise RuntimeError(f'{s.name}: no IPMI reading at the start')
                        s.stop = min(s.value + s.stop_over_start, s.stop_max)
                        s.abort = min(s.value + s.abort_over_start, s.abort_max)
                        self.note(f'{s.name}: start {s.value:g}C -> stop {s.stop:g}C, abort {s.abort:g}C')
                    s.fresh = True
                else:
                    s.fresh = False
                v = s.value
            else:
                v = self.read_temp(s)
                s.value = v
            row[s.name] = '' if v is None else f'{v:g}'
            self.judge(s, v, stops, fresh=s.fresh)
        # drives (SATA/SAS by smartctl, at most every SMART_S; health every HEALTH_S)
        if self.drives and (first or now - self.smart_t >= SMART_S - 1):
            health = first or now - self.health_t >= HEALTH_S - 5
            self.smart_t = now
            if health:
                self.health_t = now
            for d in self.drives:
                r = self.read_drive(d, health)
                d.value = r.get('temp')
                asleep = r.get('standby') and not (self.fio is not None)
                b = self.drive_base.setdefault(d.src, {})
                for k in ('defects', 'realloc', 'pending', 'crc', 'media_errors', 'crit_warning', 'phy'):
                    if k not in b and k in r:      # baseline from the first read that has the field
                        b[k] = r[k]
                if health:
                    for p in health_problems(b, r, self.phy_jump):
                        stops.append(f'{d.name}: {p}')
                self.judge(d, d.value, stops, fresh=not asleep)
                row[d.name] = '' if d.value is None else d.value
        else:
            for d in self.drives:
                row[d.name] = '' if d.value is None else d.value
        # guards
        gp = self.check_guards(now, first)
        stops += gp
        if first or now - self.guard_t >= GUARD_S - 1:
            self.guard_t = now
        for k, v in self.guard_vals.items():
            if k != 'up0_base':
                row[k] = v
        return stops, row

    def judge(self, s, v, stops, fresh=True):
        if s.log_only or not fresh or not self.judging:
            return
        if v is None:
            s.missing += 1
            if s.missing >= 3:
                stops.append(f'{s.name}: no reading 3 times in a row')
            return
        s.missing = 0
        if s.abort is not None and v >= s.abort:
            stops.append(f'{s.name} {v:g}C at its abort line {s.abort:g}C (one reading)')
            s.over += 1
            return
        if s.stop is not None and v >= s.stop:
            s.over += 1
            if s.over >= s.n:
                stops.append(f'{s.name} {v:g}C at its stop line {s.stop:g}C ({s.over} readings in a row)')
            else:
                self.note(f'{s.name} {v:g}C at its stop line {s.stop:g}C ({s.over} of {s.n} readings)')
        else:
            s.over = 0

    # ---------- run
    def columns(self, row):
        fixed = ['epoch', 'time', 'phase', 'phase_min', 'cpu', 'fio']
        return fixed + list(row.keys())

    def emit(self, now, phase, t0, row):
        vals = [int(now), time.strftime('%T', time.localtime(now)), phase, f'{(now - t0) / 60:.1f}',
                self.cur[0] if self.cur else 0, self.cur[1] if self.cur else '']
        vals += [str(row.get(c, '')).replace(',', ';') for c in self.cols[6:]]
        self.env.write(self.csv, ','.join(map(str, vals)) + '\n')

    def setup(self):
        self.load_docs()
        self.build_sensors()
        self.build_drives()
        guards = self.prof.get('guards', {})
        known = {'futaba_ha', 'tinypc_sat', 'sojiro_ipmi', 'mirror_voice', 'makoto_fan'}
        unknown = sorted(set(guards) - known)
        if unknown:
            raise RuntimeError(f'unknown guard keys {unknown} (known: {", ".join(sorted(known))})')
        if self.host == 'makoto' and 'makoto_fan' not in guards:
            raise RuntimeError('makoto needs the makoto_fan guard (its controller must be checked on every sample)')
        if 'sojiro_ipmi' in guards and not any(x.kind == 'ipmi' for x in self.sensors):
            raise RuntimeError('guard sojiro_ipmi needs ipmi sensors in the profile')
        for st in self.steps:
            st['fio_devs'] = self.resolve_fio(st['fio']) if st['fio'] else []

    def run(self):
        self.setup()
        now = self.env.now()
        stops, row = self.sample(now, 'start', now, first=True)
        dead = [x.name for x in self.sensors if x.value is None and not x.log_only and not x.optional]
        if dead and not self.selftest:
            raise RuntimeError(f'no reading at the start from {dead}: their stop lines could not act')
        if self.selftest:
            return self.report(row, stops)
        cols = self.columns(row)
        fresh_csv = not self.env.exists(self.csv)
        if fresh_csv:
            self.env.write(self.csv, ','.join(cols) + '\n', 'w')
        self.cols = cols
        for line in self.early:
            self.env.write(self.csv, line)
        self.early = []
        if not fresh_csv:
            self.note('appending; columns: ' + ','.join(self.cols))
        self.note(f'start {self.label} on {self.host}: {len(self.steps)} steps, {len(self.sensors)} sensors, '
                  f'{len(self.drives)} drives, guards {sorted(self.prof.get("guards", {}))}, LOAD_UNTIL {self.load_until:.0f}')
        for n in self.notes_pending:
            self.note(n)
        for s in self.sensors + self.drives:
            if not s.log_only:
                self.note(f'stop line {s.name}: now {s.value}, stop {s.stop} ({s.n} readings), abort {s.abort}')
        if stops:
            self.note('STOP: at the start, before any load: ' + '; '.join(stops))
            return self.cooldown(4, 'start')
        self.emit(now, 'start', now, row)
        for st in self.steps:
            now = self.env.now()
            if now >= self.load_until:
                self.note(f'{st["name"]}: past LOAD_UNTIL, not started')
                break
            end = now + st['min'] * 60 if st['min'] > 0 else float('inf')
            if st['until'] is not None:
                end = min(end, st['until'])
            end = min(end, self.load_until)
            if end - now < 30:
                self.note(f'{st["name"]}: ends in {end - now:.0f} s, skipped')
                continue
            self.start_step(st, end - now)
            self.note(f'phase {st["name"]}: cpu {st["cpu"]} (nice {st["nice"]}), fio {self.cur[1] or "none"}, '
                      f'{(end - now) / 60:.1f} min to {time.strftime("%H:%M", time.localtime(end))}')
            t0 = now
            while True:
                self.env.sleep(SAMPLE_S)
                now = self.env.now()
                stops, row = self.sample(now, st['name'], t0)
                for attr, what in (('stress', 'stress-ng'), ('fio', 'fio')):
                    p = getattr(self, attr)       # kept even when its leader has exited: stop_load kills the group
                    if p is not None and p.poll() is not None and now < end - 5 and attr not in self.early_noted:
                        self.note(f'{st["name"]}: {what} ended early (rc {p.poll()})')
                        self.early_noted.add(attr)
                self.emit(now, st['name'], t0, row)
                if stops:
                    self.stop_load()
                    self.note(f'STOP: {st["name"]}: ' + '; '.join(stops))
                    return self.cooldown(4, st['name'])
                if now >= self.load_until:
                    self.stop_load()
                    self.note(f'{st["name"]}: LOAD_UNTIL reached: load off')
                    return self.cooldown(0, st['name'], self.tail_s if self.ev.get('TAIL_S') else 0)
                if now >= end:
                    break
        self.stop_load()
        self.note('plan done: load off')
        return self.cooldown(0, 'end', float(self.ev.get('TAIL_S', '') or 0))

    def cooldown(self, rc, phase, secs=None):
        secs = self.tail_s if secs is None else secs
        self.judging = False          # the load is off: log only
        t0 = self.env.now()
        if secs > 0:
            self.note(f'logging {secs / 60:.0f} more min with the load off')
        while self.env.now() - t0 < secs:
            self.env.sleep(SAMPLE_S)
            now = self.env.now()
            _, row = self.sample(now, 'cooldown', t0)
            self.emit(now, 'cooldown', t0, row)
        self.note(f'exit {rc}')
        return rc

    def report(self, row, stops):
        o = self.env.out
        argv_bad = self.argv_check()
        if argv_bad:
            stops = list(stops) + ['ARGV CHECK FAILED: ' + '; '.join(argv_bad)]
        o(f'host {self.host}: profile {self.prof.get("host")}, vendor {self.vendor}, max_cpu {self.max_cpu}')
        for s in self.sensors + self.drives:
            o(f'  {s.kind:7} {s.name:40} now {s.value!s:>6}  stop {s.stop!s:>6} (n={s.n})  abort {s.abort!s:>6}'
              f'  target {s.target!s:>6}{"  LOG ONLY" if s.log_only else ""}  src {s.src}')
        o(f'  busy {row.get("busy_pct")} %, MHz mean/max {row.get("mhz_mean")}/{row.get("mhz_max")}, '
          f'throttle core/pkg {row.get("thr_core")}/{row.get("thr_pkg")}, guards {self.guard_vals}')
        for n in self.notes_pending:
            o('  note: ' + n)
        if stops:
            o('  WOULD STOP AT THE START: ' + '; '.join(stops))
        t = self.env.now()
        for st in self.steps:
            end = t + st['min'] * 60 if st['min'] > 0 else float('inf')
            if st['until'] is not None:
                end = min(end, st['until'])
            o(f'  step {st["name"]}: cpu {st["cpu"]} nice {st["nice"]}, '
              f'{"stress-ng: " + " ".join(self.stress_cmd(st["cpu"], st["nice"], 60)) if st["cpu"] else "no stress-ng"}; '
              f'fio {st["fio"] or "none"} on {st["fio_devs"]}; until {time.strftime("%F %H:%M", time.localtime(end)) if end < 1e17 else "?"}')
        return 0 if not stops else 3


def main(argv, env=None, env_vars=None):
    L = Load(argv, env, env_vars)

    def on_term(*a):
        L.stop_load()
        L.note('stopped (SIGTERM): load off')
        sys.exit(0)

    if env is None:
        signal.signal(signal.SIGTERM, on_term)
    try:
        return L.run()
    except (RuntimeError, OSError, ValueError, KeyError) as e:
        L.stop_load()
        if L.cols is None:
            L.cols = []                  # no header: the refusal goes straight to the file as a note
            for line in L.early:
                L.env.write(L.csv, line)
        L.note(f'STOP: refused: {type(e).__name__}: {e}')
        return 2
    finally:
        if L.stress is not None or L.fio is not None:
            L.stop_load()


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
