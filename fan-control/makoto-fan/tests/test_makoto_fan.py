#!/usr/bin/env python3
# Offline tests for makoto-fan: the controller's Control.step() drives a thermal model of makoto (no hardware touched).
# Model (fitted to the 2026-10-19/20 fixed-fan runs, see PLANT below): the CPU die sits P x R_JH over its heatsink;
# the heatsink settles toward the case air + P x R_HS(FAN1 rpm) with time constant TAU_HS; the case air settles toward
# room + total heat / airflow(FAN1, FAN4) with TAU_AIR; board sensors follow the case air with their own offsets and
# time constants. Duty -> rpm from the 10-19 map. Scenarios check peak temperatures against the limits, how often the
# fans change, and that a few seconds of load (Whisper, Kokoro) do not rev them.
# usage: python3 tests/test_makoto_fan.py [-v]
import importlib.machinery, importlib.util, math, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
loader = importlib.machinery.SourceFileLoader('makoto_fan', os.path.join(HERE, '..', 'makoto-fan'))
spec = importlib.util.spec_from_loader('makoto_fan', loader)
mf = importlib.util.module_from_spec(spec)
loader.exec_module(mf)
VERBOSE = '-v' in sys.argv

# duty % -> rpm (10-19 map; between points linear)
RPM1 = [(1, 1800), (3, 1900), (5, 2100), (10, 2300), (12, 2500), (20, 3000), (25, 3300), (30, 3600), (40, 4100),
        (100, 7600)]   # 100% not measured yet (BMC auto reached 7,000)
RPM4 = [(1, 1500), (8, 1500), (12, 1600), (15, 1700), (20, 1900), (25, 2100), (30, 2300), (35, 2500), (40, 2700),
        (100, 4900)]

PLANT = {
    # case air over the room = (q_base + CPU package W) / (g0 + g1*rpm1/1000 + g4*rpm4/1000), time constant tau_air.
    # Fitted 2026-10-19 to the idle phases (room 23C): auto 3,600/2,300 rpm -> Card Side 46, floor 1,800/1,500 -> 52+,
    # FAN1 3,600 + FAN4 1,500 -> 51, FAN1 1,700 + FAN4 1,900 -> 51, FAN4 1,700 -> 53-54 (still rising).
    'room': 23.0, 'q_base': 27.0, 'g0': 0.35, 'g1': 0.08, 'g4': 0.41, 'tau_air': 900.0,
    # CPU: heatsink over (case air + cpu_off) by P * (r0 + r1 / (rpm1/1000) + r4 / (rpm4/1000)), time constant tau_hs;
    # die over heatsink by P * r_jh at once. Fitted 2026-10-20 00:1x: 22 W at FAN1 3,500 -> 84C, 25 W at 7,000 -> 74C,
    # 21 W at 1,700 -> 90C and still rising within a minute (FAN1 is the heatsink fan: tau ~30-60 s under load).
    'cpu_off': 3.0, 'r0': 0.30, 'r1': 1.96, 'r4': 0.0, 'tau_hs': 60.0, 'r_jh': 0.5,
    'idle_w': 3.5,
    'sens': {                  # sensor: (offset over case air, gain on package W, time constant s)
        'card': (4.0, 0.0, 300.0), 'ddr': (6.0, 0.05, 600.0), 'mb': (-1.0, 0.03, 600.0),
        'nvme': (4.5, 0.03, 600.0), 'ssd': (-12.0, 0.0, 900.0),
    },
}


def interp(pts, x):
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


class Plant:
    def __init__(self, p=PLANT, room=None):
        self.p = p
        self.room = p['room'] if room is None else room
        r1, r4 = 3.6, 2.3                                   # start settled at the BMC's idle speeds
        self.air = self.room + (p['q_base'] + p['idle_w']) / (p['g0'] + p['g1'] * r1 + p['g4'] * r4)
        self.hs = self.air + p['cpu_off'] + p['idle_w'] * (p['r0'] + p['r1'] / r1 + p['r4'] / r4)
        self.s = {k: self.air + v[0] for k, v in p['sens'].items()}

    def step(self, dt, watts, f1, f4):
        p = self.p
        r1, r4 = interp(RPM1, f1) / 1000, interp(RPM4, f4) / 1000
        air_eq = self.room + (p['q_base'] + watts) / (p['g0'] + p['g1'] * r1 + p['g4'] * r4)
        self.air += (air_eq - self.air) * (1 - math.exp(-dt / p['tau_air']))
        hs_eq = self.air + p['cpu_off'] + watts * (p['r0'] + p['r1'] / r1 + p['r4'] / r4)
        self.hs += (hs_eq - self.hs) * (1 - math.exp(-dt / p['tau_hs']))
        for k, (off, g, tau) in p['sens'].items():
            eq = self.air + off + g * watts
            self.s[k] += (eq - self.s[k]) * (1 - math.exp(-dt / tau))
        return self.hs + watts * p['r_jh'], dict(self.s)


