#!/usr/bin/env python3
# disk-soak (2026-10-13): read-only drive heat soak for the final rack run.
# usage (root): disk-soak.py <label> <pool> <phases> [limit C]
#   phases: comma list of mode:minutes, mode seq (1 MiB sequential reads, queue depth 4, like a scrub) or rand
#   (64 KiB random reads across the whole disk, queue depth 16: the most seeking, the most heat).
# Every data disk of <pool> (from zpool status -P; log and cache devices excluded) gets its own fio job on the raw
# disk with --readonly (fio refuses any write or trim) and O_DIRECT. Nothing is written anywhere and no file system is
# involved, so the pool's data cannot change; ZFS only sees slower I/O while it runs.
# Every 60 s: each disk's temperature (smartctl) and the MB/s read over the minute (/proc/diskstats) go to
# /var/tmp/disk-soak-<label>.csv. Stops (fio killed, exit 3) when any disk reaches the limit (default 52C), and starts
# no new phase after LOAD_UNTIL (epoch, env). SIGTERM (systemctl stop) kills fio too.
import os, re, signal, subprocess, sys, time

LABEL, POOL, PHASES = sys.argv[1], sys.argv[2], sys.argv[3]
LIMIT = int(sys.argv[4]) if len(sys.argv) > 4 else 52
CSV = f'/var/tmp/disk-soak-{LABEL}.csv'
LOAD_UNTIL = float(os.environ.get('LOAD_UNTIL', 'inf'))
JOB = f'/run/disk-soak-{LABEL}.fio'
fio = None


def note(m):
    with open(CSV, 'a') as f:
        f.write(f'# {int(time.time())} {time.strftime("%F %T %Z")} {m}\n')
    print(m, flush=True)


def stop_fio():
    global fio
    if fio and fio.poll() is None:
        fio.terminate()
        try:
            fio.wait(20)
        except subprocess.TimeoutExpired:
            fio.kill()
    fio = None


def on_term(*a):
    stop_fio()
    note('stopped (SIGTERM)')
    sys.exit(0)


signal.signal(signal.SIGTERM, on_term)


def data_disks(pool):
    out = subprocess.run(['zpool', 'status', '-P', pool], capture_output=True, text=True, check=True).stdout
    disks, section = [], 'data'
    for line in out.splitlines():
        s = line.strip()
        if s.startswith(('logs', 'cache', 'spares', 'special', 'dedup')):
            section = s.split()[0]
        m = re.match(r'(/dev/\S+)\s+ONLINE', s)
        if m and section == 'data':
            dev = os.path.realpath(re.sub(r'-part\d+$', '', m.group(1)))
            dev = re.sub(r'(\d+)$', '', dev) if re.match(r'/dev/sd[a-z]+\d+$', dev) else dev
            disks.append(dev)
    return disks


def temp(dev):
    o = subprocess.run(['smartctl', '-n', 'standby', '-A', dev], capture_output=True, text=True).stdout
    m = re.search(r'Current Drive Temperature:\s+(\d+)', o) or \
        re.search(r'^194 Temperature_Celsius(?:\s+\S+){7}\s+(\d+)', o, re.M)
    return int(m.group(1)) if m else None


def sectors(devs):
    names = {os.path.basename(d) for d in devs}
    tot = 0
    for line in open('/proc/diskstats'):
        f = line.split()
        if f[2] in names:
            tot += int(f[5])
    return tot


def start_fio(devs, mode, secs):
    global fio
    opts = {'seq': 'rw=read\nbs=1M\niodepth=4', 'rand': 'rw=randread\nbs=64k\niodepth=16'}[mode]
    with open(JOB, 'w') as f:
        f.write(f'[global]\ndirect=1\nioengine=libaio\n{opts}\ntime_based=1\nruntime={secs}\n'
                f'group_reporting=0\n')
        for d in devs:
            f.write(f'[{os.path.basename(d)}]\nfilename={d}\n')
    # --readonly is a command-line option only (a job file rejects it and drops the job); it makes fio refuse any write
    # or trim for every job. fio's own messages go to the journal.
    fio = subprocess.Popen(['fio', '--readonly', JOB], stdout=subprocess.DEVNULL)


devs = data_disks(POOL)
cols = ['epoch', 'time', 'phase', 'phase_min', 'running', 'mb_s', 'tmax', 'tmean', 'temps']
if not os.path.exists(CSV):
    with open(CSV, 'w') as f:
        f.write(','.join(cols) + '\n')
note(f'start {LABEL}: pool {POOL}, {len(devs)} disks {" ".join(os.path.basename(d) for d in devs)}, phases {PHASES}, '
     f'limit {LIMIT}C')
if not devs:
    note('no data disks found; stopping')
    sys.exit(2)
try:
    for ph in PHASES.split(','):
        mode, mins = ph.split(':')
        mins = float(mins)
        if time.time() > LOAD_UNTIL:
            note(f'{ph}: past LOAD_UNTIL, not started')
            break
        start_fio(devs, mode, int(mins * 60))
        note(f'phase {mode}: {mins} min on {len(devs)} disks')
        t0 = s0 = time.time()
        sec0 = sectors(devs)
        while time.time() - t0 < mins * 60 + 5:
            time.sleep(60)
            ts = [temp(d) for d in devs]
            good = [t for t in ts if t is not None]
            sec1, s1 = sectors(devs), time.time()
            mbs = (sec1 - sec0) * 512 / 1e6 / (s1 - s0)
            sec0, s0 = sec1, s1
            run = fio is not None and fio.poll() is None
            row = [int(s1), time.strftime('%T'), mode, f'{(s1 - t0) / 60:.1f}', int(run), f'{mbs:.0f}',
                   max(good) if good else '', f'{sum(good) / len(good):.1f}' if good else '',
                   ';'.join('' if t is None else str(t) for t in ts)]
            with open(CSV, 'a') as f:
                f.write(','.join(map(str, row)) + '\n')
            if good and max(good) >= LIMIT:
                stop_fio()
                note(f'{mode}: a disk reached {max(good)}C (limit {LIMIT}C): stopped')
                sys.exit(3)
            if not run:
                break
        stop_fio()
    note('done')
finally:
    stop_fio()
    try:
        os.remove(JOB)
    except OSError:
        pass
