#!/usr/bin/env python3
# make-units (2026-10-13; 10-20 version for the new-spot run): the run's schedule as persistent systemd units, one
# .service + .timer per block, written to ~/lab-thermal-2026-10-20/units/<host>/. Each service: fin-gate.py as
# ExecStartPre (waits while a block it depends on still runs, on any host; refuses after its not-after time), LOAD_UNTIL
# for the test scripts, a RuntimeMaxSec cap, and the restore script as ExecStopPost. Unit names on mementos and ryuji
# start with the repo tool names the lab-thermal alert rules know (ryuji-floor*, mementos-steps*, scrub-quiet*,
# mic-shelf*, mic-r720*) when they stop or override a controller, so FanControllerStale stays quiet while they run.
# Hosts without a controller-state metric (sojiro, tinynas, futaba, morgana, yusuke, tinypc) use lab-load-* / lab-soak-*.
# usage: make-units.py [DAY ...]   (default: every day) - prints the schedule
import os, sys, time

OUT = os.path.expanduser('~/lab-thermal-2026-10-20/units')
IP = {'tinypc': '10.0.0.2', 'futaba': '10.0.0.3', 'yusuke': '10.0.0.4', 'tinynas': '10.0.0.5', 'makoto': '10.0.0.6',
      'morgana': '10.0.0.7', 'sojiro': '10.0.0.8', 'ryuji': '10.0.0.9', 'mementos': '10.0.0.10'}
R, M, S = IP['ryuji'], IP['mementos'], IP['sojiro']
HOSTS = ['mementos', 'ryuji', 'sojiro', 'futaba', 'morgana', 'yusuke', 'tinynas', 'tinypc']


def ep(s):
    return int(time.mktime(time.strptime(s, '%Y-%m-%d %H:%M')))


# LOAD_UNTIL per window: the scripts start no load step after it and cut a running one at it. t2: T2's load ends by
# 13:05 (REVIEW-PLAN-1 B4); eve and e3: the evening unwind is done by 21:00 (B2). e3 also gates on /var/tmp/e3-go.
LU = {'n1b': ep('2026-10-20 06:50'), 'tue': ep('2026-10-20 15:58'), 't2': ep('2026-10-20 13:05'),
      'eve': ep('2026-10-20 20:30'), 'e3': ep('2026-10-20 20:30'), 'wed': ep('2026-10-21 14:58')}
PY = '/usr/bin/python3 -I'   # -I: /var/tmp is world-writable and would otherwise be on sys.path
RF = f'{PY} /var/tmp/ryuji-floor-1020.py'
MS = f'{PY} /var/tmp/mementos-steps-1020.py'
DS = f'{PY} /var/tmp/disk-soak-1020.py'
LL = f'{PY} /var/tmp/lab-load-1020.py'
RREST, MREST = '/var/tmp/ryuji-profile-restore.sh', '/var/tmp/mementos-steps-restore-fin.sh'
SREST = '/var/tmp/sojiro-floor-restore.sh'
# filled from the coding agents' notes (RACK-TOOLS-NOTES.md, HOST-TOOLS-NOTES.md, sojiro-bmc/NOTES.md)
T1A = (f'{PY} /var/tmp/noise-sweep-1020.py proof t1a1020', '/var/tmp/noise-sweep-restore.sh')
T1B_SHELF = (f'{PY} /var/tmp/noise-sweep-1020.py shelf t1bshelf1020', '/var/tmp/noise-sweep-restore.sh')
T1B_R720 = (f'{PY} /var/tmp/noise-sweep-1020.py r720 t1br7201020', '/var/tmp/noise-sweep-restore.sh')
T1B_NOTCH = (f'{PY} /var/tmp/r720-notch-sweep-1020.py notch t1bnotch1020', '/var/tmp/r720-notch-restore.sh')
SOJ_IDLE = f'{PY} /var/tmp/sojiro-floor-1020.py idle1020 t1b_idle'
SOJ_T3 = f'{PY} /var/tmp/sojiro-floor-1020.py t3a1020 t3a_aba5'
SOJIRO_BACKUP = []          # sojiro's 03:00 backups are cron/ssh, not units: wait-no-backup.sh checks processes instead
PRE = {'n1b': '/bin/sh /var/tmp/wait-no-backup.sh',
       'e3': '/usr/bin/test -e /var/tmp/e3-go'}   # e3-go: written on ryuji only once T1a proves the mic (PLAN, B2)
NIGHTCAP = 'FAN_CAP_SHELF=25 FAN_CAP_R720=24'
WX = 'WATCH_EXTRA=/dev/disk/by-id/wwn-0x5000cca02b3ee724'   # mementos rear boot SSD, watched by the internal soaks

