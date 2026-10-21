#!/usr/bin/env python3
# lr-cut (2026-10-20): living-room circuit estimate with its own load cut, the unmetered twin of pdu-cut.sh. Runs on
# ryuji as root, one per test window:
#   systemd-run --unit=lr-cut-<x> -p RuntimeMaxSec=<s> --setenv=UNITS='<unit globs>' python3 /var/tmp/lr-cut.py
# Every 15 s it estimates the strip's draw:
#   ryuji wall W = its ACPI power meter (PSU input) as node_exporter already exports it to Prometheus:
#     node_hwmon_power_average_watt{instance="10.0.0.9",chip="lnxsybus:00_acpi000d:00"} (~125 W idle, 538 W max in
#     3 days). lr-cut never reads that meter itself (on this board it may go through the BMC; only the existing
#     node_exporter reader is allowed), or 125 + 1.37 x package W of both sockets from local RAPL energy_uj deltas
#     (the 10-16 calibration's conservative fit, over the DCMI wall by 0-26 W from idle to 44 workers; VR W and RAPL
#     package W agree within 5 W there): the higher of the two when both exist (the meter read 64 W once on 10-19, a
#     glitch), RAPL alone when the meter series is older than 60 s.
#   + the other boxes on the strip from Prometheus (futaba): CPU busy fraction over 1 min (1 - idle rate of
#     node_cpu_seconds_total) mapped linearly idle -> full wall W: tinynas 60->150, makoto 45->90, futaba 15->45,
#     morgana 8->65, yusuke 6->65. A box with no fresh series counts at its full W.
#   + a fixed 120 W for the closed appliance on the strip.
#   amps = W / 114 (a sagging 120 V line, so the estimate errs high).
# Cut: amps over LIMIT (env, default 11.0 = 12 A continuous on the 15 A strip less ~1 A for estimate error) on 2
# fresh samples in a row (a blind or failed sample in between keeps the count), or no fresh estimate (ryuji's power
# and Prometheus both answered) for 60 s: `systemctl stop` on every active service matching UNITS (env,
# space-separated globs; a bare name gets .service). UNITS refuses to start (exit 2) when empty, when a glob does not
# start with a test-unit prefix (ryuji-floor-, lab-load-, lab-soak-, scrub-quiet-soak-, mementos-steps-,
# sojiro-floor-) or when it matches a production unit (fan-watchdog, md1200-fan, ryuji-fan-guard, makoto-*,
# lab-bmc-ip, ...); every listed unit is re-checked against all three before it is stopped. (With no pattern,
# systemctl list-units lists every active service: that is how pdu-cut.sh would stop sshd and the fan controllers.) It keeps running and cuts again if a
# matching unit comes back while still over or blind; END (env epoch) ends it cleanly (exit 0) so RuntimeMaxSec need
# not mark it failed. Log: LOG (env, default /var/tmp/lr-cut.csv), one row per sample, '#' lines for events ("STOP:"
# on a cut). SIGTERM: exit 0. --selftest: one estimate and the units it would stop; stops nothing, writes nothing.
import fnmatch, json, os, re, signal, subprocess, sys, time, urllib.parse, urllib.request

PROM = os.environ.get('PROM', 'http://10.0.0.3:9090')
# instance -> (name, idle W, full W)
OTHERS = {'10.0.0.5': ('tinynas', 60, 150), '10.0.0.6': ('makoto', 45, 90), '10.0.0.3': ('futaba', 15, 45),
          '10.0.0.7': ('morgana', 8, 65), '10.0.0.4': ('yusuke', 6, 65)}
