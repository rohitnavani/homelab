#!/usr/bin/env python3
# silence (2026-10-08): Alertmanager silences for Thursday's loud window, when the tests stop the fan controllers on
# purpose (fixed-fan map: fan-watchdog; noise sweep: md1200-fan and fan-watchdog; ryuji offsets: ryuji-fan-guard).
# usage: silence.py create "YYYY-MM-DD HH:MM" "YYYY-MM-DD HH:MM" | list | expire <id>
import datetime, json, sys, urllib.request
AM = 'http://10.0.0.3:9093/api/v2'
def iso(s):
    return datetime.datetime.strptime(s, '%Y-%m-%d %H:%M').astimezone().astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
def call(method, path, body=None):
    r = urllib.request.Request(AM + path, method=method, data=json.dumps(body).encode() if body else None,
                               headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(r, timeout=20) as resp:
        t = resp.read().decode()
        return json.loads(t) if t else None
if sys.argv[1] == 'create':
    start, end = iso(sys.argv[2]), iso(sys.argv[3])
    for name, extra in (('FanControllerStale', [{'name': 'controller', 'value': 'fan-watchdog|md1200-fan|ryuji-fan-guard', 'isRegex': True, 'isEqual': True}]),
                        ('ThermalMetricsMissing', []), ('R720FansInIdracAuto', [])):
        body = {'matchers': [{'name': 'alertname', 'value': name, 'isRegex': False, 'isEqual': True}] + extra,
                'startsAt': start, 'endsAt': end, 'createdBy': 'thermal-retest-ryuji-makoto (Claude)',
                'comment': 'fan tests stop the controllers on purpose (fan-control/testing)'}
        print(name, call('POST', '/silences', body))
elif sys.argv[1] == 'list':
    for s in call('GET', '/silences'):
        if s['status']['state'] != 'expired':
            print(s['id'], s['status']['state'], s['startsAt'], s['endsAt'], [m['value'] for m in s['matchers']], s['createdBy'])
elif sys.argv[1] == 'expire':
    print(call('DELETE', f'/silence/{sys.argv[2]}'))
