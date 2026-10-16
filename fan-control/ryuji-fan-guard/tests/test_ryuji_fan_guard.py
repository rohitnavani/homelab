# Closed-loop harness for ryuji-fan-guard (v2, 2026-10-06; v2.3 2026-10-10; v2.4-v2.6 2026-10-13; v2.7-v2.8 2026-10-14;
# v2.10 2026-10-15; v2.11 2026-10-16): fake clock + a ryuji
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
SIO = {-127: {0: 75.0, 2: 76.0, 4: 70.0, 22: 57.0, 33: 47.0, 44: 43.0},   # v2.10: fin_heavy 10-15 (+3C to 27C)
       -80: {0: 75.0, 2: 76.0, 4: 69.0, 22: 54.0, 44: 42.0}, -60: {0: 74.5, 2: 76.0, 4: 58.0, 22: 50.5, 44: 41.0},
       -40: {0: 74.5, 4: 51.0, 22: 48.0, 44: 40.0}, -16: {0: 71.5, 4: 49.0, 22: 45.0, 44: 39.0},
       0: {0: 59.5, 4: 47.0, 22: 44.0, 44: 39.0}, 127: {0: 45.0, 4: 42.0, 22: 40.0, 44: 37.0}}
CPU = {-127: {0: 45, 2: 64, 4: 68, 22: 72, 33: 77, 44: 80.5},   # v2.10: -80 + 3 / 4 / 3.5C at 22 / 33 / 44 workers
       -80: {0: 45, 2: 63, 4: 67, 22: 69, 33: 73, 44: 77}, -60: {0: 44, 2: 58, 4: 64, 22: 67, 33: 72, 44: 75},
       -40: {0: 44, 4: 59, 22: 66, 44: 74}, -16: {0: 43, 4: 58, 22: 62, 44: 72},
       0: {0: 41, 4: 56, 22: 62, 44: 72}, 127: {0: 40, 4: 55, 22: 61, 44: 71}}
PKG = {0: 18, 2: 90, 4: 110, 11: 148, 22: 188, 33: 245, 44: 296}   # W, both packages (PL1 150 W each from ~30 workers)
SIO_TAU = {-127: 600, -80: 600, -60: 600, -40: 600}   # SIO1 rises slowly with the system fans at their floor; ~210 s elsewhere
# v2.8: hottest MG04 drive at a 24C room, idle disks / a sustained random-read job, by offset (2026-10-14 soaks: -80 idle
# 45C, job +1C/min; 0: flat at 50C under the job; -8: 50 -> 51C in 6 min). tau 11 min. CPU load lifts the system fans
# (BMC curve), worth ~2C at 11-22 workers and ~4C at 44 (estimate).
DRV = {-127: (45, 56), -80: (45, 56), -60: (45, 56), -40: (45, 55), -16: (44, 54), -8: (43, 52), 0: (42, 50), 127: (39, 45)}
DRV_TAU = 660
def at(table, lvl, load):
    pts = sorted(table[lvl].items())
    for (l0, v0), (l1, v1) in zip(pts, pts[1:]):
        if load <= l1:
            return v0 + (v1 - v0) * (min(max(load, l0), l1) - l0) / (l1 - l0)
    return pts[-1][1]
plant = {}
def reset(room, sio, cpu):
    plant.update(room=room, sio=sio, cpu=cpu, t=clock[0], load=0, cpu_extra=0.0, sio_force=None, cpu_force=None,
                 dead=False, cpu_max=cpu, bmc_down=0, pkg_force=None, io=0, drive=None, drive_force=None, drive_max=0)
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
    if plant['drive'] is not None:
        d_inf = DRV.get(lvl, DRV[-80])[plant['io']] + (plant['room'] - 24) - (4 if plant['load'] >= 44 else 2 if plant['load'] >= 11 else 0)
        plant['drive'] = d_inf + (plant['drive'] - d_inf) * math.exp(-dt / DRV_TAU)
        plant['drive_max'] = max(plant['drive_max'], plant['drive'])
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
def drives():
    advance()
    if plant['drive_force'] is not None:
        return plant['drive_force']
    return None if plant['drive'] is None else round(plant['drive'])
