#!/usr/bin/env python3
# make-units (2026-10-13): the final rack run's schedule as persistent systemd units, one .service + .timer per block,
# written to ~/lab-thermal-2026-10-14/units/<host>/. Each service: fin-gate.py as ExecStartPre (waits while a block it
# depends on still runs, on any host, via Prometheus; refuses after its not-after time), LOAD_UNTIL for the test
# scripts, a RuntimeMaxSec cap, and the restore script as ExecStopPost. Unit names start with the repo tool names the
# lab-thermal alert rules know (ryuji-floor*, mementos-steps*, scrub-quiet*, mic-shelf*, mic-r720*), so
# FanControllerStale stays quiet while they run. Prints the schedule.
import os, time

OUT = os.path.expanduser('~/lab-thermal-2026-10-14/units')
R, M = '10.0.0.9', '10.0.0.10'


def ep(s):
    return int(time.mktime(time.strptime(s, '%Y-%m-%d %H:%M')))


LU = {'2026-10-14': ep('2026-10-14 21:30'), '2026-10-15': ep('2026-10-15 15:58'), '2026-10-16': ep('2026-10-16 15:58')}
RF = '/usr/bin/python3 /var/tmp/ryuji-floor-fin.py'
MS = '/usr/bin/python3 /var/tmp/mementos-steps-fin.py'
DS = '/usr/bin/python3 /var/tmp/disk-soak.py'
RREST, MREST = '/var/tmp/ryuji-profile-restore.sh', '/var/tmp/mementos-steps-restore-fin.sh'
# (host, unit, day, start HH:MM, not-after HH:MM, blockers, command, ExecStopPost, max minutes, what)
B = [
    # Wednesday 10-14: medium window 08:00-22:00 (Rohit WFH)
    ('ryuji', 'ryuji-floor-fin-light', '2026-10-14', '08:00', '08:30', [], f'{RF} finlight1014 fin_light', RREST, 305,
     'ryuji 2/4/11 workers, -80/-60/-40 A/B/A, 20 min holds'),
    ('mementos', 'mementos-steps-fin-steps', '2026-10-14', '12:25', '13:30', [f'{R}:ryuji-floor-fin-light.*'],
     f'{MS} fin_steps finsteps1014', MREST, 155, 'mementos 6/12/18/24 workers under fan-watchdog, 20 min each'),
    ('mementos', 'scrub-quiet-soak-shelf', '2026-10-14', '14:30', '15:30', [f'{M}:mementos-steps-fin-steps.*'],
     f'{DS} shelf1014 dataPool seq:60,rand:120 54', None, 200, 'shelf drives: 60 min sequential + 120 min random reads'),
    ('mementos', 'scrub-quiet-soak-int', '2026-10-14', '14:30', '15:30', [f'{M}:mementos-steps-fin-steps.*'],
     f'{DS} int1014 vmPool rand:90 50', None, 110, 'mementos internal drives: 90 min random reads'),
    ('ryuji', 'ryuji-floor-disk-wed', '2026-10-14', '14:30', '15:30', [f'{M}:mementos-steps-fin-steps.*'],
     f'{DS} ryuji1014 computePool rand:90 50', None, 110, 'ryuji drives: 90 min random reads, CPUs idle'),
    ('ryuji', 'ryuji-floor-fin-mixed', '2026-10-14', '17:35', '18:20',
     [f'{M}:scrub-quiet-soak-.*', f'{R}:ryuji-floor-disk-wed.*'], f'{RF} finmixed1014 fin_mixed', RREST, 105,
     'everyday medium mix: ryuji 11 workers'),
    ('mementos', 'mementos-steps-fin-mixed', '2026-10-14', '17:35', '18:20',
     [f'{M}:scrub-quiet-soak-.*', f'{R}:ryuji-floor-disk-wed.*'], f'{MS} fin_mixed finmixed1014', MREST, 105,
     'everyday medium mix: mementos 12 workers'),
    ('mementos', 'scrub-quiet-soak-mix', '2026-10-14', '17:45', '18:25', [f'{M}:scrub-quiet-soak-shelf.*'],
     f'{DS} mix1014 dataPool seq:45 54', None, 55, 'everyday medium mix: shelf sequential reads'),
    ('ryuji', 'ryuji-floor-fin-burstm', '2026-10-14', '19:00', '19:45',
     [f'{R}:ryuji-floor-fin-mixed.*', f'{M}:mementos-steps-fin-mixed.*', f'{M}:scrub-quiet-soak-mix.*'],
     f'{RF} finburstm1014 fin_burstm', RREST, 90, 'ryuji medium bursts (0-11 workers), hunting check'),
    ('mementos', 'mementos-steps-fin-burstm', '2026-10-14', '20:00', '20:45', [f'{R}:ryuji-floor-fin-burstm.*'],
     f'{MS} fin_burstm finburstm1014', MREST, 90, 'mementos medium bursts (0-18 workers), hunting check'),
    # Thursday 10-15: loud window 07:00-16:00, all test load off by 16:30 (Rohit at work)
    ('mementos', 'mic-shelf-sweep-fin', '2026-10-15', '07:05', '07:45', [], '/usr/bin/python3 /var/tmp/noise-sweep.py',
     '/var/tmp/noise-sweep-restore.sh', 90, 'noise sweep at idle: shelf 10-40%, mementos 10-50%'),
    ('mementos', 'mic-r720-notch-fin', '2026-10-15', '08:10', '08:50', [f'{M}:mic-shelf-sweep-fin.*'],
     '/usr/bin/python3 /var/tmp/r720-notch-sweep.py', '/var/tmp/r720-notch-restore.sh', 45,
     'mementos 36-44% in 1% steps (the ringing band)'),
    ('ryuji', 'ryuji-floor-fin-idleoff', '2026-10-15', '08:40', '09:20',
     [f'{M}:mic-r720-notch-fin.*', f'{M}:mic-shelf-sweep-fin.*'], f'{RF} finidleoff1015 fin_idleoff', RREST, 50,
     'ryuji offsets at idle, A/B against -80'),
    ('ryuji', 'ryuji-floor-fin-heavy', '2026-10-15', '09:15', '09:55', [f'{R}:ryuji-floor-fin-idleoff.*'],
     f'{RF} finheavy1015 fin_heavy', RREST, 225, 'ryuji 22/33/44 workers at -80 vs -127, 15-20 min holds'),
    ('mementos', 'mementos-steps-fin-high', '2026-10-15', '12:30', '13:15', [f'{R}:ryuji-floor-fin-heavy.*'],
     f'{MS} fin_high finhigh1015', MREST, 120, 'mementos 36/48 workers and a full load from idle'),
    ('ryuji', 'ryuji-floor-fin-comb', '2026-10-15', '14:05', '14:30',
     [f'{M}:mementos-steps-fin-high.*', f'{R}:ryuji-floor-fin-heavy.*'], f'{RF} fincomb1015 fin_comb', RREST, 140,
     'combined full tilt: ryuji 44 workers 100 min'),
    ('mementos', 'mementos-steps-fin-comb', '2026-10-15', '14:05', '14:30',
     [f'{M}:mementos-steps-fin-high.*', f'{R}:ryuji-floor-fin-heavy.*'], f'{MS} fin_comb fincomb1015', MREST, 140,
     'combined full tilt: mementos idle 20, 24 workers 20, 48 workers 60 min'),
    ('mementos', 'scrub-quiet-soak-comb-shelf', '2026-10-15', '14:45', '15:10', [f'{M}:mementos-steps-fin-high.*'],
     f'{DS} combshelf1015 dataPool rand:60 54', None, 70, 'combined full tilt: shelf random reads'),
    ('mementos', 'scrub-quiet-soak-comb-int', '2026-10-15', '14:45', '15:10', [f'{M}:mementos-steps-fin-high.*'],
     f'{DS} combint1015 vmPool rand:60 50', None, 70, 'combined full tilt: mementos internal random reads'),
    ('ryuji', 'ryuji-floor-disk-comb', '2026-10-15', '14:45', '15:10', [f'{R}:ryuji-floor-fin-heavy.*'],
     f'{DS} combryuji1015 computePool rand:60 50', None, 70, 'combined full tilt: ryuji drive random reads'),
    # Friday 10-16: loud window 07:00-16:00, off by 16:30. The soak runs only if Rohit has not flagged the adapter.
    ('ryuji', 'ryuji-floor-fin-soak', '2026-10-16', '07:05', '07:30', [], f'{RF} finsoak1016 fin_soak', RREST, 170,
     '2 h soak: ryuji 33 workers'),
    ('mementos', 'mementos-steps-fin-soak', '2026-10-16', '07:05', '07:30', [], f'{MS} fin_soak finsoak1016', MREST, 170,
     '2 h soak: mementos 36 workers'),
    ('mementos', 'scrub-quiet-soak-fri', '2026-10-16', '07:10', '07:30', [], f'{DS} soakshelf1016 dataPool rand:120 54',
     None, 130, '2 h soak: shelf random reads'),
    ('ryuji', 'ryuji-floor-fin-val', '2026-10-16', '09:40', '10:15',
     [f'{R}:ryuji-floor-fin-soak.*', f'{M}:mementos-steps-fin-soak.*', f'{M}:scrub-quiet-soak-fri.*'],
     f'{RF} finval1016 fin_val', RREST, 175, 'validation: ryuji every load level under the guard as deployed'),
    ('mementos', 'mementos-steps-fin-val', '2026-10-16', '12:10', '12:45', [f'{R}:ryuji-floor-fin-val.*'],
     f'{MS} fin_val finval1016', MREST, 180, 'validation: mementos every load level under fan-watchdog as deployed'),
    ('ryuji', 'ryuji-floor-fin-burst', '2026-10-16', '14:45', '15:05', [f'{M}:mementos-steps-fin-val.*'],
     f'{RF} finburst1016 fin_burst', RREST, 90, 'bursts 0-44 workers, hunting check'),
    ('mementos', 'mementos-steps-fin-burst', '2026-10-16', '14:45', '15:05', [f'{M}:mementos-steps-fin-val.*'],
     f'{MS} fin_burst finburst1016', MREST, 90, 'bursts 0-48 workers, hunting check'),
]
# backstops: (unit, day, time); pdu-cut: (unit, day, start, minutes, units it may stop on ryuji / on mementos)
STOPS = [('lab-loadoff-final-wed', '2026-10-14', '22:00'), ('lab-loadoff-final-thu', '2026-10-15', '16:25'),
         ('lab-loadoff-final-thu2', '2026-10-15', '22:00'), ('lab-loadoff-final-fri', '2026-10-16', '16:25')]
