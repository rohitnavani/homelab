# Closed-loop harness for ryuji-fan-guard (v2, 2026-10-06; v2.3 2026-10-10; v2.4/v2.5 2026-10-13): fake clock + a ryuji
# model. SIO Temp 1 and the hottest CPU settle (tau 3.5 min / 1 min) toward values that depend on the guard level, the
# load (busy threads) and the room. usage: python3 tests/test_ryuji_fan_guard.py ryuji-fan-guard
# v2.4: the model is for the 2x Xeon E5-2696 v4 fitted 2026-10-12 (44 cores / 88 threads, 150 W PL1 each). Idle and 4
# threads come from the 10-12 evening holds (room 24-25C, ryuji out of the rack), 2, 11, 22 and 44 workers from the
# 10-13 profile (room 24C), all shifted to a 27C room; -40 and 127 under load are estimates. Package power (RAPL, both
# CPUs) by load from the same runs (v2.5's trigger). Other loads interpolate linearly.
import math, sys, types
SRC = sys.argv[1]
src = open(SRC).read().replace("if __name__ == '__main__':\n    main()", '')
clock = [1_000_000.0]; T0 = clock[0]
# equilibria at a 27C room: {offset: {busy threads: value}}
SIO = {-80: {0: 75.0, 2: 76.0, 4: 69.0, 22: 54.0, 44: 42.0}, -60: {0: 74.5, 2: 76.0, 4: 58.0, 22: 50.5, 44: 41.0},
       -40: {0: 74.5, 4: 51.0, 22: 48.0, 44: 40.0}, -16: {0: 71.5, 4: 49.0, 22: 45.0, 44: 39.0},
       0: {0: 59.5, 4: 47.0, 22: 44.0, 44: 39.0}, 127: {0: 45.0, 4: 42.0, 22: 40.0, 44: 37.0}}
CPU = {-80: {0: 45, 2: 63, 4: 67, 22: 69, 33: 73, 44: 77}, -60: {0: 44, 2: 58, 4: 64, 22: 67, 33: 72, 44: 75},
       -40: {0: 44, 4: 59, 22: 66, 44: 74}, -16: {0: 43, 4: 58, 22: 62, 44: 72},
       0: {0: 41, 4: 56, 22: 62, 44: 72}, 127: {0: 40, 4: 55, 22: 61, 44: 71}}
PKG = {0: 18, 2: 90, 4: 110, 11: 148, 22: 188, 33: 245, 44: 296}   # W, both packages (PL1 150 W each from ~30 workers)
SIO_TAU = {-80: 600, -60: 600, -40: 600}   # SIO1 rises slowly with the system fans at their floor; ~210 s elsewhere
def at(table, lvl, load):
    pts = sorted(table[lvl].items())
    for (l0, v0), (l1, v1) in zip(pts, pts[1:]):
        if load <= l1:
            return v0 + (v1 - v0) * (min(max(load, l0), l1) - l0) / (l1 - l0)
    return pts[-1][1]
plant = {}
def reset(room, sio, cpu):
    plant.update(room=room, sio=sio, cpu=cpu, t=clock[0], load=0, cpu_extra=0.0, sio_force=None, cpu_force=None,
                 dead=False, cpu_max=cpu, bmc_down=0, pkg_force=None)
state = {'off': -80}
def advance():
    dt = clock[0] - plant['t']; plant['t'] = clock[0]
    lvl = state['off'] if state['off'] in SIO else -80
    s_inf = at(SIO, lvl, plant['load']) + plant['room'] - 27
    c_inf = at(CPU, lvl, plant['load']) + plant['cpu_extra'] + (plant['room'] - 27)
    tau = SIO_TAU.get(lvl, 210) if s_inf > plant['sio'] else 210
    plant['sio'] = s_inf + (plant['sio'] - s_inf) * math.exp(-dt / tau)
    plant['cpu'] = c_inf + (plant['cpu'] - c_inf) * math.exp(-dt / 60)
    plant['cpu_max'] = max(plant['cpu_max'], plant['cpu'])