# (host, unit, day, start HH:MM, not-after HH:MM, blockers, command, ExecStopPost, max minutes, LU key, env, what)
B = [
    # N1b, Tuesday 05:35, quiet: sequential reads only, night fan caps (mementos 24%, shelf 25%)
    ('mementos', 'scrub-quiet-soak-n1b-shelf', '2026-10-20', '05:35', '06:15', SOJIRO_BACKUP,
     f'{DS} n1bshelf dataPool seq:60 54', None, 75, 'n1b', NIGHTCAP, 'N1b: shelf sequential reads 60 min, caps on'),
    ('mementos', 'scrub-quiet-soak-n1b-int', '2026-10-20', '05:35', '06:15', SOJIRO_BACKUP,
     f'{DS} n1bint vmPool seq:60 50', None, 75, 'n1b', f'{NIGHTCAP} {WX}', 'N1b: mementos internal sequential reads 60 min'),
    ('sojiro', 'lab-soak-n1b-sojiro', '2026-10-20', '05:35', '06:15', SOJIRO_BACKUP,
     f'{DS} n1bsojiro backupPool seq:60 50', None, 75, 'n1b', '', 'N1b: sojiro backupPool sequential reads 60 min'),
    # T1a, Tuesday 08:00 (Rohit at work; makoto quiet 08:00-13:15 by the makoto session)
    ('mementos', 'mic-r720-proof-1020', '2026-10-20', '08:00', '08:20', [f'{M}:scrub-quiet-soak-n1b.*'],
     T1A[0], T1A[1], 30, 'tue', '', 'T1a mic proof: R720 10/45/10/45/10%, 3-min holds'),
    # T1b: one fan sweep at a time on mementos (local gate check), then ryuji and sojiro idle offsets
    ('mementos', 'mic-shelf-sweep-1020', '2026-10-20', '08:05', '09:00', [f'{M}:mic-r720-proof-1020.*'],
     T1B_SHELF[0], T1B_SHELF[1], 35, 'tue', '', 'T1b shelf 10/20/10/30/10/40/10%, 3-min holds'),
    ('mementos', 'mic-r720-sweep-1020', '2026-10-20', '08:30', '09:30',
     [f'{M}:mic-r720-proof-1020.*', f'{M}:mic-shelf-sweep-1020.*'],
     T1B_R720[0], T1B_R720[1], 50, 'tue', '', 'T1b R720 10-50% against 10%, 3-min holds'),
    ('mementos', 'mic-r720-notch-1020', '2026-10-20', '09:05', '09:35',
     [f'{M}:mic-r720-proof-1020.*', f'{M}:mic-shelf-sweep-1020.*', f'{M}:mic-r720-sweep-1020.*'],
     T1B_NOTCH[0], T1B_NOTCH[1], 30, 'tue', '', 'T1b R720 38-44% in 1% steps, 90 s'),
    ('ryuji', 'ryuji-floor-idleoff-1020', '2026-10-20', '09:40', '10:00', [f'{M}:mic-.*'],
     f'{RF} idleoff1020 t1b_idleoff', RREST, 35, 'tue', '', 'T1b ryuji idle offsets -127/-40/0 against -80'),
    ('sojiro', 'sojiro-floor-idle-1020', '2026-10-20', '10:05', '10:35', [f'{R}:ryuji-floor-idleoff-1020.*', f'{M}:mic-.*'],
     SOJ_IDLE, SREST, 20, 'tue', '', 'T1b sojiro idle offset 0 against -80'),
    # T2, Tuesday 10:30: ryuji alone (nothing else loads the rack)
    ('ryuji', 'ryuji-floor-t2-1020', '2026-10-20', '10:20', '11:15',
     [f'{R}:ryuji-floor-idleoff-1020.*', f'{S}:sojiro-floor-idle-1020.*', f'{M}:mic-.*'],
     f'{RF} t21020 t2_alone', RREST, 185, 't2', '', 'T2: ryuji 2/4/11 workers at -80, one-PSU A/B/A at 22 and 33'),
    # T3a, Tuesday 13:15: the shelf boxes, sojiro and tinynas loaded (makoto's own map runs from 13:15, other session)
    ('morgana', 'lab-load-t3-morgana', '2026-10-20', '13:15', '13:45', [],
     f'{LL} t3morgana /var/tmp/lab-load-profile.json /var/tmp/lab-load-plan-t3.json', None, 140, 'tue', '',
     'T3/T4: morgana 8 threads to 15:25'),
    ('yusuke', 'lab-load-t3-yusuke', '2026-10-20', '13:15', '13:45', [],
     f'{LL} t3yusuke /var/tmp/lab-load-profile.json /var/tmp/lab-load-plan-t3.json', None, 140, 'tue', '',
     'T3/T4: yusuke 16 threads to 15:25'),
    ('futaba', 'lab-load-t3-futaba', '2026-10-20', '13:15', '13:45', [],
     f'{LL} t3futaba /var/tmp/lab-load-profile.json /var/tmp/lab-load-plan-t3.json', None, 140, 'tue', '',
     'T3/T4: futaba 2 threads (nice 19, HA guard) to 15:25'),
    ('tinynas', 'lab-load-t3-tinynas', '2026-10-20', '13:15', '13:45', [],
     f'{LL} t3tinynas /var/tmp/lab-load-profile.json /var/tmp/lab-load-plan-t3.json', None, 140, 'tue', '',
     'T3: tinynas 12 threads + sequential reads to 14:15, then idle (its NVMe is the T4 room proxy, B6)'),
    ('sojiro', 'lab-load-t3-sojiro', '2026-10-20', '13:15', '13:45', [f'{S}:sojiro-floor-idle-1020.*'],
     f'{LL} t3sojiro /var/tmp/lab-load-profile.json /var/tmp/lab-load-plan-t3.json', None, 140, 'tue', '',
     'T3/T4: sojiro 8 threads + random reads to 15:25'),
    ('sojiro', 'sojiro-floor-t3-1020', '2026-10-20', '13:16', '13:45', [f'{S}:sojiro-floor-idle-1020.*'],
     SOJ_T3, SREST, 44, 'tue', '', 'T3a: sojiro 9-min warm, then offset -80/0/-80/-40/-80 under its load, 5-min holds'),
    # T3b and T4: ryuji 44 workers under the guard from 13:51, mementos from 14:05, every pool from 14:25
    ('ryuji', 'ryuji-floor-t4-1020', '2026-10-20', '13:51', '14:15', [f'{R}:ryuji-floor-t2-1020.*'],
     f'{RF} t41020 t4_comb', RREST, 130, 'tue', '', 'T3b/T4: ryuji 44 workers under the guard to 15:25, unwind'),
    ('mementos', 'mementos-steps-t4-1020', '2026-10-20', '14:05', '14:30', [f'{M}:mic-.*', f'{R}:ryuji-floor-t2-1020.*'],
     f'{MS} t4_mem t41020', MREST, 115, 'tue', '', 'T4: mementos idle 10, 24 workers 10, 48 workers 60 min, unwind'),
    ('mementos', 'scrub-quiet-soak-t4-shelf', '2026-10-20', '14:25', '14:50', [f'{M}:mic-.*'],
     f'{DS} t4shelf dataPool rand:60 54', None, 70, 'tue', '', 'T4: shelf random reads 60 min'),
    ('mementos', 'scrub-quiet-soak-t4-int', '2026-10-20', '14:25', '14:50', [f'{M}:mic-.*'],
     f'{DS} t4int vmPool rand:60 50', None, 70, 'tue', WX, 'T4: mementos internal random reads 60 min'),
    ('ryuji', 'ryuji-floor-disk-t4-1020', '2026-10-20', '14:25', '14:50', [f'{R}:ryuji-floor-t2-1020.*'],
     f'{DS} t4ryuji computePool rand:60 50', None, 70, 'tue', '', 'T4: ryuji computePool random reads 60 min'),
    # tinypc's 20-thread block moved to Wednesday: it heats the bedroom the Dreo reference sits in (B6)
    # E, Tuesday evening (Rohit home from ~17:00): medium only, quiet by 21:00
    ('ryuji', 'ryuji-floor-e1-1020', '2026-10-20', '16:35', '17:05', [f'{R}:ryuji-floor-(t4|disk).*'],
     f'{RF} e11020 e1_mix', RREST, 70, 'eve', '', 'E1 everyday mix: ryuji 11 workers 40 min'),
    ('mementos', 'mementos-steps-e1-1020', '2026-10-20', '16:35', '17:05', [f'{M}:(mementos-steps-t4|scrub-quiet-soak-t4).*'],
     f'{MS} e1_mix e11020', MREST, 70, 'eve', 'NIGHT_FAN_CAP=30', 'E1 everyday mix: mementos 12 workers 40 min'),
    ('mementos', 'scrub-quiet-soak-e1-shelf', '2026-10-20', '16:45', '17:15', [f'{M}:scrub-quiet-soak-t4.*'],
     f'{DS} e1shelf dataPool seq:35 54', None, 45, 'eve', 'FAN_CAP_SHELF=30 FAN_CAP_R720=30',
     'E1 everyday mix: shelf sequential reads 35 min, medium caps'),
    # E2 (bursts) dropped: E3 could not start in time behind it (B2); W3 covers hunting
    ('ryuji', 'ryuji-floor-e3-1020', '2026-10-20', '17:40', '18:00',
     [f'{R}:ryuji-floor-e1.*', f'{M}:mementos-steps-e1.*', f'{M}:scrub-quiet-soak-e1.*'],
     f'{RF} e31020 e3_light', RREST, 180, 'e3', '', 'E3: ryuji -80/-60/-80 at 4 and 11 workers, 20-min holds, 15-min warm at 11'),
]
# backstops on every loaded host: (unit, day, HH:MM)
STOPS = [('lab-loadoff-1020-tue', '2026-10-20', '16:00'), ('lab-loadoff-1020-tue2', '2026-10-20', '16:30'),
         ('lab-loadoff-1020-eve', '2026-10-20', '21:00'), ('lab-loadoff-1020-wed', '2026-10-21', '15:00'),
         ('lab-loadoff-1020-wed2', '2026-10-21', '15:30')]