APPLIANCE_W = 120
VOLTS = 114.0
WALL0, WALL_K = 125.0, 1.37    # fallback: wall = 125 + 1.37 x RAPL package W
RYUJI_METER = 'node_hwmon_power_average_watt{instance="10.0.0.9",chip="lnxsybus:00_acpi000d:00"}'
EVERY, STALE_S = 15, 60
RAPL = ['/sys/class/powercap/intel-rapl:0', '/sys/class/powercap/intel-rapl:1']
# UNITS may only name the run's test units: every glob must start with one of these, match none of PRODUCTION, and every
# unit it lists is re-checked against both before `systemctl stop`.
TEST_PREFIXES = ('ryuji-floor-', 'lab-load-', 'lab-soak-', 'scrub-quiet-soak-', 'mementos-steps-', 'sojiro-floor-')
PRODUCTION = ('fan-watchdog.service', 'md1200-fan.service', 'ryuji-fan-guard.service', 'makoto-fan.service',
              'makoto-fan-test.service', 'makoto-fanstep-day1.service', 'makoto-miclevels.service', 'lab-bmc-ip.service',
              'lab-thermal-textfile.service', 'lab-sync.service', 'ssh.service', 'sshd.service',
              'prometheus-node-exporter.service', 'systemd-journald.service', 'systemd-logind.service')


class Env:
    def now(self):
        return time.time()

    def sleep(self, s):
        time.sleep(s)

    def read(self, path):
        with open(path) as f:
            return f.read()

    def write(self, path, text, mode='a'):
        with open(path, mode) as f:
            f.write(text)

    def exists(self, path):
        return os.path.exists(path)

    def prom(self, q, timeout=8):
        url = f'{PROM}/api/v1/query?query=' + urllib.parse.quote(q)
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.load(r)['data']['result']

    def run(self, args, timeout=60):
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
            return r.returncode, r.stdout + r.stderr
        except (OSError, subprocess.TimeoutExpired) as e:
            return 255, f'{type(e).__name__}: {e}'

    def out(self, text):
        print(text, flush=True)


def busy_query():
    rx = '|'.join(i.replace('.', '[.]') for i in OTHERS)   # no backslashes: PromQL strings reject a bare \\.
    return f'1 - avg by (instance) (rate(node_cpu_seconds_total{{mode="idle",instance=~"{rx}"}}[1m]))'