def temps():
    advance()
    if plant['dead']:
        return None
    sio = plant['sio_force'] if plant['sio_force'] is not None else plant['sio']
    cpu = plant['cpu_force'] if plant['cpu_force'] is not None else plant['cpu']
    return {'sio': round(sio), 'cpu': round(cpu), 'vr': 60, 'dimm': 50}
offsets, logs, events = [], [], []
class Stop(Exception): pass
END = [0]
def sleep(s):
    clock[0] += s
    while events and clock[0] - T0 >= events[0][0]:
        events.pop(0)[1]()
    if clock[0] - T0 > END[0]: raise Stop()
def fake_bmc(action, offset=None):
    advance()
    if plant['bmc_down'] and clock[0] - T0 < plant['bmc_down']:
        raise OSError(113, 'No route to host')
    if action == 'set':
        state['off'] = offset; offsets.append((round((clock[0] - T0) / 60), offset))
    return state['off']
def run(label, end_min, room=27, start=-80, evs=(), bmc_down_s=0):
    offsets.clear(); logs.clear(); clock[0] = T0; END[0] = end_min * 60; state['off'] = start
    lvl0 = start if start in SIO else -80
    reset(room, at(SIO, lvl0, 0) + room - 27, at(CPU, lvl0, 0) + room - 27)
    plant['bmc_down'] = bmc_down_s
    events[:] = sorted((m * 60, f) for m, f in evs)
    g = {'__name__': 'sim'}
    exec(src, g)
    g['bmc'] = fake_bmc; g['temps'] = temps; g['STATE'] = '/dev/null'
    g['busy_threads'] = lambda: 0.05 + plant['load']   # the guard's /proc/stat reading
    g['pkg_watts'] = lambda: (None if plant.get('pkg_force') == -1 else plant['pkg_force'] if plant.get('pkg_force') is not None
                              else round(at({'p': PKG}, 'p', plant['load']), 1))
    g['time'] = types.SimpleNamespace(time=lambda: clock[0], sleep=sleep, strftime=lambda *a: 'T')
    g['log'] = lambda m: logs.append((round((clock[0] - T0) / 60), m))
    try: g['main']()
    except Stop: pass
    print(f'## {label}\n   offset changes (min, offset): {offsets}   [SIO1 end {plant["sio"]:.1f}, CPU max {plant["cpu_max"]:.1f}]')
    return offsets
def L(n): return lambda: plant.update(load=n)
ok = True
def expect(c, m):
    global ok; print('   ', 'PASS' if c else 'FAIL', m); ok &= bool(c)
vals = lambda o: [v for _, v in o]
def P(w): return lambda: plant.update(pkg_force=w)
o = run('1 idle, 27C room, 4 h', 240); expect(o == [], 'stays at -80 (SIO1 ~75 is under 79)')
o = run('2 4 busy threads for 60 min at 30 min, 27C room', 180, evs=[(30, L(4)), (90, L(0))])
expect(o[:1] and o[0][1] == -60 and 30 <= o[0][0] <= 33, f'-60 within 3 min of the load ({o[:1]})')
expect(vals(o) == [-60, -80] and o[-1][0] >= 100, f'back to -80 >= 10 idle min after, never -16/Performance ({o})')
o = run('3 full load (44 workers, 296 W) for 60 min, 24C room', 160, room=24, evs=[(30, L(44)), (90, L(0))])
expect(o == [], f'v2.5: stays at -80 (past the PSU band; the BMC drives the fans; CPU ~74C) ({o})')
expect(plant['cpu_max'] < 78, f'hottest CPU under CPU_UP ({plant["cpu_max"]:.1f})')
o = run('4 hot room 31C, idle 4 h', 240, room=31)
expect(vals(o) == [-16], f'one step to -16 and stays there, no cycling ({o})')
o = run('5 bursty: 2 min of 44 workers every 10 min for 2 h, 24C room', 200, room=24,
        evs=[(m, L(44)) for m in range(30, 150, 10)] + [(m + 2, L(0)) for m in range(30, 150, 10)])
