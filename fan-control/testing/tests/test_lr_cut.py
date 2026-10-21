#!/usr/bin/env python3
# Fake-clock dry runs of lr-cut.py: fake RAPL counters (package power set per scenario, with a counter wrap), fake
# Prometheus answers (busy per instance, missing series, outages) and a fake systemctl that records stops.
# usage: python3 -I tests/test_lr_cut.py [-v]
import importlib.util, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
exec(open(os.path.join(HERE, 'guard.py')).read())   # any real subprocess/network call now raises
spec = importlib.util.spec_from_file_location('lr_cut', os.path.join(HERE, '..', 'lr-cut.py'))
lc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lc)
VERBOSE = '-v' in sys.argv
T0 = 1_792_516_200.0   # 2026-10-20 13:10 EDT
RANGE = 262143328850


class FakeEnv(lc.Env):
    def __init__(self, pkg_w=100.0, busy=None, events=None, units=('ryuji-floor-t4-1020.service',), start_uj=0):
        self.t = T0
        self.pkg_w = pkg_w                     # per package
        self.uj = [start_uj, start_uj]
        self.busy = dict(busy or {i: 0.05 for i in lc.OTHERS})
        self.prom_up = True
        self.rapl_ok = True
        self.meter = 'auto'                    # 'auto' = mapping of pkg_w (2 sockets), None = stale, or a number
        self.events = sorted((events or {}).items())
        self.active = list(units)
        self.extra_listed = []                 # names a buggy systemctl would also print
        self.files, self.calls, self.outs = {}, [], []

    def now(self):
        return self.t

    def sleep(self, s):
        end = self.t + s
        while self.events and T0 + self.events[0][0] <= end:
            sec, fn = self.events.pop(0)
            self._adv(T0 + sec - self.t)
            fn(self)
        self._adv(end - self.t)

    def _adv(self, dt):
        if dt <= 0:
            return
        for i in range(2):
            self.uj[i] = (self.uj[i] + int(self.pkg_w * dt * 1e6)) % RANGE
        self.t += dt

    def read(self, path):
        if not self.rapl_ok:
            raise OSError(path)
        z = 0 if 'intel-rapl:0' in path else 1
        if path.endswith('max_energy_range_uj'):
            return f'{RANGE}\n'
        return f'{self.uj[z]}\n'

    def write(self, path, text, mode='a'):
        self.files[path] = (self.files.get(path, '') if mode == 'a' else '') + text

    def exists(self, path):
        return path in self.files

    def prom(self, q, timeout=8):
        self.calls.append(('prom', q))
        assert '\\' not in q, f'backslash in a PromQL string: {q}'
        if not self.prom_up:
            raise OSError('connection refused')
        if 'node_hwmon_power_average_watt' in q:
            assert 'lnxsybus:00_acpi000d:00' in q and '10.0.0.9' in q and 'timestamp' in q, q
            if self.meter is None:
                return []
            w = 130 + 1.4 * 2 * self.pkg_w if self.meter == 'auto' else self.meter
            return [{'metric': {}, 'value': [self.t, str(w)]}]
        assert 'node_cpu_seconds_total' in q and 'mode="idle"' in q, q
        return [{'metric': {'instance': i}, 'value': [self.t, str(b)]} for i, b in self.busy.items() if b is not None]

    def run(self, args, timeout=60):
        self.calls.append(('run', list(args)))
        if args[:2] == ['systemctl', 'list-units']:
            assert '--' in args and len(args) > args.index('--') + 1, f'list-units without patterns: {args}'
            return 0, ''.join(f'{u} loaded active running x\n' for u in self.active + self.extra_listed)
        if args[:2] == ['systemctl', 'stop']:
            if args[2] in self.active:
                self.active.remove(args[2])
            return 0, ''
        raise AssertionError(f'unexpected command {args}')

    def out(self, text):
        self.outs.append(text)
        if VERBOSE:
            print('   |', text)


RESULTS = []


def case(name, ok, detail=''):
    RESULTS.append((name, ok))
    print(f'{"PASS" if ok else "FAIL"}  {name}' + (f'  ({detail})' if detail and (VERBOSE or not ok) else ''))


