#!/usr/bin/env python3
# labmon: log this host's sensors as JSON lines, and optionally run a stepped CPU load plan with
# safety limits. It changes nothing except the stress-ng load it starts and stops itself.
#   labmon.py [--plan W:P:MIN,W:P:MIN,...] [--start-after MIN] [--limit 'REGEX<=VALUE' ...] [--tag NAME]
# W = stress-ng cpu workers, P = per-worker load %, MIN = minutes per step.
# A limit applies to every sensor key matching REGEX (hwmon, ipmi, disk, rapl); if any reading
# reaches its limit the load stops at once, the plan is abandoned, and logging carries on.
import argparse, glob, json, os, re, signal, subprocess, sys, time

ap = argparse.ArgumentParser()
ap.add_argument('--plan', default='')
ap.add_argument('--start-after', type=float, default=0)
ap.add_argument('--limit', action='append', default=[])
ap.add_argument('--tag', default='labmon')
ap.add_argument('--interval', type=int, default=30)
ap.add_argument('--hours', type=float, default=18)
args = ap.parse_args()
OUT = f'/var/tmp/{args.tag}.jsonl'
SMART_EVERY = 300

def sh(*a, timeout=20):
    try:
        return subprocess.run(a, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ''

def hwmon():
    d = {}
    for h in sorted(glob.glob('/sys/class/hwmon/hwmon*')):
        try:
            name = open(h + '/name').read().strip()
        except OSError:
            continue
        for f in glob.glob(h + '/temp*_input') + glob.glob(h + '/fan*_input') + glob.glob(h + '/pwm[0-9]'):
            base = os.path.basename(f)
            lab = f.replace('_input', '_label')
            try:
                label = open(lab).read().strip() if os.path.exists(lab) else base.replace('_input', '')
                v = int(open(f).read())
            except (OSError, ValueError):
                continue
            d[f'{os.path.basename(h)}:{name}/{label}'] = round(v / 1000, 1) if base.startswith('temp') else v
    return d

def ipmi():
    d = {}
    if not os.path.exists('/dev/ipmi0'):
        return d
    for kind in ('Temperature', 'Fan'):
        seen = {}
        for line in sh('ipmitool', 'sdr', 'type', kind).splitlines():
            f = [x.strip() for x in line.split('|')]
            if len(f) < 5:
                continue
            m = re.match(r'(-?[\d.]+)\s', f[4] + ' ')
            if not m:
                continue
            n = seen.get(f[0], 0)
            seen[f[0]] = n + 1
            d[f'ipmi:{f[0]}' + (f'#{n}' if n else '')] = float(m.group(1))
    m = re.search(r'Instantaneous power reading:\s+(\d+)', sh('ipmitool', 'dcmi', 'power', 'reading'))
    if m:
        d['ipmi:power_w'] = int(m.group(1))
    return d

_rapl_last = {}
def rapl():
    d, now = {}, time.time()
    for z in glob.glob('/sys/class/powercap/intel-rapl:*'):
        try:
            name = open(z + '/name').read().strip()
            e = int(open(z + '/energy_uj').read())
            rng = int(open(z + '/max_energy_range_uj').read())
        except (OSError, ValueError):
            continue
        key = f'rapl:{os.path.basename(z)}:{name}'
        if key in _rapl_last:
            e0, t0 = _rapl_last[key]
            de = e - e0 if e >= e0 else e + rng - e0
            if now > t0:
                d[key + '_w'] = round(de / 1e6 / (now - t0), 1)
        _rapl_last[key] = (e, now)
    return d

_last_stat = {}
def activity():
    # CPU busy % and disk MB moved since the last sample (inputs for the power estimates)
    d = {}
    f = open('/proc/stat').readline().split()[1:]
    vals = [int(x) for x in f]
    idle, total = vals[3] + vals[4], sum(vals[:8])
    if 'cpu' in _last_stat:
        i0, t0 = _last_stat['cpu']
        if total > t0:
            d['cpu_busy_pct'] = round(100 * (1 - (idle - i0) / (total - t0)), 1)
    _last_stat['cpu'] = (idle, total)
    io = 0
    for line in open('/proc/diskstats'):
        x = line.split()
        if re.fullmatch(r'sd[a-z]+|nvme\d+n\d+', x[2]):
            io += (int(x[5]) + int(x[9])) * 512
    if 'io' in _last_stat:
        d['disk_io_mb'] = round((io - _last_stat['io']) / 1e6, 1)
    _last_stat['io'] = io
    return d

def disks():
    d = {}
    for line in sh('lsblk', '-dno', 'NAME,TYPE').splitlines():
        name, typ = (line.split() + [''])[:2]
        if typ != 'disk' or name.startswith(('zd', 'loop', 'sr')):
            continue
        out = sh('smartctl', '-n', 'standby', '-A', f'/dev/{name}')
        m = (re.search(r'Current Drive Temperature:\s+(\d+)', out)
             or re.search(r'^\s*19[04] \S+\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+(\d+)', out, re.M)
             or re.search(r'^Temperature:\s+(\d+) Celsius', out, re.M))
        if m:
            d[f'disk:{name}'] = int(m.group(1))
    return d

limits = []
for spec in args.limit:
    rx, val = spec.rsplit('<=', 1)
    limits.append((re.compile(rx), float(val)))
plan = [tuple(float(x) for x in s.split(':')) for s in args.plan.split(',') if s]

stress, step_i, step_end, plan_note = None, -1, 0, ''
def stop_stress():
    global stress
    if stress and stress.poll() is None:
        stress.terminate()
        try:
            stress.wait(10)
        except subprocess.TimeoutExpired:
            stress.kill()
    stress = None

signal.signal(signal.SIGTERM, lambda *a: (stop_stress(), sys.exit(0)))
out = open(OUT, 'a', buffering=1)
t_start, last_smart, last_disks = time.time(), 0, {}
rapl(); activity()
try:
    while time.time() - t_start < args.hours * 3600:
        now = time.time()
        # advance the load plan
        if plan and step_i < len(plan) and now - t_start >= args.start_after * 60 and now >= step_end:
            stop_stress()
            step_i += 1
            if step_i < len(plan):
                w, p, mins = plan[step_i]
                step_end = now + mins * 60
                stress = subprocess.Popen(['nice', '-n', '19', 'stress-ng', '--cpu', str(int(w)), '--cpu-load', str(int(p)),
                                           '--timeout', f'{int(mins * 60) + 30}s', '--quiet'],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                plan_note = f'step {step_i + 1}/{len(plan)}: {int(w)} workers x {int(p)}%'
            else:
                plan_note = 'plan done'
        rec = {'t': round(now), 'ts': time.strftime('%T'), 'load': plan_note if stress else ''}
        rec.update(hwmon()); rec.update(ipmi()); rec.update(rapl()); rec.update(activity())
        if now - last_smart >= SMART_EVERY:
            last_disks, last_smart = disks(), now
            rec.update(last_disks)
        # safety limits (disk temps use the latest SMART read)
        if stress:
            vals = {**last_disks, **rec}
            hit = [f'{k}={v}>={lim}' for rx, lim in limits for k, v in vals.items()
                   if isinstance(v, (int, float)) and rx.search(k) and v >= lim]
            if hit:
                stop_stress()
                step_i = len(plan)
                plan_note = 'aborted: ' + '; '.join(hit[:4])
                rec['note'] = plan_note
        out.write(json.dumps(rec) + '\n')
        time.sleep(max(1, args.interval - (time.time() - now)))
finally:
    stop_stress()