expect(len(o) <= 2 and all(v not in (0, 127) for v in vals(o)) and (not o or o[-1][1] == -80), f'no Performance/Full, ends at -80 ({o})')
o = run('6 full load in a hot 28C room for 60 min', 200, room=28, evs=[(30, L(44)), (90, L(0))])
expect(o[:1] and o[0][1] == -16 and o[0][0] <= 36, f'-16 once the CPU passes 78C ({o[:1]})')
expect(all(v not in (0, 127) for v in vals(o)) and o[-1][1] == -80 and len(o) <= 3, f'no Performance/Full, back to -80 ({o})')
expect(plant['cpu_max'] < 82, f'hottest CPU under the BMC warning ({plant["cpu_max"]:.1f})')
o = run('7 emergency SIO1 83 for 5 min', 120, evs=[(10, lambda: plant.update(sio_force=83)), (15, lambda: plant.update(sio_force=None))])
expect(o[:1] and o[0][1] == 127, f'Full at once ({o[:1]})')
expect(len(o) >= 2 and o[1][1] == 0, f'then Performance after 5 min ({o[1:2]})')
o = run('8 sensors unreadable 10 min', 40, evs=[(5, lambda: plant.update(dead=True)), (15, lambda: plant.update(dead=False))])
expect(o[:1] and o[0][1] == 0, f'safe Performance after 5 min unreadable ({o[:1]})')
o = run('9 restart while the BMC is at -61 (left by a test)', 30, start=-61)
expect(o[:1] == [(0, -80)], f'puts -80 back on its first check ({o[:1]})')
o = run('10 cool room 22C (AC working): 4 threads for 20 min', 120, room=22, evs=[(30, L(4)), (50, L(0))])
expect(vals(o) == [-60, -80] and o[0][0] <= 33 and o[1][0] >= 60, f'-60 held to the end of the job and back ({o})')
o = run('11 4 threads for 3 h, 27C room', 240, evs=[(30, L(4)), (210, L(0))])
expect(vals(o) == [-60, -80] and o[1][0] >= 220, f'holds -60 steadily through a long light load ({o})')
o = run('12 hot room 31C for 2 h, then the room cools to 25C', 300, room=31, evs=[(120, lambda: plant.update(room=25))])
expect(o[:1] and o[0][1] == -16, f'-16 in the hot room ({o[:1]})')
expect(len(o) == 2 and o[1][1] == -80 and o[1][0] <= 200, f'back to -80 within ~80 min of the room cooling, and stays ({o})')
o = run('13 10-12 conditions: 24.5C room, 4 threads for 30 min', 120, room=24.5, evs=[(30, L(4)), (60, L(0))])
expect(vals(o) == [-60, -80] and 30 <= o[0][0] <= 33 and o[1][0] >= 70, f'-60 within 3 min (v2.3 never left -80), back ({o})')
o = run('14 -60 not enough: SIO1 forced to 80 for 6 min under the load, 24C room', 200, room=24,
        evs=[(30, L(4)), (50, lambda: plant.update(sio_force=80)), (56, lambda: plant.update(sio_force=None)), (120, L(0))])
expect(o[:1] and o[0][1] == -60, f'-60 first ({o[:1]})')
expect(len(o) >= 2 and o[1][1] == -16 and 50 <= o[1][0] <= 53, f'then -16 once SIO1 >= 79 at -60 ({o[1:2]})')
expect(o and o[-1][1] == -80, f'back to -80 in the end ({o[-1:]})')
o = run('15 restart while the BMC is at -60 (guard restarted under load), idle', 40, start=-60)
expect(vals(o) == [-80] and o[0][0] >= 10, f'treats -60 as BUSY, back to -80 after 10 idle min ({o})')
o = run('16 restart while the BMC is at -40 (v2.3 BUSY, not a level now), idle', 30, start=-40)
expect(o[:1] == [(0, -80)], f'puts -80 back on its first check ({o[:1]})')
o = run('17 one busy thread for 2 h, 27C room', 180, evs=[(30, L(1)), (150, L(0))])
expect(o == [], f'stays at -80 under BUSY_THREADS ({o})')
o = run('18 two busy threads for 60 min, 27C room', 150, evs=[(30, L(2)), (90, L(0))])
expect(vals(o) == [-60, -80] and o[0][0] <= 33, f'-60 at 2 busy threads, back afterwards ({o})')
o = run('19 a one-minute job (4 threads), 27C room', 60, evs=[(30, L(4)), (31, L(0))])
expect(o == [], f'a single busy reading changes nothing ({o})')
o = run('20 a CPU reads 84C for 3 min at idle (sensor glitch or a stuck fan)', 120,
        evs=[(10, lambda: plant.update(cpu_force=84)), (13, lambda: plant.update(cpu_force=None))])