# PDU cut (dining room) on the loaded PDU hosts: (unit, day, start, minutes, {host: unit globs})
CUTS = [('pdu-cut-t4', '2026-10-20', '13:10', 170,
         {'mementos': 'mementos-steps-t4* scrub-quiet-soak-t4*', 'sojiro': 'lab-load-t3* sojiro-floor-t3*'}),
        ('pdu-cut-e', '2026-10-20', '16:33', 265, {'mementos': 'mementos-steps-e1* scrub-quiet-soak-e1*'})]
# PDU-side load units bind to their host's cut: none runs without it, and a cut that dies takes them down (B1)
BIND = {u: 'pdu-cut-t4' for u in ('mementos-steps-t4-1020', 'scrub-quiet-soak-t4-shelf', 'scrub-quiet-soak-t4-int',
                                  'lab-load-t3-sojiro', 'sojiro-floor-t3-1020')}
BIND.update({u: 'pdu-cut-e' for u in ('mementos-steps-e1-1020', 'scrub-quiet-soak-e1-shelf')})
# living-room cut on ryuji: (unit, day, start, minutes, unit globs)
LRCUTS = [('lr-cut-t4', '2026-10-20', '13:10', 170, 'ryuji-floor-t4* ryuji-floor-disk-t4*')]
# ryuji room feed for ryuji-floor's room gate: (unit, day, start, hours)
FEEDS = [('room-feed-1020', '2026-10-20', '07:30', 33)]   # ends Wed 16:30, inside the 17:00 cleanup

