# wed-rows (2026-10-20, REVIEW-PLAN-1 B7): Wednesday 10-21's chain. Not run on its own: make-units.py exec()s this file
# in its own namespace just before `def timer(`, so it extends B, CUTS, LRCUTS, BIND, LU and PRE in place (FAM already
# holds RREST and MREST, the only restores used here). Notes, timeline and what is still missing: WED-NOTES.md.
# Windows (PLAN.md): loud 07:00-15:00, load off 14:58, backstops 15:00 / 15:30 (make-units STOPS), no controller change
# after 10:00 (every row here runs the deployed controllers or none). Rules kept:
#  - gates: each block waits for the one before it on the same host (local systemctl check); cross-host blockers only on
#    ryuji, mementos and sojiro. Never a tinynas unit as a remote blocker (10.0.0.5 exports no unit states).
#  - RuntimeMaxSec = the plan's minutes + 10.
#  - W1 only with /var/tmp/w1-ok on the host (Rohit's adapter / 50 ft cord check); default: W1 refuses at 08:00.
#  - every PDU-side load binds to its host's pdu-cut-w*, and every ryuji load to its lr-cut-w*, so none runs without
#    its cut and a cut that ends takes its loads down.
#  - tinypc's 20-thread block runs in W0, hours before the rack-only phase and the 15:30 baseline (the Dreo reference
#    sits in tinypc's bedroom, B6).
#  - rows whose plan, plan entry or profile does not exist yet are not written (a note goes to stderr instead):
#    the rack-only phase (plan w2_rack in ryuji-floor.py and mementos-steps.py), tinypc's W3 (a "tinypc" entry in
#    lab-load/lab-load-plan-w1.json) and the makoto rows (a "makoto" profile and plan entries). WED-NOTES.md lists
#    each one's exact steps.
import json, re

D = '2026-10-21'
_SD = os.path.dirname(os.path.abspath(_wed))
_LLD = os.path.join(_SD, 'lab-load')


def _has_plan(tool, name):
    """True if the tool's source defines plan `name` (a "'name':" key line); read only, nothing is imported."""
    try:
        return re.search(rf"^\s*'{re.escape(name)}'\s*:", open(os.path.join(_SD, tool)).read(), re.M) is not None
    except OSError:
        return False


def _json_has(fname, key):
    """True if lab-load/<fname> has an entry for host `key` (top level or under "hosts")."""
    try:
        d = json.load(open(os.path.join(_LLD, fname)))
    except (OSError, ValueError):
        return False
    if isinstance(d, dict) and isinstance(d.get('hosts'), dict):
        d = d['hosts']
    return isinstance(d, dict) and key in d


def _skip(what, why):
    print(f'wed-rows: {what} NOT written: {why} (see WED-NOTES.md)', file=sys.stderr)


# LOAD_UNTIL per window (the tools start no load step after it and cut a running one at it)
LU.update({'w0': ep(f'{D} 08:00'), 'w1': ep(f'{D} 10:00'), 'w1mk': ep(f'{D} 10:00'), 'w2': ep(f'{D} 13:05'),
           'w2mk': ep(f'{D} 12:40'), 'wr': ep(f'{D} 14:10'), 'w3': ep(f'{D} 14:58')})
# W1: only with Rohit's adapter/cord check, flagged per host. makoto (B4): no wake or request in mirror-voice's journal
# for 10 min (waits up to 30 min, then refuses). No "$" or "%" anywhere: systemd would expand them.
W1OK = '/usr/bin/test -e /var/tmp/w1-ok'
JGATE = ("/usr/bin/timeout 1800 /bin/sh -c 'while journalctl --user-unit=mirror-voice.service --since -10min --no-pager "
         "-o cat | grep -q -E \"wake [(]|heard \"; do sleep 60; done'")
PRE.update({'w1': W1OK, 'w1mk': f'{W1OK}\nExecStartPre={JGATE}', 'w2mk': JGATE})

LLW1 = '/var/tmp/lab-load-profile.json /var/tmp/lab-load-plan-w1.json'
TN = IP['tinynas']     # local blocker on tinynas only (fin-gate checks it with systemctl there)
RACK = _has_plan('ryuji-floor.py', 'w2_rack') and _has_plan('mementos-steps.py', 'w2_rack')