def stops(e):
    return [c[1][2] for c in e.calls if c[0] == 'run' and c[1][:2] == ['systemctl', 'stop']]


def rows(e, log='/var/tmp/lr.csv'):
    lines = [l.split(',') for l in e.files.get(log, '').splitlines() if l and not l.startswith('#')]
    if not lines:
        return []
    hdr = lines[0]
    assert all(len(l) == len(hdr) for l in lines), 'ragged CSV row'
    return [dict(zip(hdr, l)) for l in lines[1:]]


BASE = {'LOG': '/var/tmp/lr.csv', 'UNITS': 'ryuji-floor-t4* ryuji-floor-disk-t4*', 'LIMIT': '11.0'}

# 1. normal: 2 x 50 W packages (100 W total -> 261 W wall), others near idle: ~5 A, no action, a row every 15 s
e = FakeEnv(pkg_w=50)
rc = lc.main([], e, dict(BASE, END=str(T0 + 600)))
r = rows(e)
amps = [float(x['amps']) for x in r if x['amps']]
case('normal: exit 0 at END, ~39 rows, ryuji from the meter (270 W, over RAPL 262), no cut', rc == 0 and 38 <= len(r) <= 41
     and r[0]['ryuji_w'] == '270' and r[0]['ryuji_src'] == 'meter' and r[0]['ryuji_rapl_wall_w'] == '262'
     and not stops(e) and all(a < 6 for a in amps), f'{len(r)} rows, first {r[0] if r else None}')
case('estimate = meter + others + 120, / 114', abs(amps[0] - (270 + sum(i + 0.05 * (f - i) for _, i, f in lc.OTHERS.values()) + 120) / 114) < 0.02,
     amps[0])

# 1b. meter stale -> RAPL fallback (125 + 1.37 x 100 = 262 W); meter glitch low (64 W at 262) -> RAPL
e = FakeEnv(pkg_w=50)
e.meter = None
rc = lc.main([], e, dict(BASE, END=str(T0 + 60)))
r = rows(e)
case('meter stale: RAPL fallback 262 W, still a fresh estimate', r and r[0]['ryuji_w'] == '262' and r[0]['ryuji_src'] == 'rapl'
     and r[0]['amps'] and not stops(e), r[:1])
e = FakeEnv(pkg_w=50)
e.meter = 64
rc = lc.main([], e, dict(BASE, END=str(T0 + 60)))
r = rows(e)
case('meter glitch (64 W while RAPL says 262): RAPL used', r and r[0]['ryuji_w'] == '262' and r[0]['ryuji_src'] == 'rapl(>meter)', r[:1])
e = FakeEnv(pkg_w=50)
e.meter = 250
rc = lc.main([], e, dict(BASE, END=str(T0 + 60)))
r = rows(e)
case('review M7: meter 250 under RAPL 262: the higher (RAPL) is used', r and r[0]['ryuji_w'] == '262', r[:1])

# 2. over the limit on 2 samples: stops only the matching unit, keeps running, logs once
def heavy(env):
    env.pkg_w = 230                         # 460 W package -> meter 764 W
    env.busy = {i: 1.0 for i in lc.OTHERS}  # others at full: 415 W; + 120 -> 1299 W = 11.4 A
e = FakeEnv(pkg_w=50, events={120: heavy}, units=['ryuji-floor-t4-1020.service', 'ryuji-floor-disk-t4-1020.service'])
rc = lc.main([], e, dict(BASE, END=str(T0 + 600)))
log = e.files['/var/tmp/lr.csv']
case('over 11 A on 2 samples: both ryuji test units stopped, then quiet, runs to END',
     rc == 0 and sorted(stops(e)) == ['ryuji-floor-disk-t4-1020.service', 'ryuji-floor-t4-1020.service']
     and log.count('STOP: lr-cut') == 1 and 'cut-idle' in log, stops(e))
r = rows(e)
first_cut = [x for x in r if x['action'] == 'CUT']
case('the cut row is the 2nd over sample (over=2)', first_cut and first_cut[0]['over'] == '2', first_cut[:1])

# 3. one sample over, then back under: no cut
def spike(env):
    env.pkg_w = 230
    env.busy = {i: 1.0 for i in lc.OTHERS}
def calm(env):
    env.pkg_w = 50
