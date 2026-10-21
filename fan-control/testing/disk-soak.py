#!/usr/bin/env python3
# disk-soak (2026-10-13; v2 2026-10-20): read-only drive heat soak.
# usage (root): disk-soak.py [--selftest] <label> <pool> <phases> [limit C]
#   phases: comma list of mode:minutes, mode seq (1 MiB sequential reads, queue depth 4, like a scrub) or rand
#   (64 KiB random reads across the whole disk, queue depth 16: the most seeking, the most heat).
#   limit: optional, only lowers the per-class stop line of the loaded disks (min of the two).
#   --selftest: read-only discovery (devices, serials, classes, stop lines, one SMART snapshot, fan states, the fio job
#   it would run, and `fio --readonly --parse-only` on that job, written to its runtime path and removed: the host's
#   own fio parses it, no I/O); starts no load; exit 3 if fio rejects the job.
# Every data disk of <pool> (from zpool status -P; log, cache, spare and special devices excluded) gets its own fio job
# on the raw disk with --readonly (fio refuses any write or trim) and O_DIRECT. Nothing is written anywhere and no file
# system is involved, so the pool's data cannot change; ZFS only sees slower I/O while it runs. The pool's log, cache,
# spare and special devices (and WATCH_EXTRA) are watched (temperature and SMART) but not loaded.
# Every 60 s: each device's temperature (one smartctl -A per device, one at a time), MB/s read over the minute
# (/proc/diskstats) and the fan controllers' levels go to /var/tmp/disk-soak-<label>.csv, one column per device named
# <dev>_<serial>; the start notes list each device with model, class, stop line and watch-list status.
# Stops (fio killed, a "STOP:" note):
#   exit 3: a device at its class stop line on 2 reads in a row, or 5C over it on one read (env STOP_SAS10K 50,
#           STOP_HUSMM 60, STOP_EXOS 54, STOP_MG04 50, STOP_HGST 55, STOP_HDD 50, STOP_SATA_SSD 65; NVMe: its warning
#           temperature - NVME_MARGIN 5), or any watched device without a temperature for 3 reads in a row
#   exit 3 also on a shelf soak (pools in SHELF_POOLS, default dataPool): the enclosure's backplane / SIM / expander
#           from md1200-fan's /run/md1200-fan.state ("temps", "time"), read every sample: at or above 48 / 60 / 88C on
#           2 readings in a row, or 52 / 64 / 92C on one; a state missing or older than 120 s is a missing reading
#           (keeps the count) and 60 s without a fresh one stops; no fresh state at the start refuses (exit 2)
#   exit 4: SMART health against the start snapshot, re-read every HEALTH_EVERY s (600): any new SAS grown defect,
#           SATA Reallocated_Sector_Ct (5) or Current_Pending_Sector (197), NVMe media error or new critical warning;
#           a SAS phy counter (invalid DWORD, running disparity, loss of DWORD sync, phy reset problem, from
#           smartctl -l sasphy) or SATA UDMA_CRC_Error_Count (199) up by more than PHY_JUMP (100) over the soak; or a
#           loaded disk whose SMART data can't be read twice in a row
#   exit 5: night fan caps (env FAN_CAP_SHELF, FAN_CAP_R720, percent, default none): md1200-fan's and fan-watchdog's
#           own state files (/run/md1200-fan.state, /run/fan-watchdog.state; lab_thermal.prom as fallback) read once a
#           minute; a level above the cap (iDRAC auto counts as 100%), or no fresh state (older than 300 s), on two
#           reads in a row stops the soak. With a cap set, an unreadable state at the start refuses the soak (exit 2).
# Starts no new phase after LOAD_UNTIL (epoch, env) and stops the running one when it passes (exit 0). SIGTERM
# (systemctl stop) kills fio too (exit 0). Refuses (exit 2) on makoto, and if a data disk is on the never-touch list
# (makoto's backupPool, sojiro's old pool drives in ryuji). Reads only: smartctl -A / -i / -c / -l sasphy, lsblk,
# zpool status, /proc/diskstats and the controllers' state files. No SES, IPMI or BMC access.
import json, os, re, signal, socket, subprocess, sys, time

# Never loaded and never read (serials): makoto's backupPool MX500s; sojiro's old pool drives, unimported in ryuji.
DENY = {'2152E5F70B12': "makoto backupPool", '2016E29B77F7': "makoto backupPool", '2007E28BD0DA': "makoto backupPool",
        '67H5K3L0FSZC': "sojiro's old pool (in ryuji)", '67H4K4ELFSZC': "sojiro's old pool (in ryuji)",
        '28NXK3O0FSYC': "sojiro's old pool (in ryuji)", '28OYK4BFFSYC': "sojiro's old pool (in ryuji)"}