# (host, unit, day, start, not-after, blockers, command, ExecStopPost, max minutes, LU key, env, what)
W = [
    # W0 07:00-08:00: random reads on every pool, CPUs idle (disk-soak lines from HOST-TOOLS-NOTES.md, 55 min)
    ('mementos', 'lab-soak-w0-shelf', D, '07:00', '07:20', [], f'{DS} w0shelf dataPool rand:55 54', None, 65, 'w0', '',
     'W0: shelf random reads 55 min, CPUs idle'),
    ('mementos', 'lab-soak-w0-int', D, '07:00', '07:20', [], f'{DS} w0int vmPool rand:55 50', None, 65, 'w0', WX,
     'W0: mementos internal random reads 55 min, CPUs idle'),
    ('ryuji', 'lab-soak-w0-ryuji', D, '07:00', '07:20', [], f'{DS} w0ryuji computePool rand:55 50', None, 65, 'w0', '',
     'W0: ryuji computePool random reads 55 min, CPUs idle'),
    ('sojiro', 'lab-soak-w0-sojiro', D, '07:00', '07:20', [], f'{DS} w0sojiro backupPool rand:55 50', None, 65, 'w0', '',
     'W0: sojiro backupPool random reads 55 min, CPUs idle'),
    ('tinynas', 'lab-soak-w0-tinynas', D, '07:00', '07:20', [], f'{DS} w0tinynas homePool rand:55', None, 65, 'w0', '',
     'W0: tinynas homePool random reads 55 min'),
    ('tinynas', 'lab-soak-w0-tinynas-nvme', D, '07:00', '07:20', [], f'{DS} w0tinynasnvme nvmePool rand:55', None, 65,
     'w0', '', 'W0: tinynas nvmePool random reads 55 min'),
    # W1 08:00-10:00 (only with /var/tmp/w1-ok): the 2 h soak. ryuji 33 / mementos 36 under their controllers, load cut
    # at 10:00, then the plans' 25-min unwind (back to idle within 25 min); shelf random reads; half load elsewhere
    ('ryuji', 'ryuji-floor-w1-1021', D, '08:00', '08:20', [f'{R}:lab-soak-w0-ryuji.*'], f'{RF} w11021 fin_soak', RREST,
     160, 'w1', '', 'W1 2 h soak: ryuji 33 workers under the guard to 10:00, unwind'),
    ('mementos', 'mementos-steps-w1-1021', D, '08:00', '08:20', [f'{M}:lab-soak-w0-.*'], f'{MS} fin_soak w11021', MREST,
     160, 'w1', '', 'W1 2 h soak: mementos 36 workers to 10:00, unwind'),
    ('mementos', 'lab-soak-w1-shelf', D, '08:00', '08:20', [f'{M}:lab-soak-w0-.*'], f'{DS} w1shelf dataPool rand:120 54',
     None, 130, 'w1', '', 'W1: shelf random reads to 10:00'),
    ('sojiro', 'lab-load-w1-sojiro', D, '08:00', '08:20', [f'{S}:lab-soak-w0-sojiro.*'], f'{LL} w1sojiro {LLW1}', None,
     130, 'w1', '', 'W1: sojiro sequential backupPool reads to 10:00, CPU idle (93C at 4 threads on the top plate, T3)'),
    ('tinynas', 'lab-load-w1-tinynas', D, '08:00', '08:20', [f'{TN}:lab-soak-w0-tinynas.*'], f'{LL} w1tinynas {LLW1}',
     None, 130, 'w1', '', 'W1: tinynas 6 threads + sequential homePool reads to 10:00'),
] + [(h, f'lab-load-w1-{h}', D, '08:00', '08:20', [], f'{LL} w1{h} {LLW1}', None, 130, 'w1', '',
      f'W1: {h} half load ({n} threads) to 10:00') for h, n in (('yusuke', 8), ('futaba', 1))] + [   # morgana dropped 10-20 21:15: 50C skin stop ends any load in <1 min (T34)
    # W2 10:15 (10:30 after a W1): validation of the deployed controllers, each box after its own W1. Shelf boxes,
    # sojiro and tinynas idle. ryuji fin_val 145 min (2/4/11/22/33/44 workers, 15-20 min each); mementos fin_val
    # 150 min (6-48 workers, 15-20 min each, then a full-load onset from idle)
    ('ryuji', 'ryuji-floor-w2-1021', D, '10:15', '10:55', [f'{R}:ryuji-floor-w1.*'], f'{RF} w21021 fin_val', RREST, 155,
     'w2', '', 'W2 validation: ryuji 2/4/11/22/33/44 workers under the guard, unwind'),
    ('mementos', 'mementos-steps-w2-1021', D, '10:15', '10:55', [f'{M}:mementos-steps-w1.*', f'{M}:lab-soak-w1.*'],
     f'{MS} fin_val w21021', MREST, 160, 'w2', '', 'W2 validation: mementos 6-48 workers, full-load onset from idle'),
    # W3 13:00 (after the rack-only phase if armed, else after W2): irregular bursts on both, under their controllers
    ('ryuji', 'ryuji-floor-w3-1021', D, '13:00', '14:25',
     [f'{R}:ryuji-floor-w2.*', f'{R}:ryuji-floor-wr.*', f'{M}:mementos-steps-wr.*'], f'{RF} w31021 fin_burst', RREST,
     65, 'w3', '', 'W3 bursts: ryuji 0-44 workers, irregular, under the guard, unwind'),
    ('mementos', 'mementos-steps-w3-1021', D, '13:00', '14:25',
     [f'{M}:mementos-steps-w2.*', f'{M}:mementos-steps-wr.*', f'{M}:lab-soak-wr.*', f'{R}:ryuji-floor-wr.*'],
     f'{MS} fin_burst w31021', MREST, 65, 'w3', '', 'W3 bursts: mementos 0-48 workers, irregular, unwind'),
]
CW = [('pdu-cut-w0', D, '06:55', 95, {'mementos': 'lab-soak-w0-shelf* lab-soak-w0-int*', 'sojiro': 'lab-soak-w0-sojiro*'}),
      ('pdu-cut-w1', D, '07:55', 190, {'mementos': 'mementos-steps-w1-1021* lab-soak-w1-shelf*',
                                       'sojiro': 'lab-load-w1-sojiro*'}),
      ('pdu-cut-w2', D, '10:10', 210, {'mementos': 'mementos-steps-w2-1021*'}),
      ('pdu-cut-w3', D, '12:55', 125, {'mementos': 'mementos-steps-w3-1021*'})]