CUTS = [('pdu-cut-thu', '2026-10-15', '14:00', 150, 'ryuji-floor-fin-comb* ryuji-floor-disk-comb*',
         'mementos-steps-fin-comb* scrub-quiet-soak-comb*'),
        ('pdu-cut-fri', '2026-10-16', '07:00', 170, 'ryuji-floor-fin-soak*', 'mementos-steps-fin-soak* scrub-quiet-soak-fri*')]


def timer(unit, day, hm, what):
    return (f'[Unit]\nDescription=lab final rack run: start {unit} {day} {hm}\n\n[Timer]\nOnCalendar={day} {hm}:00\n'
            f'AccuracySec=1s\nPersistent=false\nUnit={unit}.service\n\n[Install]\nWantedBy=timers.target\n')


rows = []
for host in ('ryuji', 'mementos'):
    os.makedirs(f'{OUT}/{host}', exist_ok=True)
    for f in os.listdir(f'{OUT}/{host}'):
        os.remove(f'{OUT}/{host}/{f}')
for host, unit, day, hm, na, blk, cmd, post, mx, what in B:
    gate = ' '.join([str(ep(f'{day} {na}'))] + [f"'{b}'" for b in blk])
    svc = (f'[Unit]\nDescription=lab final rack run: {what}\nAfter=network-online.target\n\n[Service]\nType=simple\n'
           f'TimeoutStartSec=infinity\nEnvironment=LOAD_UNTIL={LU[day]}\n'
           f'ExecStartPre=/usr/bin/python3 /var/tmp/fin-gate.py {gate}\nExecStart={cmd}\n'
           + (f'ExecStopPost={post}\n' if post else '') + f'RuntimeMaxSec={mx * 60}\n')
    open(f'{OUT}/{host}/{unit}.service', 'w').write(svc)
    open(f'{OUT}/{host}/{unit}.timer', 'w').write(timer(unit, day, hm, what))
    rows.append((day, hm, host, unit, na, what))