expect(o[:1] and o[0][1] == 127 and o[0][0] <= 11, f'Full at CPU >= 83 ({o[:1]})')
expect(len(o) >= 2 and o[1][1] == 0 and o[-1][1] == -80, f'then Performance, then back to -80 ({o})')
o = run('21 boot with the BMC off the network for 3 min (10-12 power-cord pull)', 30, bmc_down_s=180)
expect(o == [] and any('assuming -80' in m for _, m in logs) and any('BMC check failed' in m for _, m in logs),
       f'assumes -80, retries the check until the BMC answers, no change ({o})')
# v2.5 (2026-10-13 afternoon)
o = run('22 half load (22 workers, 188 W) for 60 min, 24C room', 160, room=24, evs=[(30, L(22)), (90, L(0))])
expect(vals(o) == [-60, -80] and o[0][0] <= 33 and o[1][0] >= 100, f'-60 under a half load (the PSU tone sits in the band at -80), back ({o})')
o = run('23 a job that grows: 22 workers for 20 min, then 44 for 30 min, 24C room', 160, room=24,
        evs=[(30, L(22)), (50, L(44)), (80, L(0))])
expect(vals(o) == [-60, -80] and 50 <= o[1][0] <= 57, f'-60, then back to -80 within ~6 min of the full load, and stays ({o})')
o = run('24 package power in the dead band (225 W, ~28 workers) for 60 min from idle, 24C room', 140, room=24,
        evs=[(30, lambda: (plant.update(load=28), plant.update(pkg_force=225))), (90, lambda: (plant.update(load=0), plant.update(pkg_force=None)))])
expect(o == [], f'from -80: stays at -80 (not under BUSY_PKG_MAX) ({o})')
o = run('25 the same dead-band load starting at -60 (guard restarted in it), 24C room', 100, room=24, start=-60,
        evs=[(0, lambda: (plant.update(load=28), plant.update(pkg_force=225))), (60, lambda: (plant.update(load=0), plant.update(pkg_force=None)))])
expect(vals(o) == [-80] and o[0][0] >= 70, f'stays at -60 through it (not at HEAVY_PKG), back after 10 idle min ({o})')
o = run('26 power swinging 200 / 250 W every 3 min (a job across the line), 24C room', 150, room=24,
        evs=[(m, (lambda w: lambda: (plant.update(load=30), plant.update(pkg_force=w)))(200 if (m // 3) % 2 == 0 else 250)) for m in range(30, 120, 3)]
            + [(120, lambda: (plant.update(load=0), plant.update(pkg_force=None)))])
expect(len(o) <= 4, f'no flip-flop: at most a couple of changes ({o})')
o = run('27 RAPL unreadable (pkg None) under a full load, 24C room', 120, room=24,
        evs=[(30, lambda: (plant.update(load=44), plant.update(pkg_force=-1))), (80, lambda: (plant.update(load=0), plant.update(pkg_force=None)))])
expect(o[:1] and o[0][1] == -60, f'falls back to v2.4: -60 under any sustained load ({o})')
o = run('28 a lighter 44-thread job (200 W, e.g. a compile), 24C room', 120, room=24,
        evs=[(30, lambda: (plant.update(load=44), plant.update(pkg_force=200))), (80, lambda: (plant.update(load=0), plant.update(pkg_force=None)))])
expect(vals(o) == [-60, -80], f'-60: it is the power, not the thread count, that decides ({o})')
print('ALL PASS' if ok else 'SOME FAILED')