def run(power, seconds, room=None, bmc_ok=lambda t: True, start=None):
    """power(t) -> package W. Returns a trace of (t, cpu, temps, f1, f4)."""
    plant, ctl = Plant(room=room), mf.Control()
    f1 = f4 = 30
    trace = []
    t = 0.0
    while t < seconds:
        cpu, temps = plant.step(mf.EVERY, power(t), f1, f4)
        temps = {k: round(v) for k, v in temps.items()}    # the BMC and drives report whole degrees
        n1, n4, why, _ = ctl.step(mf.EVERY, round(cpu), temps, bmc_ok(t))
        if abs(n1 - f1) >= mf.DEADBAND or n1 in (mf.FLOOR1, 100) and n1 != f1:
            f1 = n1
        if abs(n4 - f4) >= mf.DEADBAND or n4 in (mf.FLOOR4, 100) and n4 != f4:
            f4 = n4
        trace.append((t, cpu, temps, f1, f4))
        t += mf.EVERY
    return trace


def summary(trace, skip=0):
    tr = [x for x in trace if x[0] >= skip]
    peak = {'cpu': max(x[1] for x in tr)}
    for k in tr[0][2]:
        peak[k] = max(x[2][k] for x in tr)
    changes1 = sum(1 for a, b in zip(tr, tr[1:]) if a[3] != b[3])
    changes4 = sum(1 for a, b in zip(tr, tr[1:]) if a[4] != b[4])
    hours = (tr[-1][0] - tr[0][0]) / 3600
    return peak, changes1 / hours, changes4 / hours, max(x[3] for x in tr), max(x[4] for x in tr), tr[-1]


# peaks allowed in transients; SETTLED: the mean over the last hour of a steady scenario
LIMITS = {'cpu': 85, 'ddr': 74, 'mb': 55, 'card': 55, 'nvme': 70, 'ssd': 60}
SETTLED = {'card': 51.0}
FAILS = []


def check(name, cond, msg):
    if not cond:
        FAILS.append(f'{name}: {msg}')
    if VERBOSE or not cond:
        print(('ok  ' if cond else 'FAIL'), name, msg)


def whisper(t):          # 3 s at 25 W every 60 s on top of idle
    return 25.0 if t % 60 < 3 else PLANT['idle_w']


SCEN = {
    'idle': (lambda t: PLANT['idle_w'], 3 * 3600),
    'whisper bursts': (whisper, 2 * 3600),
    'light 12 W': (lambda t: 12.0, 2 * 3600),
    'medium 25 W': (lambda t: 25.0, 2 * 3600),
    'full 40 W from idle': (lambda t: 40.0 if t >= 600 else PLANT['idle_w'], 2 * 3600),
    'full 40 W then idle': (lambda t: 40.0 if t < 3600 else PLANT['idle_w'], 3 * 3600),
}

if __name__ == '__main__':
    for room in (22, 26):
        for name, (pw, secs) in SCEN.items():
            tr = run(pw, secs, room=room)
            peak, ch1, ch4, max1, max4, last = summary(tr, skip=1800 if secs > 3600 else 0)
            label = f'{name} room {room}'
            print(f"{label:28s} peak cpu {peak['cpu']:5.1f} ddr {peak['ddr']} mb {peak['mb']} card {peak['card']} "
                  f"nvme {peak['nvme']} | changes/h FAN1 {ch1:5.1f} FAN4 {ch4:5.1f} | max {max1}/{max4}% | "
                  f"end {last[3]}/{last[4]}%")
            for k, lim in LIMITS.items():
                check(label, peak[k] <= lim + (10 if k == 'cpu' and 'full' in name else 0), f'{k} peak {peak[k]:.1f} <= {lim}')
            if 'then' not in name:
                last = [x for x in tr if x[0] >= secs - 3600]
                for k, lim in SETTLED.items():
                    m = sum(x[2][k] for x in last) / len(last)
                    maxed = all(x[4] >= 100 for x in last)     # FAN4 already flat out: nothing left to give
                    check(label, m <= lim or maxed, f'{k} settled mean {m:.1f} <= {lim}' + (' (FAN4 at 100%)' if maxed else ''))
        tr = run(whisper, 3600, room=room)
        check(f'whisper room {room}', max(x[3] for x in tr[900:]) - min(x[3] for x in tr[900:]) <= 6,
              'Whisper-like bursts move FAN1 by at most 6%')
    tr = run(lambda t: PLANT['idle_w'], 1800, bmc_ok=lambda t: t < 600)
    check('bmc lost', tr[-1][4] >= mf.STALE_FAN4, f'FAN4 >= {mf.STALE_FAN4}% once the BMC readings are stale')
    print('\n' + ('all passed' if not FAILS else f'{len(FAILS)} FAILED'))
    sys.exit(1 if FAILS else 0)