# restore -> the unit family it guards: restore-guard.sh skips a restore while another unit of the family runs
FAM = {T1A[1]: 'mic-.*', T1B_NOTCH[1]: 'mic-.*', RREST: 'ryuji-floor-.*', SREST: 'sojiro-floor-.*', MREST: 'mementos-steps-.*'}
# Wednesday's rows live in wed-rows.py (built separately, 10-20); it extends B, CUTS, LRCUTS, BIND, LU, PRE in place
_wed = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wed-rows.py')
if os.environ.get('NO_WED'):   # retired 10-20 06:45: Wednesday is installed, and a Tuesday-only set would let units-prune remove it
    sys.exit('NO_WED is retired: Wednesday is installed; installing a Tuesday-only set would disarm it')
if os.path.exists(_wed):
    exec(open(_wed).read())


def timer(unit, day, hm, what):
    return (f'[Unit]\nDescription=lab thermal run 10-20: start {unit} {day} {hm}\n\n[Timer]\nOnCalendar={day} {hm}:00 '
            f'America/New_York\nAccuracySec=1s\nPersistent=false\nUnit={unit}.service\n\n[Install]\n'
            f'WantedBy=timers.target\n')


def main(days):
    rows = []
    for host in HOSTS:
        os.makedirs(f'{OUT}/{host}', exist_ok=True)
        for f in os.listdir(f'{OUT}/{host}'):
            os.remove(f'{OUT}/{host}/{f}')
    for host, unit, day, hm, na, blk, cmd, post, mx, lu, env, what in B:
        if days and day not in days:
            continue
        gate = ' '.join([str(ep(f'{day} {na}'))] + [f"'{b}'" for b in blk])
        envl = f'Environment=LOAD_UNTIL={LU[lu]}' + (f' {env}' if env else '') + '\n'
        bind = f'BindsTo={BIND[unit]}.service\nAfter={BIND[unit]}.service\n' if unit in BIND else ''
        svc = (f'[Unit]\nDescription=lab thermal run 10-20: {what}\nAfter=network-online.target\n{bind}\n[Service]\n'
               f'Type=simple\nTimeoutStartSec=infinity\n{envl}'
               f'ExecStartPre={PY} /var/tmp/fin-gate-1020.py {gate}\n'
               + (f'ExecStartPre={PRE[lu]}\n' if lu in PRE else '') + f'ExecStart={cmd}\n'
               + (f'ExecStopPost=/bin/sh /var/tmp/restore-guard.sh %n {FAM[post]} {post}\nTimeoutStopSec=180\n' if post else '') + f'RuntimeMaxSec={mx * 60}\n')
        open(f'{OUT}/{host}/{unit}.service', 'w').write(svc)
        open(f'{OUT}/{host}/{unit}.timer', 'w').write(timer(unit, day, hm, what))
        rows.append((day, hm, host, unit, na, what))
    for unit, day, hm in STOPS:
        if days and day not in days:
            continue
        for host in HOSTS:
            open(f'{OUT}/{host}/{unit}.service', 'w').write(
                f'[Unit]\nDescription=lab thermal run 10-20: load-off backstop {day} {hm}\n\n[Service]\nType=oneshot\nTimeoutStartSec=600\n'
                f'ExecStart=/bin/sh /var/tmp/lab-loadoff-1020.sh\n')
            open(f'{OUT}/{host}/{unit}.timer', 'w').write(timer(unit, day, hm, 'backstop'))
        rows.append((day, hm, 'all', unit, '', 'backstop: stop test units, kill stress-ng/fio, production control on'))
    for unit, day, hm, mins, per in CUTS:
        if days and day not in days:
            continue
        for host, units in per.items():
            open(f'{OUT}/{host}/{unit}.service', 'w').write(
                f'[Unit]\nDescription=lab thermal run 10-20: PDU cut at 14.0 A\n\n[Service]\nType=simple\n'
                f'Environment=LIMIT=140 LOG=/var/tmp/{unit}.log "UNITS={units}"\nExecStart=/bin/bash /var/tmp/pdu-cut.sh\n'
                f'RuntimeMaxSec={mins * 60}\n')
            open(f'{OUT}/{host}/{unit}.timer', 'w').write(timer(unit, day, hm, 'pdu cut'))
        rows.append((day, hm, '+'.join(per), unit, '', f'PDU cut at 14.0 A for {mins} min'))
    for unit, day, hm, mins, units in LRCUTS:
        if days and day not in days:
            continue
        end = ep(f'{day} {hm}') + mins * 60   # lr-cut exits cleanly at END; RuntimeMaxSec is 5 min later, as a backstop
        open(f'{OUT}/ryuji/{unit}.service', 'w').write(
            f'[Unit]\nDescription=lab thermal run 10-20: living-room estimate cut at 11 A\n\n[Service]\nType=simple\n'
            f'Environment=LIMIT=11.0 LOG=/var/tmp/{unit}.csv "UNITS={units}" END={end}\nExecStart={PY} /var/tmp/lr-cut-1020.py\n'
            f'RuntimeMaxSec={mins * 60 + 300}\n')
        open(f'{OUT}/ryuji/{unit}.timer', 'w').write(timer(unit, day, hm, 'living-room cut'))
        rows.append((day, hm, 'ryuji', unit, '', f'living-room estimate cut at 11 A for {mins} min'))
    for unit, day, hm, hours in FEEDS:
        if days and day not in days:
            continue
        open(f'{OUT}/ryuji/{unit}.service', 'w').write(
            f'[Unit]\nDescription=lab thermal run 10-20: room feed (R720 inlet) for ryuji-floor\n\n[Service]\nType=simple\n'
            f'Environment=LIMIT=30 LOG=/var/tmp/{unit}.csv\nExecStart=/bin/bash /var/tmp/room-feed-local.sh\n'
            f'RuntimeMaxSec={hours * 3600}\n')
        open(f'{OUT}/ryuji/{unit}.timer', 'w').write(timer(unit, day, hm, 'room feed'))
        rows.append((day, hm, 'ryuji', unit, '', f'room feed for {hours} h (kills stress-ng at inlet > 30C twice)'))
    for r in sorted(rows):
        print(f'{r[0]} {r[1]}  {r[2]:<14} {r[3]:<28} {("not after " + r[4]) if r[4] else "":<16} {r[5]}')


if __name__ == '__main__':
    main(sys.argv[1:])