class Cut:
    def __init__(self, argv, env=None, env_vars=None):
        self.env = env or Env()
        ev = os.environ if env_vars is None else env_vars
        self.selftest = '--selftest' in argv
        self.limit = float(ev.get('LIMIT', '') or 11.0)
        self.log = ev.get('LOG', '') or '/var/tmp/lr-cut.csv'
        self.units = [u if re.search(r'[*?\[]', u) or u.endswith('.service') else u + '.service'   # bare name -> .service
                      for u in ev.get('UNITS', '').split()]
        self.end = float(ev.get('END', '') or 'inf')
        self.rapl = ev.get('RAPL_ZONES', '').split() or RAPL
        self.last_e = None          # (t, [uj per zone])
        self.last_fresh = None      # time of the last fresh estimate
        self.t_start = None
        self.over = 0
        self.cols = (['epoch', 'time', 'ryuji_pkg_w', 'ryuji_rapl_wall_w', 'ryuji_meter_w', 'ryuji_w', 'ryuji_src']
                     + [OTHERS[i][0] + '_w' for i in OTHERS]
                     + ['appliance_w', 'total_w', 'amps', 'over', 'blind_s', 'action', 'note'])

    def note(self, m):
        t = self.env.now()
        if not self.selftest:
            self.log_write(f'# {int(t)} {time.strftime("%F %T %Z", time.localtime(t))} {m}\n')
        self.env.out(m)

    def log_write(self, text, mode='a'):
        try:
            self.env.write(self.log, text, mode)
        except OSError as e:         # a full or broken /var/tmp must not end the guard: the journal still gets it
            self.env.out(f'log write failed ({type(e).__name__}): {text.strip()}')

    # ---- inputs
    def read_energy(self):
        vals = []
        for z in self.rapl:
            vals.append((int(self.env.read(f'{z}/energy_uj').strip()), int(self.env.read(f'{z}/max_energy_range_uj').strip())))
        return vals

    def ryuji_pkg_w(self):
        """Package W of both sockets since the last call, or None (first call or a failed read)."""
        t = self.env.now()
        try:
            e = self.read_energy()
        except (OSError, ValueError):
            self.last_e = None
            return None
        prev, self.last_e = self.last_e, (t, e)
        if prev is None or t - prev[0] <= 0:
            return None
        tot = 0.0
        for (u1, rng), (u0, _) in zip(e, prev[1]):
            d = u1 - u0
            if d < 0:           # counter wrapped
                d += rng
            tot += d
        return tot / 1e6 / (t - prev[0])

    def meter_w(self):
        """ryuji's ACPI meter from Prometheus if its sample is under 60 s old, else None."""
        try:
            res = self.env.prom(f'{RYUJI_METER} and on() (time() - timestamp({RYUJI_METER}) < {STALE_S})')
            return float(res[0]['value'][1]) if res else None
        except Exception:   # noqa: BLE001
            return None

    def others_w(self):
        """{name: (W, busy or None)} or None if Prometheus did not answer."""
        try:
            res = self.env.prom(busy_query())
        except Exception:   # noqa: BLE001 (any failure = no fresh data)
            return None
        busy = {}
        for x in res:
            try:
                busy[x['metric']['instance']] = min(1.0, max(0.0, float(x['value'][1])))
            except (KeyError, ValueError, TypeError, IndexError):
                pass
        out = {}
        for inst, (name, idle, full) in OTHERS.items():
            b = busy.get(inst)
            out[name] = (full if b is None else idle + b * (full - idle), b)
        return out

    # ---- action
    def bad_units(self):
        """Why UNITS is unsafe to act on, or '' if it is fine."""
        if not self.units:
            return 'UNITS is empty'
        out = [g for g in self.units if not g.startswith(TEST_PREFIXES)]
        if out:
            return f'UNITS globs outside the test-unit prefixes {TEST_PREFIXES}: {out}'
        hit = [f'{g} -> {p}' for g in self.units for p in PRODUCTION if fnmatch.fnmatchcase(p, g)]
        return f'UNITS matches production units: {hit}' if hit else ''

    def matching_units(self):
        if self.bad_units():
            return []
        rc, out = self.env.run(['systemctl', 'list-units', '--type=service', '--state=active', '--no-legend', '--plain',
                                '--'] + self.units)
        names = [l.split()[0] for l in out.splitlines() if l.strip()]
        # belt and braces: only names that end in .service and match one of our globs
        return [n for n in names if n.endswith('.service') and n.startswith(TEST_PREFIXES) and n not in PRODUCTION
                and any(fnmatch.fnmatchcase(n, g) or fnmatch.fnmatchcase(n, g + '.service') for g in self.units)]

    def cut(self, why):
        units = self.matching_units()
        if not units:
            return 'cut-idle'      # nothing of ours running: no log spam while over or blind
        self.note(f'STOP: lr-cut: {why}: stopping {" ".join(units)}')
        for u in units:
            rc, out = self.env.run(['systemctl', 'stop', u], timeout=120)
            self.note(f'stopped {u} (rc {rc})' if rc == 0 else f'stop {u} failed (rc {rc}): {out.strip()[-200:]}')
        return 'CUT'

    def sample(self):
        t = self.env.now()
        pkg = self.ryuji_pkg_w()
        rapl_wall = None if pkg is None else WALL0 + WALL_K * pkg
        meter = self.meter_w()
        oth = self.others_w()
        ryuji, src = None, ''
        if meter is not None and (rapl_wall is None or meter >= rapl_wall):
            ryuji, src = meter, 'meter'
        elif rapl_wall is not None:      # the higher of the two when both exist (a lagging or glitching meter reads low)
            ryuji, src = rapl_wall, 'rapl' if meter is None else 'rapl(>meter)'
        fresh = ryuji is not None and oth is not None
        total = amps = None
        if fresh:
            total = ryuji + sum(w for w, _ in oth.values()) + APPLIANCE_W
            amps = total / VOLTS
            self.last_fresh = t
        blind = t - (self.last_fresh if self.last_fresh is not None else self.t_start)
        action, note = '', ''
        if fresh:
            self.over = self.over + 1 if amps > self.limit else 0
            if self.over >= 2:
                action = self.cut(f'estimate {amps:.2f} A > {self.limit:g} A on {self.over} samples')
            elif self.over:
                action = 'over'
            missing = [n for n, (w, b) in oth.items() if b is None]
            if missing:
                note = 'no fresh CPU data (counted at full W): ' + ' '.join(missing)
        else:                      # blind: the over count stays as it was (only a fresh sample under LIMIT clears it)
            note = ('no ryuji power (meter stale and no RAPL delta)' if ryuji is None else '') + \
                   (' no Prometheus answer' if oth is None else '')
            if blind >= STALE_S:
                action = self.cut(f'no fresh estimate for {blind:.0f} s ({note.strip()})')
            else:
                action = 'blind'
        f0 = lambda v: '' if v is None else f'{v:.0f}'
        row = [int(t), time.strftime('%T', time.localtime(t)), f0(pkg), f0(rapl_wall), f0(meter), f0(ryuji), src]
        row += ['' if oth is None else f'{oth[OTHERS[i][0]][0]:.0f}' for i in OTHERS]
        row += [APPLIANCE_W, f0(total), '' if amps is None else f'{amps:.2f}', self.over, f'{blind:.0f}', action,
                note.strip().replace(',', ';')]
        return row

    def run(self):
        self.t_start = self.env.now()
        if self.selftest:          # never cuts: one estimate by hand and the units it would stop
            self.ryuji_pkg_w()
            self.env.sleep(2)
            pkg = self.ryuji_pkg_w()
            meter = self.meter_w()
            oth = self.others_w()
            rw = None if pkg is None else WALL0 + WALL_K * pkg
            self.env.out(f'ryuji: meter {meter} W (Prometheus, fresh < {STALE_S} s); RAPL package '
                         f'{None if pkg is None else round(pkg, 1)} W -> fallback wall {None if rw is None else round(rw)} W')
            self.env.out(f'others (W, busy): {oth}')
            ry = max(x for x in (meter, rw) if x is not None) if (meter is not None or rw is not None) else None
            if ry is not None and oth is not None:
                tot = ry + sum(w for w, _ in oth.values()) + APPLIANCE_W
                self.env.out(f'total {tot:.0f} W = {tot / VOLTS:.2f} A (limit {self.limit:g} A)')
            self.env.out(f'UNITS {self.units}{" REFUSED: " + self.bad_units() if self.bad_units() else ""}; '
                         f'active now: {self.matching_units()}')
            return 0
        if self.bad_units():
            self.note(f'STOP: lr-cut refused: {self.bad_units()} (it would stop every active service)')
            return 2
        if not self.env.exists(self.log):
            self.log_write(','.join(self.cols) + '\n', 'w')
        self.note(f'lr-cut start: limit {self.limit:g} A, units {" ".join(self.units) or "(none)"}, every {EVERY} s, '
                  f'blind cut after {STALE_S} s')
        self.ryuji_pkg_w()
        while True:
            self.env.sleep(EVERY)
            if self.env.now() >= self.end:
                self.note('lr-cut end (END reached)')
                return 0
            try:
                row = self.sample()
            except Exception as e:   # noqa: BLE001 (never die silently: an error counts as blind)
                t = self.env.now()
                blind = t - (self.last_fresh if self.last_fresh is not None else self.t_start)
                self.note(f'sample failed: {type(e).__name__}: {e}')
                action = self.cut(f'no fresh estimate for {blind:.0f} s (errors)') if blind >= STALE_S else 'error'
                row = [int(t), time.strftime('%T', time.localtime(t))] + [''] * (len(self.cols) - 6) + \
                      [self.over, f'{blind:.0f}', action, type(e).__name__]
            self.log_write(','.join(map(str, row)) + '\n')


def main(argv, env=None, env_vars=None):
    c = Cut(argv, env, env_vars)

    def on_term(*a):
        c.note('lr-cut stopped (SIGTERM)')
        sys.exit(0)

    if env is None:
        signal.signal(signal.SIGTERM, on_term)
    return c.run()


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