LW = [('lr-cut-w0', D, '06:55', 95, 'lab-soak-w0-ryuji*'), ('lr-cut-w1', D, '07:55', 190, 'ryuji-floor-w1-1021*'),
      ('lr-cut-w2', D, '10:10', 210, 'ryuji-floor-w2-1021*'), ('lr-cut-w3', D, '12:55', 125, 'ryuji-floor-w3-1021*')]
BW = {'lab-soak-w0-shelf': 'pdu-cut-w0', 'lab-soak-w0-int': 'pdu-cut-w0', 'lab-soak-w0-sojiro': 'pdu-cut-w0',
      'mementos-steps-w1-1021': 'pdu-cut-w1', 'lab-soak-w1-shelf': 'pdu-cut-w1', 'lab-load-w1-sojiro': 'pdu-cut-w1',
      'mementos-steps-w2-1021': 'pdu-cut-w2', 'mementos-steps-w3-1021': 'pdu-cut-w3',
      'lab-soak-w0-ryuji': 'lr-cut-w0', 'ryuji-floor-w1-1021': 'lr-cut-w1', 'ryuji-floor-w2-1021': 'lr-cut-w2',
      'ryuji-floor-w3-1021': 'lr-cut-w3'}

# Rack-only phase at the end of W2 (B6): mementos 48 + ryuji 44 + shelf random reads for 40 min, shelf boxes and sojiro
# idle; both servers start together (each waits for both W2 units). Needs plan w2_rack in both tools (WED-NOTES.md).
if RACK:
    W += [('ryuji', 'ryuji-floor-wr-1021', D, '12:40', '13:30', [f'{R}:ryuji-floor-w2.*', f'{M}:mementos-steps-w2.*'],
           f'{RF} wr1021 w2_rack', RREST, 73, 'wr', '',
           'W2 end, rack only: ryuji 44 workers 40 min under the guard; shelf boxes and sojiro idle'),
          ('mementos', 'mementos-steps-wr-1021', D, '12:40', '13:30', [f'{M}:mementos-steps-w2.*', f'{R}:ryuji-floor-w2.*'],
           f'{MS} w2_rack wr1021', MREST, 73, 'wr', '', 'W2 end, rack only: mementos 48 workers 40 min'),
          ('mementos', 'lab-soak-wr-shelf', D, '12:40', '13:30', [f'{M}:mementos-steps-w2.*', f'{R}:ryuji-floor-w2.*'],
           f'{DS} wrshelf dataPool rand:40 54', None, 50, 'wr', '', 'W2 end, rack only: shelf random reads 40 min')]
    CW += [('pdu-cut-wr', D, '12:35', 130, {'mementos': 'mementos-steps-wr-1021* lab-soak-wr-shelf*'})]
    LW += [('lr-cut-wr', D, '12:35', 130, 'ryuji-floor-wr-1021*')]
    BW.update({'mementos-steps-wr-1021': 'pdu-cut-wr', 'lab-soak-wr-shelf': 'pdu-cut-wr', 'ryuji-floor-wr-1021': 'lr-cut-wr'})
