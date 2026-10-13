# Closed-loop harness for ryuji-fan-guard (v2, 2026-10-06; v2.3 2026-10-10; v2.4 2026-10-13): fake clock + a ryuji
# model. SIO Temp 1 and the hottest CPU settle (tau 3.5 min / 1 min) toward values that depend on the guard level, the
# load (busy threads) and the room. usage: python3 tests/test_ryuji_fan_guard.py ryuji-fan-guard
# v2.4: the model is for the 2x Xeon E5-2696 v4 fitted 2026-10-12 (44 cores / 88 threads, 150 W PL1 each). Idle and 4
# threads come from the 10-12 evening holds (room 24-25C, ryuji out of the rack), shifted to a 27C room. The 44-thread
# (full load) values are pessimistic estimates until the full-load profile replaces them (METHODOLOGY's prediction:
# 77-79C at a 22C room with loud CPU fans, so ~82-84C at 27C). Other loads interpolate linearly between 0, 4 and 44.
import math, sys, types
SRC = sys.argv[1]
src = open(SRC).read().replace("if __name__ == '__main__':\n    main()", '')
clock = [1_000_000.0]; T0 = clock[0]
# equilibria at a 27C room: {offset: {busy threads: value}}
SIO = {-80: {0: 76.0, 4: 69.0, 44: 58.0}, -60: {0: 75.5, 4: 56.5, 44: 52.0}, -40: {0: 75.0, 4: 51.0, 44: 49.0},
       -16: {0: 71.5, 4: 49.0, 44: 47.0}, 0: {0: 59.5, 4: 47.0, 44: 45.0}, 127: {0: 45.0, 4: 42.0, 44: 40.0}}
CPU = {-80: {0: 46, 4: 66.5, 44: 91}, -60: {0: 45, 4: 63.5, 44: 89}, -40: {0: 44, 4: 59, 44: 87},
       -16: {0: 44, 4: 58, 44: 85}, 0: {0: 42, 4: 56, 44: 82}, 127: {0: 40, 4: 53, 44: 80}}
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
                 dead=False, cpu_max=cpu, bmc_down=0)
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
o = run('1 idle, 27C room, 4 h', 240); expect(o == [], 'stays at -80 (SIO1 ~76 is under 79)')
o = run('2 4 busy threads for 60 min at 30 min, 27C room', 180, evs=[(30, L(4)), (90, L(0))])
expect(o[:1] and o[0][1] == -60 and 30 <= o[0][0] <= 33, f'v2.4: -60 within 3 min of the load ({o[:1]})')
expect(o and o[-1][1] == -80 and o[-1][0] >= 100, f'back to -80 >= 10 idle min after the load ({o[-1:]})')
expect(vals(o) == [-60, -80], f'never -16 or Performance, no flip-flop ({o})')
o = run('3 full load (44 threads) for 60 min, 24C room', 220, room=24, evs=[(30, L(44)), (90, L(0))])
expect(o[:1] and o[0][1] in (-60, -16) and 30 <= o[0][0] <= 33, f'leaves -80 within 3 min ({o[:1]})')
expect(any(v in (0, 127) for v in vals(o)), f'Performance or Full while the CPUs run hot ({o})')
expect(len(o) <= 6 and o and o[-1][1] == -80, f'no flip-flop, back to -80 in the end ({o})')
expect(plant['cpu_max'] < 85, f'hottest CPU stays under the 85C critical ({plant["cpu_max"]:.1f})')
o = run('4 hot room 30C, idle 4 h', 240, room=30)
expect(vals(o) == [-16], f'one step to -16 and stays there, no cycling ({o})')
o = run('5 bursty: 2 min of 44 threads every 10 min for 2 h, 24C room', 200, room=24,
        evs=[(m, L(44)) for m in range(30, 150, 10)] + [(m + 2, L(0)) for m in range(30, 150, 10)])
