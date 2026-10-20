#!/usr/bin/env python3
# fanstep: run a schedule of fixed fan duties (and optional CPU load) on makoto with temperature stops, then hand the
# fans back to the BMC. Root. Schedule lines: LABEL F1 F4 SECONDS [WORKERS]   (F1/F4: 0 = BMC auto, 1-100 = duty %)
# A line '@gate F1 F4 MAXWAIT' holds F1/F4 with no load until mirror-voice has logged no wake or request ('wake (' /
# 'heard ') for 10 min (Rohit not using the assistant), checking every 60 s; past MAXWAIT s the run ends.
# 'LABEL ctl ctl SECONDS [WORKERS]' (a whole schedule, not mixed with fixed duties): makoto-fan holds the fans and this
# run only adds load and watches, with no IPMI calls of its own (BMC values from makoto-fan's state file); it ends if
# makoto-fan stops or its state goes stale, and leaves the fans to makoto-fan at the end.
# usage: fanstep.py SCHEDULE OUT.csv [--stall note|restore] [--load-off C] [--abort C] [--card-max C] [--check]
import argparse, glob, json, os, signal, subprocess, sys, time

ap = argparse.ArgumentParser()
ap.add_argument('schedule'); ap.add_argument('out')
ap.add_argument('--stall', default='note', choices=['note', 'restore'])
ap.add_argument('--load-off', type=float, default=84)   # coretemp package: drop the load (2 readings in a row)
ap.add_argument('--abort', type=float, default=88)      # coretemp package: BMC auto and stop
ap.add_argument('--card-max', type=float, default=55)   # BMC Card Side Temp: BMC auto and stop
ap.add_argument('--check', action='store_true')         # print the schedule and exit, touching nothing
a = ap.parse_args()
LIMITS = {'DDR4_A Temp': 75, 'DDR4_B Temp': 75, 'MB Temp': 58, 'Card Side Temp': a.card_max}   # BMC: auto and stop
NVME_MAX = 70
PHASE = '/run/makoto-fantest.phase'
CTL_STATE = '/run/makoto-fan.state'
SENS = ['FAN1', 'FAN4', 'CPU1 Temp', 'DDR4_A Temp', 'DDR4_B Temp', 'MB Temp', 'Card Side Temp']
CORETEMP = next(d for d in glob.glob('/sys/class/hwmon/hwmon*') if open(d + '/name').read().strip() == 'coretemp')
NVME = next((d for d in glob.glob('/sys/class/hwmon/hwmon*') if open(d + '/name').read().strip() == 'nvme'), None)
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))


def log(msg):
    print(time.strftime('%H:%M:%S'), msg, flush=True)


def fans(f1, f4):
    subprocess.run(['ipmitool', 'raw', '0x3a', '0x01', f'0x{f1:02x}', '0x00', '0x00', f'0x{f4:02x}',
                    '0x00', '0x00', '0x00', '0x00'], check=True, capture_output=True, timeout=10)
    got = subprocess.run(['ipmitool', 'raw', '0x3a', '0x02'], capture_output=True, text=True, timeout=10).stdout.split()
    if len(got) != 8 or int(got[0], 16) != f1 or int(got[3], 16) != f4:
        raise RuntimeError(f'fan setting did not hold: {got}')


def bmc():
    r = subprocess.run(['ipmitool', 'sensor', 'reading', *SENS], capture_output=True, text=True, timeout=15)
    v = {}
    for line in r.stdout.splitlines():
        k, _, x = line.partition('|')
        try:
            v[k.strip()] = float(x)
        except ValueError:
            v[k.strip()] = None
    return v


def voice_busy():
    r = subprocess.run(['journalctl', '_SYSTEMD_USER_UNIT=mirror-voice.service', '--since', '-10min', '--no-pager',
                        '-o', 'cat'], capture_output=True, text=True, timeout=60)
    return sum(('wake (' in x or 'heard ' in x) for x in r.stdout.splitlines())


def temp(p):
    return int(open(p).read()) / 1000


def ctl_state():
    # makoto-fan's state while it runs and has written it in the last 15 s, else None
    if subprocess.run(['pgrep', '-f', '^/usr/bin/python3 .*makoto-fan$'], capture_output=True).returncode:
        return None
    try:
        d = json.load(open(CTL_STATE))
    except (OSError, ValueError):
        return None
    return d if time.time() - d.get('t', 0) <= 15 else None


steps = []
for line in open(a.schedule):
    f = line.split('#')[0].split()
    if f:
        ctl = f[1] == 'ctl'
        assert ctl == (f[2] == 'ctl'), f
        steps.append((f[0], -1 if ctl else int(f[1]), -1 if ctl else int(f[2]), float(f[3]),
                      int(f[4]) if len(f) > 4 else 0))
CTL = all(s[1] == -1 for s in steps)
for s in steps:
    assert (s[1] == s[2] == -1 if CTL else 0 <= s[1] <= 100 and 0 <= s[2] <= 100) and 0 <= s[4] <= 8, s
