#!/usr/bin/env python3
# ac-check-prom (2026-10-07): is the room flat? 10-min means of the room proxies from Prometheus on futaba (mementos
# iDRAC inlet, tinynas nvme0 and SYSTIN, sojiro MB_TEMP1, makoto MB Temp) and the rack current, plus each proxy's
# spread (max - min of the 10-min means) per rolling hour. A healthy AC: every proxy within about 1C per hour, no
# hourly sawtooth. usage: ac-check-prom.py "YYYY-MM-DD HH:MM" ["YYYY-MM-DD HH:MM" | now]
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
def ts(s): return time.time() if s == 'now' else datetime.datetime.strptime(s, '%Y-%m-%d %H:%M').timestamp()
start, end = ts(sys.argv[1]), ts(sys.argv[2] if len(sys.argv) > 2 else 'now')
series = {}
for k, q in Q.items():
    u = P + '?' + urllib.parse.urlencode({'query': f'avg_over_time(({q})[10m:30s])', 'start': start, 'end': end, 'step': 600})
    r = json.load(urllib.request.urlopen(u, timeout=60))['data']['result']
    series[k] = {int(float(t)): float(v) for t, v in r[0]['values']} if r else {}
times = sorted(set(t for s in series.values() for t in s))
print('time        ' + ''.join(f'{k:>9}' for k in Q))
for t in times:
    print(datetime.datetime.fromtimestamp(t).strftime('%m-%d %H:%M ') + ''.join(
        f'{series[k][t]:9.2f}' if t in series[k] else f'{"-":>9}' for k in Q))
print('\nrolling 1 h spread (max - min of 10-min means), worst hour per proxy:')
for k in Q:
    vals = [(t, series[k][t]) for t in times if t in series[k]]
    worst = (0.0, None)
    for i in range(len(vals)):
        win = [v for t, v in vals if vals[i][0] <= t < vals[i][0] + 3600]
        if len(win) >= 5:
            sp = max(win) - min(win)
            if sp > worst[0]: worst = (sp, vals[i][0])
    when = datetime.datetime.fromtimestamp(worst[1]).strftime('%H:%M') if worst[1] else '-'
    allv = [v for _, v in vals]
    print(f'  {k:<9} spread {worst[0]:4.2f} (hour from {when}); range {min(allv) if allv else 0:.2f}-{max(allv) if allv else 0:.2f}')
