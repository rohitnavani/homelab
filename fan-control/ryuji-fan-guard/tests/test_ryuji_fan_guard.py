# Closed-loop harness for ryuji-fan-guard (v2, 2026-10-06): fake clock + a ryuji model built from the 10-06 profile.
# SIO Temp 1 and the hottest CPU settle (tau 3.5 min / 1 min) toward values that depend on the guard level, the
# load and the room. usage: python3 tests/test_ryuji_fan_guard.py ryuji-fan-guard
import math, sys, types
SRC = sys.argv[1]
src = open(SRC).read().replace("if __name__ == '__main__':\n    main()", '')
clock = [1_000_000.0]; T0 = clock[0]
# equilibria at a 27C room, measured 10-06 (ryuji_profile_table.py). -80 4-thread SIO1 is past 79 and still rising
# when measured (estimate 82); -31 uses the -24 data; Full (127) is an estimate.
SIO = {-80: {0: 77.5, 4: 82.0, 20: 55.0}, -31: {0: 76.6, 4: 57.4, 20: 45.0}, -16: {0: 71.5, 4: 54.0, 20: 46.0},
       0: {0: 59.5, 4: 48.0, 20: 44.0}, 127: {0: 45.0, 4: 42.0, 20: 40.0}}
CPU = {-80: {0: 48, 4: 61, 20: 70}, -31: {0: 44, 4: 55, 20: 63}, -16: {0: 45, 4: 54, 20: 63}, 0: {0: 43, 4: 53, 20: 62},
       127: {0: 40, 4: 50, 20: 58}}
SIO_TAU = {-80: 600}   # SIO1 rises slowly at the -80 system-fan floor; ~210 s elsewhere
plant = {}
def reset(room, sio, cpu):
    plant.update(room=room, sio=sio, cpu=cpu, t=clock[0], load=0, cpu_extra=0.0, sio_force=None, dead=False)
state = {'off': -80}
def advance():
    dt = clock[0] - plant['t']; plant['t'] = clock[0]
    lvl = state['off'] if state['off'] in SIO else -80
    s_inf = SIO[lvl][plant['load']] + plant['room'] - 27
    c_inf = CPU[lvl][plant['load']] + plant['cpu_extra'] + (plant['room'] - 27)
    tau = SIO_TAU.get(lvl, 210) if s_inf > plant['sio'] else 210
    plant['sio'] = s_inf + (plant['sio'] - s_inf) * math.exp(-dt / tau)
    plant['cpu'] = c_inf + (plant['cpu'] - c_inf) * math.exp(-dt / 60)
def temps():
    advance()
    if plant['dead']:
        return None
    sio = plant['sio_force'] if plant['sio_force'] is not None else plant['sio']
    return {'sio': round(sio), 'cpu': round(plant['cpu']), 'vr': 60, 'dimm': 50}
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
    if action == 'set':
        state['off'] = offset; offsets.append((round((clock[0] - T0) / 60), offset))
    return state['off']
def run(label, end_min, room=27, start=-80, evs=()):
    offsets.clear(); logs.clear(); clock[0] = T0; END[0] = end_min * 60; state['off'] = start
    reset(room, SIO.get(start, SIO[-80])[0] + room - 27, CPU.get(start, CPU[-80])[0])
    events[:] = sorted((m * 60, f) for m, f in evs)
    g = {'__name__': 'sim'}
    exec(src, g)
    g['bmc'] = fake_bmc; g['temps'] = temps; g['STATE'] = '/dev/null'
    g['time'] = types.SimpleNamespace(time=lambda: clock[0], sleep=sleep, strftime=lambda *a: 'T')
    g['log'] = lambda m: logs.append((round((clock[0] - T0) / 60), m))
    try: g['main']()
    except Stop: pass
    print(f'## {label}\n   offset changes (min, offset): {offsets}   [SIO1 end {plant["sio"]:.1f}]')
    return offsets
def L(n): return lambda: plant.update(load=n)
ok = True
def expect(c, m):
    global ok; print('   ', 'PASS' if c else 'FAIL', m); ok &= c
o = run('1 idle, 27C room, 4 h', 240); expect(o == [], 'stays at -80 (SIO1 ~77.5 is under 79)')
o = run('2 4 busy threads for 60 min at 30 min, 27C room', 180, evs=[(30, L(4)), (90, L(0))])
expect(o[:1] and o[0][1] == -16 and 30 <= o[0][0] <= 45, f'-16 once SIO1 climbs under the load ({o[:1]})')
expect(o and o[-1][1] == -80 and o[-1][0] >= 100, f'back to -80 >= 10 idle min after the load ({o[-1:]})')
expect(all(v != 0 for _, v in o) and len(o) <= 2, f'never Performance, no flip-flop ({o})')
o = run('3 full load (20 threads) 60 min, 27C room', 180, evs=[(30, L(20)), (90, L(0))])
expect(o == [], f'stays at -80: the BMC curve raises the system fans itself at full load ({o})')
o = run('4 hot room 29C, idle 4 h', 240, room=29)
expect([v for _, v in o] == [-16], f'one step to -16 and stays there, no cycling ({o})')
o = run('5 bursty: 2 min of 20 threads every 10 min for 2 h', 180,
        evs=[(m, L(20)) for m in range(30, 150, 10)] + [(m + 2, L(0)) for m in range(30, 150, 10)])
expect(len(o) <= 2 and all(v != 0 for _, v in o), f'no Performance, at most one round trip ({o})')
o = run('6 hotter CPUs (E5-2699 v4: +20C at full load) 60 min', 200, evs=[(30, lambda: plant.update(load=20, cpu_extra=20)),
                                                                        (90, lambda: plant.update(load=0, cpu_extra=0))])
expect(any(v in (0, 127) for _, v in o), f'Performance/Full when the CPUs run hot ({o})')
expect(o and o[-1][1] == -80, f'all the way back to -80 afterwards ({o[-1:]})')
o = run('7 emergency SIO1 83 for 5 min', 120, evs=[(10, lambda: plant.update(sio_force=83)), (15, lambda: plant.update(sio_force=None))])
expect(o[:1] and o[0][1] == 127, f'Full at once ({o[:1]})')
expect(len(o) >= 2 and o[1][1] == 0, f'then Performance after 5 min ({o[1:2]})')
o = run('8 sensors unreadable 10 min', 40, evs=[(5, lambda: plant.update(dead=True)), (15, lambda: plant.update(dead=False))])
expect(o[:1] and o[0][1] == 0, f'safe Performance after 5 min unreadable ({o[:1]})')
o = run('9 restart while the BMC is at -61 (left by a test)', 30, start=-61)
expect(o[:1] == [(0, -80)], f'puts -80 back on its first check ({o[:1]})')
o = run('10 cool room 22C (AC working): 4 threads for 20 min', 120, room=22, evs=[(30, L(4)), (50, L(0))])
expect(o == [], f'stays at -80 for a short light job in a cool room ({o})')
o = run('11 4 threads for 3 h, 27C room', 240, evs=[(30, L(4)), (210, L(0))])
expect(len(o) <= 2 and all(v != 0 for _, v in o), f'holds -16 steadily through a long light load ({o})')
o = run('12 hot room 29C for 2 h, then the room cools to 25C', 300, room=29, evs=[(120, lambda: plant.update(room=25))])
expect(o[:1] and o[0][1] == -16, f'-16 in the hot room ({o[:1]})')
expect(len(o) == 2 and o[1][1] == -80 and o[1][0] <= 200, f'back to -80 within ~80 min of the room cooling, and stays ({o})')
print('ALL PASS' if ok else 'SOME FAILED')