expect(o[:1] and o[0][1] == -60, f'-60 at the first bursts ({o[:1]})')
expect(all(v not in (0, 127) for v in vals(o)) and len(o) <= 4, f'no Performance/Full, at most 4 changes ({o})')
expect(o and o[-1][1] == -80, f'back to -80 after the bursts ({o[-1:]})')
o = run('6 full load in a hot 28C room for 60 min', 240, room=28, evs=[(30, L(44)), (90, L(0))])
expect(any(v in (0, 127) for v in vals(o)), f'Performance/Full when the CPUs run hot ({o})')
expect(len(o) <= 6 and o and o[-1][1] == -80, f'no cycling, all the way back to -80 afterwards ({o})')
o = run('7 emergency SIO1 83 for 5 min', 120, evs=[(10, lambda: plant.update(sio_force=83)), (15, lambda: plant.update(sio_force=None))])
expect(o[:1] and o[0][1] == 127, f'Full at once ({o[:1]})')
expect(len(o) >= 2 and o[1][1] == 0, f'then Performance after 5 min ({o[1:2]})')
o = run('8 sensors unreadable 10 min', 40, evs=[(5, lambda: plant.update(dead=True)), (15, lambda: plant.update(dead=False))])
expect(o[:1] and o[0][1] == 0, f'safe Performance after 5 min unreadable ({o[:1]})')
o = run('9 restart while the BMC is at -61 (left by a test)', 30, start=-61)
expect(o[:1] == [(0, -80)], f'puts -80 back on its first check ({o[:1]})')
o = run('10 cool room 22C (AC working): 4 threads for 20 min', 120, room=22, evs=[(30, L(4)), (50, L(0))])
expect(vals(o) == [-60, -80] and o[0][0] <= 33 and o[1][0] >= 60, f'v2.4: -60 held to the end of the job and back ({o})')
o = run('11 4 threads for 3 h, 27C room', 240, evs=[(30, L(4)), (210, L(0))])
expect(vals(o) == [-60, -80] and o[1][0] >= 220, f'holds -60 steadily through a long light load ({o})')
o = run('12 hot room 30C for 2 h, then the room cools to 25C', 300, room=30, evs=[(120, lambda: plant.update(room=25))])
expect(o[:1] and o[0][1] == -16, f'-16 in the hot room ({o[:1]})')
expect(len(o) == 2 and o[1][1] == -80 and o[1][0] <= 200, f'back to -80 within ~80 min of the room cooling, and stays ({o})')
o = run('13 10-12 conditions: 24.5C room, 4 threads for 30 min', 120, room=24.5, evs=[(30, L(4)), (60, L(0))])
expect(o[:1] and o[0][1] == -60 and 30 <= o[0][0] <= 33, f'-60 within 3 min (v2.3 never left -80 here) ({o[:1]})')
expect(vals(o) == [-60, -80] and o[1][0] >= 70, f'held to the end, back to -80 >= 10 idle min later ({o})')
o = run('14 -60 not enough: SIO1 forced to 80 for 6 min under the load, 24C room', 200, room=24,
        evs=[(30, L(4)), (50, lambda: plant.update(sio_force=80)), (56, lambda: plant.update(sio_force=None)), (120, L(0))])
expect(o[:1] and o[0][1] == -60, f'-60 first ({o[:1]})')
expect(len(o) >= 2 and o[1][1] == -16 and 50 <= o[1][0] <= 53, f'then -16 once SIO1 >= 79 at -60 ({o[1:2]})')
expect(o and o[-1][1] == -80, f'back to -80 in the end ({o[-1:]})')
o = run('15 restart while the BMC is at -60 (guard restarted under load), idle', 40, start=-60)
expect(vals(o) == [-80] and o[0][0] >= 10, f'treats -60 as BUSY, back to -80 after 10 idle min ({o})')
# v2.4 (2026-10-13)
o = run('16 restart while the BMC is at -40 (v2.3 BUSY, not a v2.4 level), idle', 30, start=-40)
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
       f'assumes -80, retries the check until the BMC answers, no change ({o}; {[m for _, m in logs][:3]})')
print('ALL PASS' if ok else 'SOME FAILED')