# Lab drive audit 2026-10-15 watch list (by serial; vmPool was re-paired 10-17, so sdX names moved).
WATCH = {'S3L06AZX': 'worn vmPool 10K (902 write retries)', 'S3L07QG1': 'worn vmPool 10K (recovered reads, 931 write retries)',
         'S3L05JMN': 'worn vmPool 10K (recovered-read burst)', 'S3L06G7G': 'worn vmPool 10K (352 delayed-ECC)',
         'S3L03MHA': 'worn vmPool 10K (817 write retries)', 'S3L07J7K': 'worn vmPool 10K (657 delayed-ECC)',
         'S3L05M1Y': 'worn vmPool 10K (old recovered-read burst, sync losses)',
         'S3L06H7J': 'worn vmPool 10K (still logging recovered reads)',
         '2MW3LE6A': 'mementos rear SSD, boot (SAS link errors)', '2MW3LJMA': 'mementos rear SSD, SLOG/L2ARC (SAS link errors)',
         '2016E29B77F7': "makoto's MX500 (14 uncorrectables)"}
CLASS_STOP = {'sas10k': 50, 'husmm': 60, 'exos': 54, 'mg04': 50, 'hgst': 55, 'hdd': 50, 'sata_ssd': 65}
PHY_KINDS = {'Invalid DWORD count': 'invalid_dword', 'Running disparity error count': 'disparity',
             'Loss of DWORD synchronization count': 'loss_sync', 'Phy reset problem count': 'reset_problem'}
TICK = 60
# Shelf enclosure stop lines (brief B7: backplane 48 / SIM 60 / expander 88C; SES backplane warns 50, critical 55;
# abort = stop + 4), read from md1200-fan's own state file (never SES: md1200-fan owns it). (stop, abort) in C.
SHELF_LIMITS = {'backplane': (48, 52), 'SIM': (60, 64), 'expander': (88, 92)}
SHELF_MAX_AGE, SHELF_BLIND = 120, 60     # a state older than 120 s is a missing reading; blind for 60 s stops
ABORT_ABOVE = 5   # one read at stop + 5 (the part's own limit) stops at once; the stop line itself needs 2 reads


class Env:
    """The OS as the soak sees it; the dry-run harness swaps in a fake one."""

    def now(self):
        return time.time()

    def sleep(self, s):
        time.sleep(s)

    def run(self, args, timeout=90):
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
            return r.returncode, r.stdout
        except (OSError, subprocess.TimeoutExpired) as e:
            return 255, f'{type(e).__name__}: {e}'

    def read(self, path):
        with open(path) as f:
            return f.read()

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

    def popen(self, args):
        # fio's own messages go to the journal; its own process group, still in this unit's cgroup
        return subprocess.Popen(args, stdout=subprocess.DEVNULL, start_new_session=True)

    def killgroup(self, proc, sig):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass

    def out(self, text):
        print(text, flush=True)


def envnum(env_vars, name, default, bad=None):
    v = env_vars.get(name, '')
    if v.strip() == '':
        return default
    try:
        return float(v)
    except ValueError:
        if bad is not None:
            bad.append(f'{name}={v!r}')    # a set value that does not parse refuses the run (exit 2)
        return default


def first_int(s):
    m = re.search(r'-?\d+', s.replace(',', ''))
    return int(m.group(0)) if m else None


def parse_smart(text, proto):
    """smartctl -A [-l sasphy] output -> dict: temp, defects / ata / nvme fields, phy counters."""
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
                attrs[int(m.group(1))] = (m.group(2), m.group(3))
        for i in (194, 190):
            if i in attrs:
                t = first_int(attrs[i][1])
                if t is not None and 0 < t < 100:
                    d['temp'] = t
                    break
        for i, k in ((5, 'realloc'), (197, 'pending'), (198, 'offline_unc'), (199, 'crc')):
            if i in attrs:
                d[k] = first_int(attrs[i][1])
        return d
    # SCSI / SAS
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
    """New problems of one device against its start snapshot (empty list = fine)."""
    out = []
    for k, label in (('defects', 'grown defects'), ('realloc', 'Reallocated_Sector_Ct'),
                     ('pending', 'Current_Pending_Sector'), ('media_errors', 'NVMe media errors')):
        if k in base and k in cur and cur[k] > base[k]:
            out.append(f'{label} {base[k]} -> {cur[k]}')
    if 'crit_warning' in cur and cur['crit_warning'] & ~base.get('crit_warning', 0):
        out.append(f'NVMe critical warning 0x{base.get("crit_warning", 0):02x} -> 0x{cur["crit_warning"]:02x}')
    if 'crc' in base and 'crc' in cur and cur['crc'] - base['crc'] > phy_jump:
        out.append(f'UDMA_CRC_Error_Count {base["crc"]} -> {cur["crc"]} (> +{phy_jump:g})')
    for k, v in cur.get('phy', {}).items():
        b = base.get('phy', {}).get(k)
        if b is not None and v - b > phy_jump:
            out.append(f'SAS phy {k} {b} -> {v} (> +{phy_jump:g})')
    return out


