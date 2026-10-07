#!/usr/bin/env python3
# window_compare (2026-10-07): like testing/baseline_compare.py, but windows carry their date, so tonight's baselines
# can be compared with 10-06's. labmon means per host and window, plus the room (lab-inlet-guard room.csv) and the
# rack PDU. Host logs: the live /var/tmp/labmon.jsonl over ssh, plus copies of an earlier run's logs in
# $OLD/hosts/<host>/labmon.jsonl. Room and PDU CSVs from $OLD and $DATA (room.csv from lab-inlet-guard, pdu.csv).
# usage: window_compare.py "2026-10-06 02:20-03:00" "2026-10-07 00:40-01:40" ...
import json, os, subprocess, sys, time

wins = []
for w in sys.argv[1:]:
    day, rng = w.split()
    a, b = rng.split('-')
    t = lambda hm: time.mktime(time.strptime(f'{day} {hm}', '%Y-%m-%d %H:%M'))
    wins.append((w[5:], t(a), t(b)))
KEYS = {
    'mementos': [('CPU0', 'ipmi:Temp'), ('CPU1', 'ipmi:Temp#1'), ('inlet', 'ipmi:Inlet Temp'), ('exhaust', 'ipmi:Exhaust Temp'),
                 ('fan1 rpm', 'ipmi:Fan1'), ('W (DCMI)', 'ipmi:power_w'), ('busy %', 'cpu_busy_pct')],
    'ryuji': [('CPU0', 'ipmi:CPU0_TEMP'), ('CPU1', 'ipmi:CPU1_TEMP'), ('SIO1', 'ipmi:SIO Temp 1'), ('PCH', 'ipmi:PCH_TEMP'),
              ('CPU fan', 'ipmi:CPU0_FAN'), ('sys fan', 'ipmi:SYS_FAN1'), ('W (DCMI)', 'ipmi:power_w')],
    'sojiro': [('CPU', 'ipmi:CPU0_TEMP'), ('MB1', 'ipmi:MB_TEMP1'), ('CPU fan', 'ipmi:CPU0_FAN'), ('sys fan', 'ipmi:SYS_FAN1')],
    'tinynas': [('Tctl', 'hwmon2:k10temp/Tctl'), ('SYSTIN', 'hwmon5:nct6799/SYSTIN'), ('NVMe (h0)', 'hwmon0:nvme/Composite'),
                ('NVMe (h1)', 'hwmon1:nvme/Composite'), ('pkg W', 'rapl:intel-rapl:0:package-0_w'), ('busy %', 'cpu_busy_pct')],
    'makoto': [('CPU', 'ipmi:CPU1 Temp'), ('MB', 'ipmi:MB Temp'), ('card side', 'ipmi:Card Side Temp'), ('FAN1', 'ipmi:FAN1')],
}
OLD = os.path.expanduser(os.environ.get('OLD', '~/fan-control-data-previous'))   # 10-07: ~/lab-thermal-2026-10-06/data
NEW = os.path.expanduser(os.environ.get('DATA', '~/fan-control-data'))           # 10-07: ~/lab-thermal-2026-10-07/data


def lines(h):
    out = []
    old = f'{OLD}/hosts/{h}/labmon.jsonl'
    if os.path.exists(old):
        out += open(old).read().splitlines()
    if h == os.uname().nodename:
        out += open('/var/tmp/labmon.jsonl').read().splitlines()
    else:
        out += subprocess.run(['ssh', '-o', 'BatchMode=yes', h, 'cat /var/tmp/labmon.jsonl'], capture_output=True,
                              text=True, timeout=120).stdout.splitlines()
    return out


def fmt(v):
    return f'{sum(v) / len(v):>9.1f} ({len(v):>3})' if v else f'{"-":>15}'


print(f'{"":<22}' + ''.join(f'{w:>15}' for w, _, _ in wins))
for h, keys in KEYS.items():
    rows, seen = [], set()
    for l in lines(h):
        try:
            r = json.loads(l)
        except ValueError:
            continue
        if r.get('t') in seen:
            continue        # the 10-06 copy and the live file overlap
        seen.add(r.get('t'))
        rows.append(r)
    print(h)
    for lab, k in keys:
        cells = []
        for _, a, b in wins:
            v = [r[k] for r in rows if a <= r['t'] < b and isinstance(r.get(k), (int, float))]
            cells.append(fmt(v))
        print(f'  {lab:<20}' + ''.join(cells))


def series(paths, parse):
    s = []
    for p in paths:
        try:
            for l in open(p):
                try:
                    s.append(parse(l.strip().split(',')))
                except (ValueError, IndexError):
                    pass
        except OSError:
            pass
    return s


room = series([f'{OLD}/room.csv', f'{NEW}/room.csv'], lambda p: (int(p[0]), int(p[2])))
pdu = series([f'{OLD}/pdu.csv', f'{NEW}/pdu.csv'], lambda p: (time.mktime(time.strptime(p[0], '%Y-%m-%d %H:%M:%S')), float(p[1])))
print('room / power')
for lab, s in (('room (inlet guard)', room), ('rack PDU A', pdu)):
    print(f'  {lab:<20}' + ''.join(fmt([v for t, v in s if a <= t < b]) for _, a, b in wins))