e = FakeEnv(pkg_w=50, events={118: spike, 125: calm})
rc = lc.main([], e, dict(BASE, END=str(T0 + 300)))
case('one sample over: no cut', not stops(e) and any(x['action'] == 'over' for x in rows(e)), [x['action'] for x in rows(e)])

# 4. Prometheus down: 45 s blind = no cut; 60 s = cut
def down(env):
    env.prom_up = False
def up(env):
    env.prom_up = True
e = FakeEnv(pkg_w=50, events={60: down, 105: up})
rc = lc.main([], e, dict(BASE, END=str(T0 + 300)))
case('Prometheus down 45 s: blind rows, no cut', not stops(e) and any(x['action'] == 'blind' for x in rows(e)))
e = FakeEnv(pkg_w=50, events={60: down})
rc = lc.main([], e, dict(BASE, END=str(T0 + 300)))
blind_cut = [x for x in rows(e) if x['action'] == 'CUT']
case('Prometheus down: cut once blind for 60 s', stops(e) == ['ryuji-floor-t4-1020.service'] and blind_cut
     and int(blind_cut[0]['blind_s']) >= 60 and 'no fresh estimate' in e.files['/var/tmp/lr.csv'], blind_cut[:1])

# 5. RAPL unreadable but the meter fresh: no cut; both gone: blind -> cut
def rapl_off(env):
    env.rapl_ok = False
e = FakeEnv(pkg_w=50, events={60: rapl_off})
rc = lc.main([], e, dict(BASE, END=str(T0 + 300)))
case('RAPL unreadable, meter fresh: no cut', not stops(e))
def both_off(env):
    env.rapl_ok = False
    env.meter = None
e = FakeEnv(pkg_w=50, events={60: both_off})
rc = lc.main([], e, dict(BASE, END=str(T0 + 300)))
case('RAPL unreadable and meter stale for 60 s: cut', stops(e) == ['ryuji-floor-t4-1020.service'])

# 6. RAPL counter wrap: no negative or huge power
e = FakeEnv(pkg_w=150, start_uj=RANGE - 2_000_000_000)
rc = lc.main([], e, dict(BASE, END=str(T0 + 120)))
pk = [float(x['ryuji_pkg_w']) for x in rows(e) if x['ryuji_pkg_w']]
case('RAPL counter wrap handled (package W steady at 300)', pk and all(abs(p - 300) < 1 for p in pk), pk)

# 7. a box with no fresh series counts at its full W
e = FakeEnv(pkg_w=50, busy={i: (None if i == '10.0.0.5' else 0.1) for i in lc.OTHERS})
rc = lc.main([], e, dict(BASE, END=str(T0 + 60)))
r = rows(e)
case('tinynas missing from Prometheus: counted at 150 W, noted', r and r[0]['tinynas_w'] == '150' and 'tinynas' in r[0]['note'], r[0] if r else '')

# 8. UNITS guards: empty or catch-all refuses before any systemctl call; a stray listed name is never stopped
for units, label in (('', 'empty'), ('*', 'star'), ('r*', 'two-char glob'), ('[a-z]*', 'class glob'),
                     ('ryuji*', 'review M5 ryuji*'), ('ryuji-f*', 'review M5 ryuji-f*'), ('syst*', 'review M5 syst*'),
                     ('fan-watchdog*', 'production fan-watchdog'), ('makoto-*', 'production makoto-*'),
                     ('ryuji-floor-t4* lab-bmc-ip', 'production lab-bmc-ip'), ('lab-load-*  md1200-fan.service', 'md1200-fan'),
                     ('ryuji-floor-[!x]*  ryuji-fan-guard*', 'ryuji-fan-guard')):
    e = FakeEnv(pkg_w=50)
    rc = lc.main([], e, dict(BASE, UNITS=units, END=str(T0 + 60)))
    case(f'UNITS {label!r}: refused (exit 2), no systemctl call', rc == 2 and not [c for c in e.calls if c[0] == 'run']
         and 'refused' in e.files.get('/var/tmp/lr.csv', ''))