def run(label, end_min, room=27, start=-80, evs=(), bmc_down_s=0, drive0=None):
    offsets.clear(); logs.clear(); clock[0] = T0; END[0] = end_min * 60; state['off'] = start
    lvl0 = start if start in SIO else -80
    reset(room, at(SIO, lvl0, 0) + room - 27, at(CPU, lvl0, 0) + room - 27)
    plant['bmc_down'] = bmc_down_s
    plant['drive'] = drive0
    events[:] = sorted((m * 60, f) for m, f in evs)
    g = {'__name__': 'sim'}
    exec(src, g)
    g['bmc'] = fake_bmc; g['temps'] = temps; g['STATE'] = '/dev/null'; g['drives'] = drives
    g['busy_threads'] = lambda: 0.05 + plant['load']   # the guard's /proc/stat reading
    g['pkg_watts'] = lambda: (None if plant.get('pkg_force') == -1 else plant['pkg_force'] if plant.get('pkg_force') is not None
                              else round(at({'p': PKG}, 'p', plant['load']), 1))
    g['time'] = types.SimpleNamespace(time=lambda: clock[0], sleep=sleep, strftime=lambda *a: 'T')
    g['log'] = lambda m: logs.append((round((clock[0] - T0) / 60), m))
    try: g['main']()
    except Stop: pass
    print(f'## {label}\n   offset changes (min, offset): {offsets}   [SIO1 end {plant["sio"]:.1f}, CPU max {plant["cpu_max"]:.1f}'
          + (f', drive max {plant["drive_max"]:.1f}, end {plant["drive"]:.1f}]' if plant['drive'] is not None else ']'))
    return offsets
def L(n): return lambda: plant.update(load=n)
ok = True
def expect(c, m):
    global ok; print('   ', 'PASS' if c else 'FAIL', m); ok &= bool(c)
vals = lambda o: [v for _, v in o]
def P(w): return lambda: plant.update(pkg_force=w)
o = run('1 idle, 27C room, 4 h', 240); expect(o == [], 'stays at -80 (SIO1 ~75 is under 79)')
o = run('2 4 busy threads for 60 min at 30 min, 27C room', 180, evs=[(30, L(4)), (90, L(0))])
expect(o == [], f'v2.7: stays at -80 under a light load (no -60 step) ({o})')
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
expect(o == [], f'v2.7: stays at -80 ({o})')
o = run('11 4 threads for 3 h, 27C room', 240, evs=[(30, L(4)), (210, L(0))])
expect(o == [], f'v2.7: -80 steadily through a long light load (SIO1 ~69 at 4 threads) ({o})')
o = run('12 hot room 31C for 2 h, then the room cools to 25C', 300, room=31, evs=[(120, lambda: plant.update(room=25))])
expect(o[:1] and o[0][1] == -16, f'-16 in the hot room ({o[:1]})')
expect(len(o) == 2 and o[1][1] == -80 and o[1][0] <= 200, f'back to -80 within ~80 min of the room cooling, and stays ({o})')
o = run('13 10-12 conditions: 24.5C room, 4 threads for 30 min', 120, room=24.5, evs=[(30, L(4)), (60, L(0))])
expect(o == [], f'v2.7: stays at -80 ({o})')
o = run('14 SIO1 forced to 80 for 6 min under a light load, 24C room', 200, room=24,
        evs=[(30, L(4)), (50, lambda: plant.update(sio_force=80)), (56, lambda: plant.update(sio_force=None)), (120, L(0))])
expect(o[:1] and o[0][1] == -16 and 50 <= o[0][0] <= 53, f'v2.7: -16 straight from -80 once SIO1 >= 79 ({o[:1]})')
expect(o and o[-1][1] == -80, f'back to -80 in the end ({o[-1:]})')
o = run('15 restart while the BMC is at -60 (guard restarted under load), idle', 40, start=-60)
expect(vals(o) == [-80] and o[0][0] <= 1, f'v2.7: a BMC left at -60 goes back to -80 at once ({o})')
o = run('16 restart while the BMC is at -40 (v2.3 BUSY, not a level now), idle', 30, start=-40)
expect(o[:1] == [(0, -80)], f'puts -80 back on its first check ({o[:1]})')
o = run('17 one busy thread for 2 h, 27C room', 180, evs=[(30, L(1)), (150, L(0))])
expect(o == [], f'stays at -80 under BUSY_THREADS ({o})')
o = run('18 two busy threads for 60 min, 27C room', 150, evs=[(30, L(2)), (90, L(0))])
expect(o == [], f'v2.7: stays at -80 at 2 busy threads ({o})')
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
expect(o == [], f'v2.11: stays at -80 (22 workers draw ~190 W, under the 220 W line; with one supply -127 is louder there) ({o})')
o = run('22b 11 workers (148 W) for 60 min, 24C room', 160, room=24, evs=[(30, L(11)), (90, L(0))])
expect(o == [], f'v2.7: stays at -80 at 11 workers (-80 3 dB quieter than -60 in the rack) ({o})')
o = run('23 a job that grows: 11 workers for 20 min, then 44 for 30 min, 24C room', 160, room=24,
        evs=[(30, L(11)), (50, L(44)), (80, L(0))])
