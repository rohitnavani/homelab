#!/usr/bin/env python3
# ac-verify: is the room really cooling? Compare several independent room-tracking sensors on different machines
# (10-min means from each host's labmon log), plus the PDU current (lab heat output must stay steady for the
# comparison to mean anything). A sensor only counts if its own box's load and fans were steady.
# usage: ac-verify.py [start HH:MM local, default 00:00] [bucket minutes, default 10]
import json, os, subprocess, sys, time, datetime as dt

start = sys.argv[1] if len(sys.argv) > 1 else '00:00'
bucket = int(sys.argv[2]) if len(sys.argv) > 2 else 10
day = dt.date.today().isoformat()
t0 = time.mktime(time.strptime(f'{day} {start}', '%Y-%m-%d %H:%M'))
SENS = {  # host: [(label, key)]
    'mementos': [('mem_inlet', 'ipmi:Inlet Temp'), ('mem_busy', 'cpu_busy_pct')],
    'sojiro': [('soj_MB1', 'ipmi:MB_TEMP1'), ('soj_pch', 'hwmon0:pch_haswell/temp1'), ('soj_sysfan', 'ipmi:SYS_FAN1'),
               ('soj_pkgW', 'rapl:intel-rapl:0:package-0_w')],
    'tinynas': [('tny_SYSTIN', 'hwmon5:nct6799/SYSTIN'), ('tny_AUX4', 'hwmon5:nct6799/AUXTIN4'),
                ('tny_nvme', 'hwmon1:nvme/Composite'), ('tny_pkgW', 'rapl:intel-rapl:0:package-0_w')],
    'makoto': [('mak_MB', 'ipmi:MB Temp'), ('mak_card', 'ipmi:Card Side Temp'), ('mak_pkgW', 'rapl:intel-rapl:0:package-0_w')],
}

def lines(host):
    if host == os.uname().nodename:
        return open('/var/tmp/labmon.jsonl').read().splitlines()
    return subprocess.run(['ssh', '-o', 'BatchMode=yes', host, 'cat /var/tmp/labmon.jsonl'],
                          capture_output=True, text=True, timeout=60).stdout.splitlines()

series = {}
for host, sens in SENS.items():
    for l in lines(host):
        try:
            r = json.loads(l)
        except ValueError:
            continue
        if r['t'] < t0:
            continue
        b = int((r['t'] - t0) // (bucket * 60))
        for lab, key in sens:
            v = r.get(key)
            if isinstance(v, (int, float)):
                series.setdefault(lab, {}).setdefault(b, []).append(v)
pdu = {}
try:
    for l in open(os.path.join(os.environ.get('DATA', os.path.expanduser('~/fan-control-data')), 'pdu.csv')):
        p = l.strip().split(',')
        try:
            t = time.mktime(time.strptime(p[0], '%Y-%m-%d %H:%M:%S')); a = float(p[1])
        except (ValueError, IndexError):
            continue
        if t >= t0:
            pdu.setdefault(int((t - t0) // (bucket * 60)), []).append(a)
except OSError:
    pass
series['pdu_A'] = pdu
labs = [lab for s in SENS.values() for lab, _ in s if lab in series] + ['pdu_A']
nb = max(max(v) for v in series.values() if v) + 1
print('time  ' + ' '.join(f'{l:>10}' for l in labs))
for b in range(nb):
    ts = time.strftime('%H:%M', time.localtime(t0 + b * bucket * 60))
    row = []
    for l in labs:
        v = series.get(l, {}).get(b)
        row.append(f'{sum(v) / len(v):10.1f}' if v else ' ' * 10)
    print(ts + ' ' + ' '.join(row))