for unit, day, hm in STOPS:
    for host in ('ryuji', 'mementos'):
        open(f'{OUT}/{host}/{unit}.service', 'w').write(
            f'[Unit]\nDescription=lab final rack run: load-off backstop {day} {hm}\n\n[Service]\nType=oneshot\n'
            f'ExecStart=/bin/sh /var/tmp/lab-loadoff-final.sh\n')
        open(f'{OUT}/{host}/{unit}.timer', 'w').write(timer(unit, day, hm, 'backstop'))
    rows.append((day, hm, 'both', unit, '', 'backstop: stop test units, kill stress-ng/fio, controllers on'))
for unit, day, hm, mins, ru, mu in CUTS:
    for host, units in (('ryuji', ru), ('mementos', mu)):
        open(f'{OUT}/{host}/{unit}.service', 'w').write(
            f'[Unit]\nDescription=lab final rack run: PDU cut at 14.0 A\n\n[Service]\nType=simple\n'
            f'Environment=LIMIT=140 LOG=/var/tmp/{unit}.log "UNITS={units}"\nExecStart=/bin/bash /var/tmp/pdu-cut.sh\n'
            f'RuntimeMaxSec={mins * 60}\n')
        open(f'{OUT}/{host}/{unit}.timer', 'w').write(timer(unit, day, hm, 'pdu cut'))
    rows.append((day, hm, 'both', unit, '', f'PDU cut at 14.0 A for {mins} min'))
for r in sorted(rows):
    print(f'{r[0]} {r[1]}  {r[2]:<9} {r[3]:<30} {("not after " + r[4]) if r[4] else "":<16} {r[5]}')