if a.check:
    for s in steps:
        print(*s)
    print(f'{len(steps)} steps, {sum(s[3] for s in steps) / 60:.0f} min', 'with makoto-fan in control' if CTL else '')
    raise SystemExit(0)

new = not os.path.exists(a.out)
out = open(a.out, 'a', buffering=1)
if new:
    out.write('epoch,label,f1,f4,workers,pkg,nvme,fan1,fan4,cpu_bmc,ddra,ddrb,mb,card,event\n')
load = None
try:
    for label, f1, f4, secs, workers in steps:
        if not CTL:
            fans(f1, f4)
        if label == '@gate':
            if load:
                load.terminate(); load.wait(); load = None
            open(PHASE, 'w').write('gate\n')
            waited = 0
            while (n := voice_busy()):
                if waited >= secs:
                    log(f'assistant still in use after {waited} s: ending the run')
                    raise SystemExit(0)
                log(f'gate: {n} assistant events in the last 10 min, waiting')
                time.sleep(60); waited += 60
            log(f'gate open after {waited} s')
            continue
        waited = 0
        while CTL and not ctl_state():
            if waited >= 120:
                log('makoto-fan is not running: ending the run')
                raise SystemExit(1)
            time.sleep(5); waited += 5
        open(PHASE, 'w').write(f'{label}\n')
        if load:
            load.terminate(); load.wait(); load = None
        if workers:
            load = subprocess.Popen(['nice', '-n', '19', 'stress-ng', '--cpu', str(workers), '--cpu-method', 'matrixprod',
                                     '--timeout', f'{int(secs) + 5}s', '--quiet'])
        fl = 'makoto-fan in control' if CTL else f'FAN1 {f1 or "auto"} FAN4 {f4 or "auto"}'
        log(f'step {label}: {fl} for {secs:g} s, {workers} workers')
        end, hot, stall, checked = time.time() + secs, 0, {}, time.time()
        while time.time() < end:
            if CTL:
                d = ctl_state()
                v = {} if d is None else {'FAN1': d.get('rpm1'), 'FAN4': d.get('rpm4'), 'DDR4_A Temp': d.get('ddr'),
                                          'DDR4_B Temp': d.get('ddr'), 'MB Temp': d.get('mb'),
                                          'Card Side Temp': d.get('card')}
            else:
                if time.time() - checked >= 10:     # something else (a unit's ExecStopPost, the BMC) may have reset it
                    checked = time.time()
                    got = subprocess.run(['ipmitool', 'raw', '0x3a', '0x02'], capture_output=True, text=True,
                                         timeout=10).stdout.split()
                    if len(got) == 8 and (int(got[0], 16), int(got[3], 16)) != (f1, f4):
                        log(f'fan setting was {got[0]}/{got[3]}, setting {f1}/{f4} again')
                        fans(f1, f4)
                v = bmc()
            pkg = temp(f'{CORETEMP}/temp1_input')
            nv = temp(f'{NVME}/temp1_input') if NVME else 0
            ev = ''
            hot = hot + 1 if pkg >= a.load_off else 0
            if hot >= 2 and load:
                load.terminate(); load.wait(); load = None
                ev = f'load off at {pkg:g}C'
            over = [k for k, lim in LIMITS.items() if (v.get(k) or 0) >= lim]
            if pkg >= a.abort or over or nv >= NVME_MAX:
                ev = f'abort: pkg {pkg:g} nvme {nv:g} {over}'
            if CTL and d is None:
                ev = 'abort: makoto-fan stopped or its state is stale'
            for fan, duty in (('FAN1', f1), ('FAN4', f4)):
                if not CTL and duty and (v.get(fan) or 0) < 200:
                    stall.setdefault(fan, time.time())
                    if time.time() - stall[fan] >= 6:
                        ev += f' {fan} stalled at {duty}%'
                else:
                    stall.pop(fan, None)
            d1, d4 = (d.get('fan1'), d.get('fan4')) if CTL and d else (f1, f4)
            out.write(f'{time.time():.0f},{label},{d1},{d4},{workers},{pkg:g},{nv:g},' +
                      ','.join('' if v.get(k) is None else f'{v[k]:g}' for k in SENS) + f',{ev.strip()}\n')
            if ev:
                log(ev.strip())
            if ev.startswith('abort') or ('stalled' in ev and a.stall == 'restore'):
                raise SystemExit(1)
            time.sleep(2 if CTL else 1)
finally:
    if load:
        load.terminate(); load.wait()
    if CTL and ctl_state():
        log('makoto-fan still holds the fans')
    else:
        subprocess.run(['ipmitool', 'raw', '0x3a', '0x01'] + ['0x00'] * 8, capture_output=True, timeout=10)
        log('fans back to BMC auto')
    try:
        os.remove(PHASE)
    except OSError:
        pass