else:
    _skip('rack-only phase (ryuji-floor-wr-1021, mementos-steps-wr-1021, lab-soak-wr-shelf)',
          'plan w2_rack missing in ryuji-floor.py and/or mementos-steps.py')

# tinypc's 20-thread CPU block (moved from Tuesday's T4): in W0, 07:00-07:55 (disk reads only, CPUs idle; tinypc is off
# the PDU and out of the rack), so the bedroom Dreo has hours to settle before the rack-only phase and the 15:30
# baseline. After the rack-only phase it got 0-10 min before its 14:00 end (REVIEW-WED-1, 10-20 06:35).
if _json_has('lab-load-plan-w1.json', 'tinypc'):
    W += [('tinypc', 'lab-load-w0-tinypc', D, '07:00', '07:20', [],
           f'{LL} w0tinypc {LLW1}', None, 65, 'w0', '', 'W0: tinypc 20 threads, CPU only, 55 min (bedroom; disks-only window)')]
else:
    _skip('tinypc W0 (lab-load-w0-tinypc)', 'no "tinypc" entry in lab-load/lab-load-plan-w1.json')

# makoto (after the Tue 16:00 handoff; makoto-fan is production, validate it, don't change it). B4: nice 19, at most
# 4 of 8 threads, start only after 10 quiet minutes in mirror-voice's journal. Installed by hand (install-units and
# lab-loadoff never touch makoto): only RuntimeMaxSec and LOAD_UNTIL stop these.
if _json_has('lab-load-profile.json', 'makoto') and _json_has('lab-load-plan-w1.json', 'makoto') \
        and _json_has('lab-load-plan-wmk.json', 'makoto'):
    os.makedirs(os.path.join(OUT, 'makoto'), exist_ok=True)
    for _f in os.listdir(os.path.join(OUT, 'makoto')):
        if _f.startswith('makoto-fan-test-lt1020-'):
            os.remove(os.path.join(OUT, 'makoto', _f))
    W += [('makoto', 'makoto-fan-test-lt1020-w1', D, '08:00', '08:20', [], f'{LL} w1makoto {LLW1}', None, 130, 'w1mk', '',
           'W1: makoto 2 workers nice 19 to 10:00 (w1-ok and mirror-voice journal gate)'),
          ('makoto', 'makoto-fan-test-lt1020-w2', D, '10:30', '11:00', [],
           f'{LL} w2makoto /var/tmp/lab-load-profile.json /var/tmp/lab-load-plan-wmk.json', None, 90, 'w2mk', '',
           'W2: makoto-fan validation, 2 then 4 workers nice 19, 30 min each (journal gate)')]
    # 8 workers needs mirror-voice's OK (B4: at least 4 of 8 threads free), so it is not armed:
    # ('makoto', 'makoto-fan-test-lt1020-w2full', D, '11:45', '12:15', [f"{IP['makoto']}:makoto-fan-test-lt1020-w2.*"],
    #  f'{LL} w2fmakoto /var/tmp/lab-load-profile.json /var/tmp/lab-load-plan-wmkfull.json', None, 40, 'w2mk', '',
    #  'W2: makoto 8 workers 30 min (only with mirror-voice OK)'),
else:
    _skip('makoto rows (makoto-fan-test-lt1020-w1, -w2)',
          'no "makoto" entry in lab-load-profile.json, lab-load-plan-w1.json and/or lab-load-plan-wmk.json')

B += W
CUTS += CW
LRCUTS += LW
BIND.update(BW)