expect(o == [], f'v2.7: -80 throughout ({o})')
o = run('24 package power in the dead band (170 W, ~16 workers) for 60 min from idle, 24C room', 140, room=24,
        evs=[(30, lambda: (plant.update(load=16), plant.update(pkg_force=170))), (90, lambda: (plant.update(load=0), plant.update(pkg_force=None)))])
expect(o == [], f'from -80: stays at -80 (not under BUSY_PKG_MAX) ({o})')
o = run('25 the same dead-band load starting at -60 (guard restarted in it), 24C room', 100, room=24, start=-60,
        evs=[(0, lambda: (plant.update(load=16), plant.update(pkg_force=170))), (60, lambda: (plant.update(load=0), plant.update(pkg_force=None)))])
expect(vals(o) == [-80] and o[0][0] <= 1, f'v2.7: back to -80 at once, stays ({o})')
o = run('26 power swinging 140 / 200 W every 3 min (a job across the line), 24C room', 150, room=24,
        evs=[(m, (lambda w: lambda: (plant.update(load=12), plant.update(pkg_force=w)))(140 if (m // 3) % 2 == 0 else 200)) for m in range(30, 120, 3)]
            + [(120, lambda: (plant.update(load=0), plant.update(pkg_force=None)))])
expect(o == [], f'v2.7: no change at all ({o})')
o = run('27 RAPL unreadable (pkg None) under a full load, 24C room', 120, room=24,
        evs=[(30, lambda: (plant.update(load=44), plant.update(pkg_force=-1))), (80, lambda: (plant.update(load=0), plant.update(pkg_force=None)))])
expect(o == [], f'v2.7: -80 (power no longer decides anything) ({o})')
o = run('28 a light 44-thread job (120 W, e.g. mostly waiting on I/O), 24C room', 120, room=24,
        evs=[(30, lambda: (plant.update(load=44), plant.update(pkg_force=120))), (80, lambda: (plant.update(load=0), plant.update(pkg_force=None)))])
expect(o == [], f'v2.7: -80 ({o})')
# v2.7 (2026-10-14)
o = run('29 4 threads for 2 h in a warm 29C room', 200, room=29, evs=[(30, L(4)), (150, L(0))])
expect(o == [], f'v2.7: -80 (SIO1 ~71, CPU ~69) ({o})')
o = run('30 2 threads for 2 h in a hot 31C room (SIO1 climbs past 77 at the -80 floor)', 200, room=31, evs=[(30, L(2)), (150, L(0))])
expect(o[:1] and o[0][1] == -16, f'v2.7: -16 straight from -80 when SIO1 climbs ({o[:1]})')
expect(all(v not in (0, 127, -60) for v in vals(o)), f'never -60, Performance or Full ({o})')
# v2.8 (2026-10-14): drives
def IO(n): return lambda: plant.update(io=n)
o = run('31 a disk job (random reads) for 60 min at idle CPU, 24C room', 160, room=24, drive0=45, evs=[(30, IO(1)), (90, IO(0))])
expect(o[:1] and o[0][1] == 0 and 34 <= o[0][0] <= 38, f'Performance ~5-7 min into the job ({o[:1]})')
expect(plant['drive_max'] <= 51, f'hottest drive held at 51C or less ({plant["drive_max"]:.1f})')
expect(vals(o) == [0, -80] and 100 <= o[1][0] <= 125, f'back to -80 once the drives are cool for 10 min ({o})')
o = run('32 idle with the drives at their idle temperature, 24C room, 4 h', 240, room=24, drive0=45)
expect(o == [], f'no change (45C) ({o})')
o = run('33 one bogus drive reading of 60C', 60, room=24, drive0=45, evs=[(10, lambda: plant.update(drive_force=60)), (11, lambda: plant.update(drive_force=None))])
expect(o == [], f'a single reading changes nothing ({o})')
o = run('34 a disk job in a 30C room (drives past 52C even at Performance)', 120, room=30, drive0=51, evs=[(10, IO(1)), (100, IO(0))])
expect(any(v == 127 for v in vals(o)), f'Full Speed when a drive reaches 52C ({o})')
expect(plant['drive_max'] < 55, f'hottest drive stays under its 55C rating ({plant["drive_max"]:.1f})')
o = run('35 a disk job with 22 workers of CPU load, 24C room', 120, room=24, drive0=45, evs=[(10, lambda: (plant.update(load=22), plant.update(io=1))), (70, lambda: (plant.update(load=0), plant.update(io=0)))])
expect(0 in vals(o) and vals(o)[0] in (0, -127), f'Performance for the drives (via -127 first is fine) ({o})')
expect(o[-1][1] == -80 and plant['drive_max'] <= 51, f'back to -80 at the end, drives <= 51C ({o}, {plant["drive_max"]:.1f})')
o = run('36 drives unreadable (None) under a disk job', 120, room=24, drive0=None, evs=[(10, IO(1)), (70, IO(0))])
expect(o == [], f'no drive rule without readings ({o})')
o = run('38 idle in a warm 27C room (warmest disk ~48C at -80), 4 h', 240, room=27, drive0=47)
expect(o == [], f'v2.8: DRIVE_UP 49 keeps a warm room from cycling at idle ({o})')
o = run('37 drive-triggered Performance while a 4-thread job also runs, 24C room', 160, room=24, drive0=45,
        evs=[(10, lambda: (plant.update(load=4), plant.update(io=1))), (40, IO(0)), (100, L(0))])
expect(o[:1] and o[0][1] == 0, f'Performance for the drives ({o[:1]})')
expect(vals(o)[-1:] == [-80] and all(v not in (127,) for v in vals(o)), f'back to -80 once drives cool (CPU load alone keeps -80) ({o})')
# v2.10 (2026-10-15): -127 for heavy loads
o = run('40 22 workers for 60 min, 24C room', 160, room=24, evs=[(30, L(22)), (90, L(0))])
expect(o == [], f'v2.11: stays at -80 (188 W < 220 W) ({o})')
o = run('40b 29 workers (~224 W) for 60 min, 24C room', 160, room=24, evs=[(30, L(29)), (90, L(0))])
expect(vals(o) == [-127, -80] and o[0][0] <= 37 and plant['cpu_max'] < 77, f'v2.11: -127 just over the line, CPU under 77C, back after ({o}, {plant["cpu_max"]:.1f})')
o = run('40c 26 workers (~209 W) for 60 min, 24C room', 160, room=24, evs=[(30, L(26)), (90, L(0))])
expect(o == [], f'v2.11: stays at -80 just under the line ({o})')
o = run('41 33 workers for 60 min, 24C room', 160, room=24, evs=[(30, L(33)), (90, L(0))])
expect(vals(o) == [-127, -80] and plant['cpu_max'] < 77, f'-127 held, CPU under 77C ({o}, {plant["cpu_max"]:.1f})')
o = run('42 full load (44 workers) for 60 min, 24C room', 160, room=24, evs=[(30, L(44)), (90, L(0))])
expect(o == [], f'full load stays at -80 (CPU 74C > the 72C entry line) ({o})')
o = run('43 a job growing from 33 to 44 workers, 24C room', 180, room=24, evs=[(30, L(33)), (60, L(44)), (120, L(0))])
expect(vals(o)[:2] == [-127, -80] and len(o) == 2, f'-127 at 33 workers, back to -80 once the CPUs reach 77C at full load, no cycling ({o})')
expect(plant['cpu_max'] < 79, f'hottest CPU under 79C ({plant["cpu_max"]:.1f})')
o = run('43b a job growing from 22 to 44 workers, 24C room', 180, room=24, evs=[(30, L(22)), (60, L(44)), (120, L(0))])
expect(o == [] and plant['cpu_max'] < 79, f'v2.11: -80 throughout (22 under the line, 44 too warm to enter) ({o}, {plant["cpu_max"]:.1f})')
o = run('44 33 workers in a warm 28C room', 160, room=28, evs=[(30, L(33)), (90, L(0))])
expect(-127 not in vals(o) and all(v not in (0, 127) for v in vals(o)), f'no -127 in a warm room (CPU over 72C at -80) ({o})')
o = run('45 bursts: 2 min of 44 workers every 10 min, 24C room', 200, room=24,
        evs=[(m, L(44)) for m in range(30, 150, 10)] + [(m + 2, L(0)) for m in range(30, 150, 10)])
expect(-127 not in vals(o), f'short bursts never reach -127 (needs 5 heavy readings in a row) ({o})')
o = run('46 restart while the BMC is at -127 (left by a test), idle', 30, start=-127)
expect(vals(o) == [-80] and o[0][0] <= 7, f'treats -127 as HEAVY, back to -80 after 5 light readings ({o})')
o = run('47 33 workers 60 min with a disk job from minute 50, 24C room', 160, room=24, drive0=45,
        evs=[(30, L(33)), (50, IO(1)), (90, lambda: (plant.update(load=0), plant.update(io=0)))])
expect(-127 in vals(o) and 0 in vals(o) and vals(o)[-1] == -80, f'-127, then Performance for the drives, then back ({o})')
print('ALL PASS' if ok else 'SOME FAILED')