class Soak:
    def __init__(self, argv, env=None, env_vars=None):
        self.env = env or Env()
        self.ev = os.environ if env_vars is None else env_vars
        args = [a for a in argv if a != '--selftest']
        self.selftest = len(args) != len(argv)
        if len(args) < 3:
            raise SystemExit('usage: disk-soak.py [--selftest] <label> <pool> <phases> [limit C]')
        self.label, self.pool, self.phases_arg = args[0], args[1], args[2]
        self.limit = float(args[3]) if len(args) > 3 else None
        self.phases = []
        for ph in self.phases_arg.split(','):
            mode, mins = ph.split(':')
            if mode not in ('seq', 'rand'):
                raise SystemExit(f'bad phase mode {mode!r} (seq or rand)')
            self.phases.append((mode, float(mins)))
        ev = self.ev
        self.bad_env = []
        self.load_until = envnum(ev, 'LOAD_UNTIL', float('inf'), self.bad_env)
        self.phy_jump = envnum(ev, 'PHY_JUMP', 100, self.bad_env)
        self.health_every = envnum(ev, 'HEALTH_EVERY', 600, self.bad_env)
        self.caps = {k: envnum(ev, f'FAN_CAP_{k.upper()}', None, self.bad_env) for k in ('shelf', 'r720')}
        self.state_max_age = envnum(ev, 'FAN_STATE_MAX_AGE', 300, self.bad_env)
        self.md_state = ev.get('MD_STATE', '/run/md1200-fan.state')
        self.fw_state = ev.get('FW_STATE', '/run/fan-watchdog.state')
        self.prom = ev.get('LAB_THERMAL_PROM', '/var/lib/node_exporter/textfile_collector/lab_thermal.prom')
        self.csv = f'{ev.get("CSV_DIR", "/var/tmp")}/disk-soak-{self.label}.csv'
        self.job = f'{ev.get("RUN_DIR", "/run")}/disk-soak-{self.label}.fio'
        self.class_stop = {k: envnum(ev, f'STOP_{k.upper()}', v, self.bad_env) for k, v in CLASS_STOP.items()}
        self.nvme_margin = envnum(ev, 'NVME_MARGIN', 5, self.bad_env)
        self.deny = dict(DENY)
        for s in ev.get('EXCLUDE_SERIALS', '').split():
            self.deny[s] = 'EXCLUDE_SERIALS'
        self.fio = None
        self.devs = []          # dicts: dev, name, serial, model, proto, cls, stop, role (data|watch), watch note
        self.base = {}          # dev -> start snapshot
        self.unread = {}        # dev -> consecutive failed health reads
        self.fan_bad = {'shelf': 0, 'r720': 0}
        self.fans_logged = False
        self.shelf = self.pool in self.ev.get('SHELF_POOLS', 'dataPool').split()
        self.shelf_over = {k: 0 for k in SHELF_LIMITS}
        self.shelf_fresh_t = None
        self.notemp = {}        # dev -> consecutive ticks without a temperature
        self.overt = {}         # dev -> consecutive ticks at or over its stop line

    # ---- output
    def note(self, m):
        if not self.selftest:
            self.env.write(self.csv, f'# {int(self.env.now())} {time.strftime("%F %T %Z", time.localtime(self.env.now()))} {m}\n')
        self.env.out(m)

    # ---- discovery
    def pool_devices(self):
        rc, out = self.env.run(['zpool', 'status', '-P', self.pool])
        if rc != 0:
            raise RuntimeError(f'zpool status {self.pool} failed (rc {rc}): {out.strip()[:200]}')
        if not re.search(r'^\s*state:\s+ONLINE\s*$', out, re.M):
            raise RuntimeError(f'pool {self.pool} is not ONLINE')
        if re.search(r'(resilver|scrub) in progress', out):
            raise RuntimeError(f'pool {self.pool}: a scrub or resilver is running')
        data, aux, section = [], [], 'data'
        for line in out.splitlines():
            s = line.strip()
            if s.split() and s.split()[0] in ('logs', 'cache', 'spares', 'special', 'dedup'):
                section = s.split()[0]
                continue
            m = re.match(r'(/dev/\S+)\s+(\S+)', s)
            if not m:
                continue
            if section == 'data' and m.group(2) != 'ONLINE':
                raise RuntimeError(f'{m.group(1)} is {m.group(2)}, not ONLINE')
            p = re.sub(r'-part\d+$', '', m.group(1))
            dev = self.env.realpath(p)
            if re.match(r'/dev/sd[a-z]+\d+$', dev):
                dev = re.sub(r'\d+$', '', dev)
            dev = re.sub(r'^(/dev/nvme\d+n\d+)p\d+$', r'\1', dev)
            if section == 'data':
                if dev not in data:
                    data.append(dev)
            elif dev not in aux:
                aux.append(dev)
        return data, aux

    def lsblk(self, dev):
        rc, out = self.env.run(['lsblk', '-J', '-d', '-o', 'NAME,SERIAL,MODEL,ROTA,TRAN', dev])
        try:
            b = json.loads(out)['blockdevices'][0]
            return {k: (str(v).strip() if v is not None else '') for k, v in b.items()}
        except (ValueError, KeyError, IndexError, TypeError):
            return {'name': os.path.basename(dev), 'serial': '', 'model': '', 'rota': '', 'tran': ''}

    def classify(self, d):
        rc, info = self.env.run(['smartctl', '-i', d['dev']])
        model = d['model'] or ''
        m = re.search(r'^(?:Device Model|Product|Model Number):\s+(.+)$', info, re.M)
        if m and not model:
            model = m.group(1).strip()
        if d['name'].startswith('nvme') or 'NVMe' in info:
            proto = 'nvme'
        elif re.search(r'Transport protocol:\s+SAS', info):
            proto = 'sas'
        elif re.search(r'^(?:ATA|SATA) Version is', info, re.M):
            proto = 'ata'
        else:
            proto = 'scsi'
        rota = d.get('rota') in ('1', 'True', 'true')
        if 'ST1200MM' in model:
            cls = 'sas10k'
        elif 'HUSMM' in model:
            cls = 'husmm'
        elif 'ST8000NM' in model:
            cls = 'exos'
        elif 'MG04' in model:
            cls = 'mg04'
        elif 'HUS724040' in model:
            cls = 'hgst'
        elif proto == 'nvme':
            cls = 'nvme'
        elif rota or re.search(r'Rotation Rate:\s+\d+ rpm', info):
            cls = 'hdd'
        else:
            cls = 'sata_ssd'
        if cls == 'nvme':
            rc, c = self.env.run(['smartctl', '-c', d['dev']])
            m = re.search(r'Warning\s+Comp\.\s+Temp\.\s+Threshold:\s+(\d+)', c)
            stop = (int(m.group(1)) - self.nvme_margin) if m else 75
        else:
            stop = self.class_stop[cls]
        return model, proto, cls, stop

    def discover(self):
        if self.env.hostname() == 'makoto':
            raise RuntimeError('refusing to run on makoto (its backupPool and the session host are never soaked)')
        data, aux = self.pool_devices()
        extra = [self.env.realpath(p) for p in self.ev.get('WATCH_EXTRA', '').split()]
        devs = []
        for role, lst in (('data', data), ('watch', aux + extra)):
            for dev in lst:
                if any(x['dev'] == dev for x in devs):
                    continue
                d = dict(self.lsblk(dev), dev=dev, role=role)
                d['name'] = d.get('name') or os.path.basename(dev)
                if role == 'data' and not d['serial']:
                    raise RuntimeError(f'{dev} has no serial (lsblk): the never-touch check needs one')
                if d['serial'] in self.deny:
                    if role == 'data':
                        raise RuntimeError(f'{dev} ({d["serial"]}) is on the never-touch list: {self.deny[d["serial"]]}')
                    continue
                d['model'], d['proto'], d['cls'], d['stop'] = self.classify(d)
                if role == 'data' and self.limit is not None:
                    d['stop'] = min(d['stop'], self.limit)
                d['watchnote'] = WATCH.get(d['serial'], '')
                devs.append(d)
        if not any(d['role'] == 'data' for d in devs):
            raise RuntimeError(f'no data disks found in {self.pool}')
        self.devs = devs

    # ---- SMART
    def read_smart(self, d, health):
        args = ['smartctl', '-A'] if d['proto'] == 'nvme' else ['smartctl', '-n', 'standby', '-A']
        if health and d['proto'] == 'sas':
            args += ['-l', 'sasphy']
        rc, out = self.env.run(args + [d['dev']])
        return parse_smart(out, 'scsi' if d['proto'] == 'sas' else d['proto'])

    def snapshot(self):
        for d in self.devs:
            self.base[d['dev']] = self.read_smart(d, True)

    def check_health(self, cur):
        """cur: dev -> parsed health read. Returns problems (stop reasons) and notes."""
        probs, notes = [], []
        for d in self.devs:
            c, b = cur.get(d['dev'], {}), self.base.setdefault(d['dev'], {})
            want = [k for k in ('defects', 'realloc', 'pending', 'media_errors', 'phy') if k in b]
            if want and not all(k in c for k in want):
                self.unread[d['dev']] = self.unread.get(d['dev'], 0) + 1
                msg = f'{d["name"]} {d["serial"]}: SMART health unreadable ({self.unread[d["dev"]]} in a row)'
                if d['role'] == 'data' and self.unread[d['dev']] >= 2:
                    probs.append(msg)
                else:
                    notes.append(msg)
                continue
            self.unread[d['dev']] = 0
            for k in ('defects', 'realloc', 'pending', 'offline_unc', 'crc', 'media_errors', 'crit_warning', 'phy'):
                if k not in b and k in c:     # lazily fill a baseline missed at the start (drive in standby)
                    b[k] = c[k]
            for p in health_problems(b, c, self.phy_jump):
                probs.append(f'{d["name"]} {d["serial"]}: {p}')
        return probs, notes

    # ---- fans
    def read_fans(self):
        """-> {'shelf': (pct or None, age or None, source), 'r720': (...)}; iDRAC auto = 100."""
        now, res = self.env.now(), {}
        prom = None

        def promval(name, label=None):
            nonlocal prom
            if prom is None:
                try:
                    prom = (self.env.read(self.prom), now - self.env.mtime(self.prom))
                except OSError:
                    prom = ('', None)
            pat = re.escape(name) + (r'\{[^}]*' + re.escape(label) + r'[^}]*\}' if label else r'(?:\{\})?')
            m = re.search(r'^' + pat + r'\s+(-?[\d.]+)\s*$', prom[0], re.M)
            return float(m.group(1)) if m else None

        def page(controller):      # state age via the textfile: file age + the controller's own age line
            a = promval('lab_controller_state_age_seconds', f'controller="{controller}"')
            return None if a is None or prom[1] is None else prom[1] + a

        try:
            d = json.loads(self.env.read(self.md_state))
            res['shelf'] = (int(d['pct']), now - self.env.mtime(self.md_state), 'state')
        except (OSError, ValueError, KeyError, TypeError):
            v = promval('lab_md1200_fan_percent')
            res['shelf'] = (None if v is None else int(v), page('md1200-fan'), 'prom')
        try:
            s = self.env.read(self.fw_state)
            age = now - self.env.mtime(self.fw_state)
            m = re.search(r'\s(\d+)%', s)
            res['r720'] = (100 if 'auto' in s else (int(m.group(1)) if m else None), age, 'auto' if 'auto' in s else 'state')
        except OSError:
            v = promval('lab_r720_fan_percent')
            auto = promval('lab_r720_fan_auto')
            pct = 100 if auto == 1 else (None if v is None else int(v))
            res['r720'] = (pct, page('fan-watchdog'), 'auto' if auto == 1 else 'prom')
        return res

    def read_shelf(self):
        """-> ({'backplane': C, 'SIM': C, 'expander': C}, age s) from md1200-fan's state, or (None, age or None) when
        it is missing, unparsable or older than SHELF_MAX_AGE. Three quick tries: md1200-fan rewrites it every 10 s."""
        age = None
        for attempt in range(3):
            try:
                d = json.loads(self.env.read(self.md_state))
                try:
                    age = self.env.now() - time.mktime(time.strptime(d['time'], '%Y-%m-%d %H:%M:%S'))
                except (KeyError, TypeError, ValueError):
                    age = self.env.now() - self.env.mtime(self.md_state)
                vals = {k: float(d['temps'][k]) for k in SHELF_LIMITS}
                return (vals, age) if age <= SHELF_MAX_AGE else (None, age)
            except (OSError, ValueError, KeyError, TypeError):
                if attempt < 2:
                    self.env.sleep(0.5)
        return None, age

    def judge_shelf(self, vals, now):
        """Shelf enclosure stop lines -> list of stop reasons (2 readings at stop, 1 at abort; missing keeps counts)."""
        out = []
        if vals is None:
            blind = now - (self.shelf_fresh_t if self.shelf_fresh_t is not None else now)
            if blind >= SHELF_BLIND:
                out.append(f'shelf backplane/SIM/expander: no fresh md1200-fan state for {blind:.0f} s')
            return out
        self.shelf_fresh_t = now
        for k, (stop, abort) in SHELF_LIMITS.items():
            v = vals[k]
            self.shelf_over[k] = self.shelf_over[k] + 1 if v >= stop else 0
            if v >= abort:
                out.append(f'shelf {k} {v:g}C (abort line {abort}C, one read)')
            elif self.shelf_over[k] >= 2:
                out.append(f'shelf {k} {v:g}C (stop {stop}C, 2 reads in a row)')
            elif self.shelf_over[k] == 1:
                self.note(f'shelf {k} {v:g}C at its stop line {stop}C (1 read; stops on the next)')
        return out

    def have_fans(self):
        return any(self.env.exists(p) for p in (self.md_state, self.fw_state, self.prom))

    def check_fans(self):
        """-> (problems, {'shelf': pct, 'r720': pct}); a cap needs 2 bad reads in a row to stop. Levels are logged
        wherever the controllers' state exists (mementos), caps or not."""
        if not any(v is not None for v in self.caps.values()) and not self.fans_logged:
            return [], {}
        f = self.read_fans()
        probs, vals = [], {}
        for k, cap in self.caps.items():
            pct, age, src = f[k]
            vals[k] = '' if pct is None else ('auto' if src == 'auto' else pct)
            if cap is None:
                continue
            if pct is None or age is None or age > self.state_max_age:
                why = f'{k} fan state unreadable or stale (age {age if age is None else int(age)} s)'
            elif pct > cap:
                why = f'{k} fans {"in iDRAC auto" if src == "auto" else str(pct) + "%"} above the cap {cap:g}%'
            else:
                self.fan_bad[k] = 0
                continue
            self.fan_bad[k] += 1
            if self.fan_bad[k] >= 2:
                probs.append(f'{why} on {self.fan_bad[k]} reads in a row')
            else:
                self.note(f'{why} (1 read; stops on the next)')
        return probs, vals

    # ---- fio
    def job_text(self, mode, secs):
        # --readonly is a command-line option only (a job file rejects it and drops the job); it makes fio refuse any
        # write or trim for every job.
        opts = {'seq': 'rw=read\nbs=1M\niodepth=4', 'rand': 'rw=randread\nbs=64k\niodepth=16'}[mode]
        txt = f'[global]\ndirect=1\nioengine=libaio\n{opts}\ntime_based=1\nruntime={secs}\ngroup_reporting=0\n'
        for d in self.devs:
            if d['role'] == 'data':
                txt += f'[{d["name"]}]\nfilename={d["dev"]}\n'
        return txt

    def start_fio(self, mode, secs):
        if self.load_until != float('inf'):
            secs = max(1, min(secs, int(self.load_until - self.env.now())))   # fio itself stops at LOAD_UNTIL
        self.env.write(self.job, self.job_text(mode, secs), 'w')
        self.fio = self.env.popen(['fio', '--readonly', self.job])

    def stop_fio(self):
        """TERM to fio's whole process group, then KILL to the group whether or not the leader is still alive (its
        job processes can outlive it)."""
        if self.fio is not None:
            self.env.killgroup(self.fio, signal.SIGTERM)
            for _ in range(40):
                if self.fio.poll() is not None:
                    break
                self.env.sleep(0.5)
            self.env.killgroup(self.fio, signal.SIGKILL)
        self.fio = None

    def sectors(self):
        names = {d['name'] for d in self.devs if d['role'] == 'data'}
        tot = 0
        try:
            for line in self.env.read('/proc/diskstats').splitlines():
                f = line.split()
                if len(f) > 5 and f[2] in names:
                    tot += int(f[5])
        except OSError:
            pass
        return tot

    # ---- run
    def describe(self):
        for d in self.devs:
            b = self.base.get(d['dev'], {})
            h = ' '.join(f'{k}={v}' for k, v in b.items() if k not in ('phy', 'temp'))
            if 'phy' in b:
                h += ' phy=' + ','.join(f'{k}:{v}' for k, v in sorted(b['phy'].items()))
            self.note(f'device {d["name"]} {d["serial"]} {d["model"]} ({d["proto"]}, {d["cls"]}) '
                      f'{"LOADED" if d["role"] == "data" else "watched only"}, stop {d["stop"]:g}C, now '
                      f'{b.get("temp", "?")}C; {h or "no health fields"}'
                      + (f'; WATCH LIST: {d["watchnote"]}' if d['watchnote'] else ''))

    def columns(self):
        return (['epoch', 'time', 'phase', 'phase_min', 'running', 'mb_s', 'tmax', 'tmean', 'fan_shelf', 'fan_r720',
                 'shelf_backplane', 'shelf_sim', 'shelf_expander']
                + [f'{d["name"]}_{d["serial"] or "noserial"}' for d in self.devs])

    def sample(self, health):
        cur = {}
        for d in self.devs:
            cur[d['dev']] = self.read_smart(d, health)
        return cur

    def run(self):
        if self.bad_env:
            raise RuntimeError(f'environment values that do not parse: {", ".join(self.bad_env)}')
        self.discover()
        self.snapshot()
        fans = {}
        self.fans_logged = self.have_fans()
        if self.fans_logged or any(v is not None for v in self.caps.values()):
            f = self.read_fans()
            for k, cap in self.caps.items():
                pct, age, src = f[k]
                if cap is not None and (pct is None or age is None or age > self.state_max_age):
                    raise RuntimeError(f'fan cap {k} {cap:g}% set but its controller state is unreadable or stale '
                                       f'(level {pct}, age {age})')
            fans = {k: (f[k][0], None if f[k][1] is None else int(f[k][1]), f[k][2]) for k in f}
        shelf0 = None
        if self.shelf:
            shelf0, sage = self.read_shelf()
            if shelf0 is None:
                raise RuntimeError(f'shelf soak: {self.md_state} missing, unreadable or stale (age {sage}): the '
                                   'backplane/SIM/expander stop lines could not act')
            self.shelf_fresh_t = self.env.now()
        if self.selftest:
            if self.shelf:
                self.env.out(f'shelf enclosure now (md1200-fan state): {shelf0}; stop/abort {SHELF_LIMITS}')
            self.describe()
            miss = [d['name'] for d in self.devs if d['role'] == 'data' and 'temp' not in self.base.get(d['dev'], {})]
            self.env.out(f'fans now (level, state age s, source): {fans or "(no controller state on this host)"}; '
                         f'caps {self.caps}; PHY_JUMP {self.phy_jump:g}; health every {self.health_every:g} s; '
                         f'LOAD_UNTIL {self.load_until}' + (f'; NO TEMPERATURE at the start: {miss}' if miss else ''))
            self.env.out(f'fio job for phase 1 ({self.phases[0][0]}), run as fio --readonly <job>:\n'
                         + self.job_text(self.phases[0][0], int(self.phases[0][1] * 60)))
            bad = []
            for mode in sorted({m for m, _ in self.phases}):     # the host's own fio parses each job (no I/O)
                self.env.write(self.job, self.job_text(mode, 60), 'w')
                try:
                    rc, out = self.env.run(['fio', '--readonly', '--parse-only', self.job], timeout=30)
                finally:
                    self.env.remove(self.job)
                self.env.out(f'argv check {mode}: fio --readonly --parse-only rc {rc}')
                if rc != 0:
                    bad.append(f'{mode}: rc {rc} {out.strip()[-160:]}')
            if bad:
                self.env.out('ARGV CHECK FAILED: ' + '; '.join(bad))
                return 3
            return 0
        cols = self.columns()
        if not self.env.exists(self.csv):
            self.env.write(self.csv, ','.join(cols) + '\n', 'w')
        else:
            self.note('appending to an existing CSV; columns: ' + ','.join(cols))
        self.note(f'start {self.label}: pool {self.pool}, {sum(d["role"] == "data" for d in self.devs)} disks loaded, '
                  f'{sum(d["role"] == "watch" for d in self.devs)} watched, phases {self.phases_arg}, caps '
                  f'{ {k: v for k, v in self.caps.items() if v is not None} or "none"}, PHY_JUMP {self.phy_jump:g}')
        self.describe()
        last_health = self.env.now()
        rc = 0
        for mode, mins in self.phases:
            if self.env.now() > self.load_until:
                self.note(f'{mode}:{mins:g}: past LOAD_UNTIL, not started')
                break
            self.start_fio(mode, int(mins * 60))
            self.note(f'phase {mode}: {mins:g} min on {sum(d["role"] == "data" for d in self.devs)} disks')
            t0 = s0 = self.env.now()
            sec0 = self.sectors()
            while self.env.now() - t0 < mins * 60 + 5:
                self.env.sleep(TICK)
                health = self.env.now() - last_health >= self.health_every - 5
                cur = self.sample(health)
                probs, hnotes = [], []
                if health:
                    last_health = self.env.now()
                    probs, hnotes = self.check_health(cur)
                fprobs, fans = self.check_fans()
                svals = self.read_shelf()[0] if self.shelf else None
                sec1, s1 = self.sectors(), self.env.now()
                mbs = (sec1 - sec0) * 512 / 1e6 / max(1.0, s1 - s0)
                sec0, s0 = sec1, s1
                run = self.fio is not None and self.fio.poll() is None
                temps = [cur[d['dev']].get('temp') for d in self.devs]
                good = [t for d, t in zip(self.devs, temps) if t is not None and d['role'] == 'data']
                row = [int(s1), time.strftime('%T', time.localtime(s1)), mode, f'{(s1 - t0) / 60:.1f}', int(run),
                       f'{mbs:.0f}', max(good) if good else '', f'{sum(good) / len(good):.1f}' if good else '',
                       fans.get('shelf', ''), fans.get('r720', '')]
                row += ['' if svals is None else f'{svals[k]:g}' for k in SHELF_LIMITS]
                row += ['' if t is None else t for t in temps]
                self.env.write(self.csv, ','.join(map(str, row)) + '\n')
                for n in hnotes:
                    self.note(n)
                hot = []
                for d, t in zip(self.devs, temps):
                    k = d['dev']
                    asleep = d['role'] == 'watch' and cur[k].get('standby')   # an idle watched HDD may sleep
                    self.notemp[k] = 0 if t is not None or asleep else self.notemp.get(k, 0) + 1
                    if t is not None:      # a missing reading neither clears nor adds to the at-line count
                        self.overt[k] = self.overt.get(k, 0) + 1 if t >= d['stop'] else 0
                    if t is not None and t >= d['stop'] + ABORT_ABOVE:
                        hot.append(f'{d["name"]} {d["serial"]} {t}C (abort line {d["stop"] + ABORT_ABOVE:g}C, one read)')
                    elif self.overt.get(k, 0) >= 2:
                        hot.append(f'{d["name"]} {d["serial"]} {t}C (stop {d["stop"]:g}C, 2 reads in a row)')
                    elif self.overt.get(k, 0) == 1 and t is not None:
                        self.note(f'{d["name"]} {d["serial"]} {t}C at its stop line {d["stop"]:g}C (1 read; stops on the next)')
                    if self.notemp[k] >= 3:
                        hot.append(f'{d["name"]} {d["serial"]}: no temperature for 3 reads in a row')
                if self.shelf:
                    hot += self.judge_shelf(svals, s1)
                if hot:
                    self.stop_fio()
                    self.note(f'STOP: {mode}: temperature: {"; ".join(hot)}')
                    return self.finish(3)
                if probs:
                    self.stop_fio()
                    self.note(f'STOP: {mode}: SMART health: {"; ".join(probs)}')
                    return self.finish(4)
                if fprobs:
                    self.stop_fio()
                    self.note(f'STOP: {mode}: fan cap: {"; ".join(fprobs)}')
                    return self.finish(5)
                if self.env.now() > self.load_until:
                    self.stop_fio()
                    self.note(f'{mode}: LOAD_UNTIL passed: load off')
                    return self.finish(0)
                if not run:
                    rcf = self.fio.poll() if self.fio is not None else None
                    if s1 - t0 < mins * 60 - 90:
                        self.note(f'{mode}: fio ended early (rc {rcf}) after {(s1 - t0) / 60:.1f} of {mins:g} min')
                    break
            self.stop_fio()
        self.note('done')
        return self.finish(rc)

    def finish(self, rc):
        """Final SMART read against the start snapshot (logged, never changes rc), then clean up."""
        try:
            probs, notes = self.check_health(self.sample(True))
            self.note('final SMART check: ' + ('; '.join(probs + notes) if probs or notes else 'unchanged from the start'))
        except Exception as e:  # noqa: BLE001 (the soak is over; only the log line is lost)
            self.note(f'final SMART check failed: {type(e).__name__}')
        return rc

    def cleanup(self):
        self.stop_fio()
        self.env.remove(self.job)


def main(argv, env=None, env_vars=None):
    s = Soak(argv, env, env_vars)

    def on_term(*a):
        s.stop_fio()
        s.note('stopped (SIGTERM)')
        s.env.remove(s.job)
        sys.exit(0)

    if env is None:
        signal.signal(signal.SIGTERM, on_term)
    try:
        return s.run()
    except RuntimeError as e:
        s.note(f'STOP: refused: {e}')
        return 2
    finally:
        s.cleanup()


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
