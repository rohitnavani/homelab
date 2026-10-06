#!/usr/bin/env python3
# baseline_compare: idle baselines per host for time windows (local HH:MM-HH:MM, today): labmon means per host,
# room (makoto data/room.csv), rack PDU amps (data/pdu.csv). usage: baseline_compare.py 02:20-03:00 14:30-15:30
import json, os, subprocess, sys, time, datetime as dt
day = dt.date.today().isoformat()
wins = []
for w in sys.argv[1:]:
    a, b = w.split('-')
    wins.append((w, time.mktime(time.strptime(f'{day} {a}', '%Y-%m-%d %H:%M')), time.mktime(time.strptime(f'{day} {b}', '%Y-%m-%d %H:%M'))))
KEYS = {
    'mementos': [('CPU0', 'ipmi:Temp'), ('CPU1', 'ipmi:Temp#1'), ('inlet', 'ipmi:Inlet Temp'), ('exhaust', 'ipmi:Exhaust Temp'),
                 ('fan1 rpm', 'ipmi:Fan1'), ('W', 'ipmi:power_w')],
    'ryuji': [('CPU0', 'ipmi:CPU0_TEMP'), ('CPU1', 'ipmi:CPU1_TEMP'), ('SIO1', 'ipmi:SIO Temp 1'), ('PCH', 'ipmi:PCH_TEMP'),
              ('CPU fan', 'ipmi:CPU0_FAN'), ('sys fan', 'ipmi:SYS_FAN1'), ('W', 'ipmi:power_w')],
    'sojiro': [('CPU', 'ipmi:CPU0_TEMP'), ('MB1', 'ipmi:MB_TEMP1'), ('CPU fan', 'ipmi:CPU0_FAN'), ('sys fan', 'ipmi:SYS_FAN1')],
    'tinynas': [('Tctl', 'hwmon2:k10temp/Tctl'), ('SYSTIN', 'hwmon5:nct6799/SYSTIN'), ('NVMe', 'hwmon1:nvme/Composite'),
                ('fan2 rpm', 'hwmon5:nct6799/fan2'), ('pkg W', 'rapl:intel-rapl:0:package-0_w')],
    'makoto': [('CPU', 'ipmi:CPU1 Temp'), ('MB', 'ipmi:MB Temp'), ('FAN1', 'ipmi:FAN1'), ('FAN4', 'ipmi:FAN4')],
}
def lines(h):
    if h == os.uname().nodename:
        return open('/var/tmp/labmon.jsonl').read().splitlines()
    return subprocess.run(['ssh', '-o', 'BatchMode=yes', h, 'cat /var/tmp/labmon.jsonl'], capture_output=True, text=True,
                          timeout=90).stdout.splitlines()
hdr = f'{"":<22}' + ''.join(f'{w:>14}' for w, _, _ in wins)
print(hdr)
for h, keys in KEYS.items():
    rows = []
    for l in lines(h):
        try:
            rows.append(json.loads(l))
        except ValueError:
            pass
    for lab, k in keys:
        out = f'{h + " " + lab:<22}'
        for _, a, b in wins:
            v = [r[k] for r in rows if a <= r['t'] < b and isinstance(r.get(k), (int, float))]
            out += f'{sum(v) / len(v):14.1f}' if v else f'{"-":>14}'
        print(out)
def series(path, conv):
    out = []
    for l in open(path):
        p = l.strip().split(',')
        try:
            out.append(conv(p))
        except (ValueError, IndexError):
            pass
    return out
D = os.environ.get('DATA', os.path.expanduser('~/fan-control-data'))   # room.csv (lab-inlet-guard) and pdu.csv live here
room = series(f'{D}/room.csv', lambda p: (int(p[0]), int(p[2])))
pdu = series(f'{D}/pdu.csv', lambda p: (time.mktime(time.strptime(p[0], '%Y-%m-%d %H:%M:%S')), float(p[1])))
for lab, s in (('room (mementos inlet)', room), ('rack PDU A', pdu)):
    out = f'{lab:<22}'
    for _, a, b in wins:
        v = [x for t, x in s if a <= t < b]
        out += f'{sum(v) / len(v):14.2f}' if v else f'{"-":>14}'
    print(out)