e = FakeEnv(pkg_w=230, busy={i: 1.0 for i in lc.OTHERS})
e.extra_listed = ['sshd.service', 'ryuji-fan-guard.service']
rc = lc.main([], e, dict(BASE, END=str(T0 + 120)))
case('names systemctl lists that do not match UNITS are never stopped', stops(e) == ['ryuji-floor-t4-1020.service'], stops(e))

# 9. selftest: an estimate, the units it would stop, no stop, no file
e = FakeEnv(pkg_w=50)
rc = lc.main(['--selftest'], e, dict(BASE))
case('selftest: exit 0, no stop, no log file', rc == 0 and not stops(e) and not e.files
     and any('total' in o for o in e.outs) and any('active now' in o for o in e.outs), e.outs)

# 10. an unexpected error inside a sample counts as blind: cut after 60 s, never a silent death
def boom(env):
    env.explode = True
class Boom(FakeEnv):
    def prom(self, q, timeout=8):
        if getattr(self, 'explode', False):
            raise TypeError('unexpected')
        return super().prom(q, timeout)
orig = lc.Cut.others_w
def bad_others(self):
    if getattr(self.env, 'explode', False):
        raise ZeroDivisionError('bug')
    return orig(self)
lc.Cut.others_w = bad_others
e = FakeEnv(pkg_w=50, events={60: boom})
rc = lc.main([], e, dict(BASE, END=str(T0 + 300)))
lc.Cut.others_w = orig
log = e.files['/var/tmp/lr.csv']
case('errors inside samples: logged, then a cut once blind 60 s, still runs to END', rc == 0 and 'sample failed: ZeroDivisionError' in log
     and stops(e) == ['ryuji-floor-t4-1020.service'] and all(len(r) == len(rows(e)[0]) for r in rows(e)), stops(e))

# 11. review B1: Prometheus failing every other query while over the limit: still cut (old code reset the count)
class Alternating(FakeEnv):
    def prom(self, q, timeout=8):
        if 'node_cpu_seconds_total' in q:
            self.flip = not getattr(self, 'flip', False)
            if self.flip:
                raise OSError('timeout')
        return super().prom(q, timeout)
e = Alternating(pkg_w=230, busy={i: 1.0 for i in lc.OTHERS})
rc = lc.main([], e, dict(BASE, END=str(T0 + 600)))
case('review B1: over 11 A with every other sample blind: cut (count kept across blind samples)',
     stops(e) == ['ryuji-floor-t4-1020.service'], [x['action'] for x in rows(e)][:8])

# 12. review M6: a bare unit name is matched as NAME.service
e = FakeEnv(pkg_w=230, busy={i: 1.0 for i in lc.OTHERS})
rc = lc.main([], e, dict(BASE, UNITS='ryuji-floor-t4-1020', END=str(T0 + 120)))
case('review M6: bare name ryuji-floor-t4-1020 stops ryuji-floor-t4-1020.service', stops(e) == ['ryuji-floor-t4-1020.service'], stops(e))

# 13. review M8: the log cannot be written: lr-cut keeps running and still cuts
class NoDisk(FakeEnv):
    def write(self, path, text, mode='a'):
        raise OSError(28, 'No space left on device')
e = NoDisk(pkg_w=230, busy={i: 1.0 for i in lc.OTHERS})
try:
    rc = lc.main([], e, dict(BASE, END=str(T0 + 120)))
    ok = rc == 0 and stops(e) == ['ryuji-floor-t4-1020.service'] and any('log write failed' in o for o in e.outs)
except OSError as ex:
    ok = False
case('review M8: /var/tmp full: no crash, still cuts, events go to the journal', ok)

# 14. a listed unit outside the test prefixes is never stopped even if a glob matched it
e = FakeEnv(pkg_w=230, busy={i: 1.0 for i in lc.OTHERS})
e.extra_listed = ['ryuji-floor-t4-evil.socket', 'ryuji-fan-guard.service']
rc = lc.main([], e, dict(BASE, END=str(T0 + 120)))
case('only .service units with a test prefix are stopped', stops(e) == ['ryuji-floor-t4-1020.service'], stops(e))

bad = [n for n, ok in RESULTS if not ok]
print(f'\n{len(RESULTS) - len(bad)}/{len(RESULTS)} passed' + (f'; FAILED: {bad}' if bad else ''))
sys.exit(1 if bad else 0)
