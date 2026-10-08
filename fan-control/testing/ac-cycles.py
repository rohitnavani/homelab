#!/usr/bin/env python3
# ac-cycles (2026-10-07): room proxies at 1-min steps from futaba Prometheus; per-period stats and turning points of the
# smoothed tinynas NVMe and the mementos inlet. usage: ac-cycles.py "YYYY-MM-DD HH:MM" [end|now]
import datetime, json, sys, time, urllib.parse, urllib.request
P = 'http://10.0.0.3:9090/api/v1/query_range'
Q = {
    'inlet': 'lab_r720_temp_celsius{sensor="inlet"}',
    'nvme0': 'node_hwmon_temp_celsius{chip="nvme_nvme0",sensor="temp1"} * on(instance) group_left(nodename) node_uname_info{nodename="TinyNAS"}',
    'systin': 'node_hwmon_temp_celsius{chip="platform_nct6775_656",sensor="temp1"} * on(instance) group_left(nodename) node_uname_info{nodename="TinyNAS"}',
    'sojiroMB': 'node_ipmi_temperature_celsius{sensor="MB_TEMP1"} * on(instance) group_left(nodename) node_uname_info{nodename="sojiro"}',
    'makotoMB': 'node_ipmi_temperature_celsius{sensor="MB Temp"} * on(instance) group_left(nodename) node_uname_info{nodename="makoto"}',
    'rackA': 'cyberpower_pdu_bank_load_deciamps{bank="1"} / 10',
}
ts = lambda s: time.time() if s == 'now' else datetime.datetime.strptime(s, '%Y-%m-%d %H:%M').timestamp()
start, end = ts(sys.argv[1]), ts(sys.argv[2] if len(sys.argv) > 2 else 'now')
S = {}
for k, q in Q.items():
    vals = {}
    t0 = start
    while t0 < end:                       # 11,000-point limit per query: fetch in 6 h chunks
        t1 = min(end, t0 + 6 * 3600)
        u = P + '?' + urllib.parse.urlencode({'query': q, 'start': t0, 'end': t1, 'step': 60})
        r = json.load(urllib.request.urlopen(u, timeout=60))['data']['result']
        if r:
            vals.update({int(float(t)): float(v) for t, v in r[0]['values']})
        t0 = t1 + 60
    S[k] = vals
hm = lambda t: datetime.datetime.fromtimestamp(t).strftime('%H:%M')
day = datetime.datetime.fromtimestamp(start).strftime('%Y-%m-%d')
# periods of 2026-10-07 (the AC fault, the repair, the 70F setpoint): edit for another day
PER = [('fault (AC broken)', '00:00', '10:30'), ('repaired, 71F', '11:30', '18:15'), ('room step', '18:15', '19:14'),
       ('70F setpoint', '19:14', None)]
def pct(xs, p):
    xs = sorted(xs); return xs[min(len(xs) - 1, int(p / 100 * len(xs)))] if xs else float('nan')
print(f"{'period':<20} {'span':<12} " + ' '.join(f'{k:>21}' for k in Q))
print(f"{'':<20} {'':<12} " + ' '.join(f"{'mean  p5-p95 (swing)':>21}" for k in Q))
for name, a, b in PER:
    ta = ts(f'{day} {a}'); tb = ts(f'{day} {b}') if b else end
    if ta >= end: continue
    row = f'{name:<20} {a}-{b or hm(end):<6} '
    for k in Q:
        xs = [v for t, v in S[k].items() if ta <= t < tb]
        row += f"{sum(xs)/len(xs):7.2f} {pct(xs,5):5.1f}-{pct(xs,95):<5.1f}({pct(xs,95)-pct(xs,5):3.1f})" if xs else f"{'-':>21}"
    print(row)
# turning points: 9-min centred mean of the NVMe (1C steps, dithering gives sub-degree detail) and the inlet
for k, hyst in (('nvme0', 0.35), ('inlet', 0.5)):
    ks = sorted(S[k]); v = [S[k][t] for t in ks]
    sm = [sum(v[max(0, i-4):i+5]) / len(v[max(0, i-4):i+5]) for i in range(len(v))]
    tps, mode, ext_i = [], None, 0
    for i in range(1, len(sm)):
        if mode in (None, 'up'):
            if sm[i] > sm[ext_i] or mode is None and sm[i] >= sm[ext_i]: ext_i = i if mode == 'up' or sm[i] > sm[ext_i] else ext_i
            if mode is None and sm[i] < sm[ext_i] - hyst: mode = 'down'; tps.append(('peak', ext_i)); ext_i = i
            elif mode == 'up' and sm[i] < sm[ext_i] - hyst: tps.append(('peak', ext_i)); mode = 'down'; ext_i = i
            elif mode is None and sm[i] > sm[0] + hyst: mode = 'up'; ext_i = i
        else:
            if sm[i] < sm[ext_i]: ext_i = i
            if sm[i] > sm[ext_i] + hyst: tps.append(('trough', ext_i)); mode = 'up'; ext_i = i
    print(f'\n{k} turning points (9-min mean, hysteresis {hyst}C):')
    print('  ' + '  '.join(f"{'P' if kind=='peak' else 't'} {hm(ks[i])} {sm[i]:.1f}" for kind, i in tps))
    print(f'  now {hm(ks[-1])} {sm[-1]:.1f} (raw {v[-1]:.0f})')
