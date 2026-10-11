#!/usr/bin/env python3
# lab-watch (2026-10-10): the 24 h monitoring run's watcher. Every minute it reads the lab's thermal state from
# Prometheus and Alertmanager on futaba, appends one CSV row (room proxies, every box's temps and fans, rack current,
# CPU busy and pool read rates), and logs events: INFO for controller level changes and pool activity, WARN for
# anything outside the limits below (edge-triggered: one line when it starts, one when it clears). Read-only: it
# never touches a host. usage: lab-watch.py <data dir> <stop "YYYY-MM-DD HH:MM">
import csv, datetime, json, os, sys, time, urllib.parse, urllib.request

PROM, AM = 'http://10.0.0.3:9090/api/v1/query', 'http://10.0.0.3:9093/api/v2/alerts'
DATA, STOP = sys.argv[1], datetime.datetime.strptime(sys.argv[2], '%Y-%m-%d %H:%M').timestamp()
CSV, EVENTS = os.path.join(DATA, 'watch.csv'), os.path.join(DATA, 'watch-events.log')
H = {'10.0.0.10': 'mementos', '10.0.0.9': 'ryuji', '10.0.0.8': 'sojiro', '10.0.0.6': 'makoto', '10.0.0.5': 'tinynas',
     '10.0.0.3': 'futaba', '10.0.0.2': 'tinypc', '10.0.0.7': 'morgana'}

# column -> PromQL returning one series (first value used); missing data -> empty cell
Q = {
    'inlet': 'lab_r720_temp_celsius{sensor="inlet"}',
    'nas_nvme0': 'node_hwmon_temp_celsius{instance="10.0.0.5",chip="nvme_nvme0",sensor="temp1"}',
    'nas_systin': 'node_hwmon_temp_celsius{instance="10.0.0.5",chip="platform_nct6775_656",sensor="temp1"}',
    'sojiro_mb': 'node_ipmi_temperature_celsius{instance="10.0.0.8",sensor="MB_TEMP1"}',
    'makoto_mb': 'node_ipmi_temperature_celsius{instance="10.0.0.6",sensor="MB Temp"}',
    'rack_a': 'cyberpower_pdu_bank_load_deciamps{bank="1"} / 10',
    'r720_pct': 'lab_r720_fan_percent', 'r720_auto': 'lab_r720_fan_auto',
    'r720_cpu': 'lab_r720_temp_celsius{sensor="cpu"}', 'r720_exh': 'lab_r720_temp_celsius{sensor="exhaust"}',
    'r720_hdd': 'lab_r720_temp_celsius{sensor="hdd"}', 'r720_ssd': 'lab_r720_temp_celsius{sensor="ssd"}',
    'r720_dimm': 'lab_r720_temp_celsius{sensor="dimm"}',
    'shelf_pct': 'lab_md1200_fan_percent', 'shelf_rpm': 'lab_md1200_fan_rpm',
    'shelf_drive': 'lab_md1200_temp_celsius{sensor="drive"}', 'shelf_bp': 'lab_md1200_temp_celsius{sensor="backplane"}',
    'shelf_sim': 'lab_md1200_temp_celsius{sensor="sim"}', 'shelf_exp': 'lab_md1200_temp_celsius{sensor="expander"}',
    'shelf_takeovers': 'lab_md1200_takeovers', 'shelf_primary': 'lab_md1200_primary',
    'ryuji_off': 'lab_ryuji_fan_offset', 'ryuji_sio1': 'lab_ryuji_temp_celsius{sensor="sio1"}',
    'ryuji_cpu': 'lab_ryuji_temp_celsius{sensor="cpu"}', 'ryuji_vr': 'lab_ryuji_temp_celsius{sensor="vr"}',
    'ryuji_dimm': 'lab_ryuji_temp_celsius{sensor="dimm"}',
    'ryuji_cpufan': 'max(node_ipmi_speed_rpm{instance="10.0.0.9",sensor=~"CPU._FAN"})',
    'ryuji_sysfan': 'max(node_ipmi_speed_rpm{instance="10.0.0.9",sensor=~"SYS_FAN."})',
    'ryuji_minfan': 'min(node_ipmi_speed_rpm{instance="10.0.0.9",sensor=~"CPU._FAN|SYS_FAN[1-4]"})',
    'ryuji_pch': 'node_ipmi_temperature_celsius{instance="10.0.0.9",sensor="PCH_TEMP"}',
    'sojiro_cpu': 'node_ipmi_temperature_celsius{instance="10.0.0.8",sensor="CPU0_TEMP"}',
    'sojiro_cpufan': 'node_ipmi_speed_rpm{instance="10.0.0.8",sensor="CPU0_FAN"}',
    'sojiro_sysfan': 'node_ipmi_speed_rpm{instance="10.0.0.8",sensor="SYS_FAN1"}',
    'makoto_cpu': 'node_ipmi_temperature_celsius{instance="10.0.0.6",sensor="CPU1 Temp"}',
    'makoto_fan1': 'node_ipmi_speed_rpm{instance="10.0.0.6",sensor="FAN1"}',
    'makoto_fan4': 'node_ipmi_speed_rpm{instance="10.0.0.6",sensor="FAN4"}',
    'nas_tctl': 'node_hwmon_temp_celsius{instance="10.0.0.5",chip="pci0000:00_0000:00:18_3",sensor="temp1"}',
    'nas_fan2': 'node_hwmon_fan_rpm{instance="10.0.0.5",sensor="fan2"}',
    'futaba_cpu': 'max(node_hwmon_temp_celsius{instance="10.0.0.3",chip=~"platform_coretemp.*"})',
    'tinypc_cpu': 'max(node_hwmon_temp_celsius{instance="10.0.0.2",chip=~"platform_coretemp.*"})',
    'age_fw': 'lab_controller_state_age_seconds{controller="fan-watchdog"}',
    'age_shelf': 'lab_controller_state_age_seconds{controller="md1200-fan"}',
    'age_guard': 'lab_controller_state_age_seconds{controller="ryuji-fan-guard"}',
}
for ip, h in (('10.0.0.10', 'mementos'), ('10.0.0.9', 'ryuji'), ('10.0.0.8', 'sojiro'), ('10.0.0.6', 'makoto'),
              ('10.0.0.5', 'tinynas'), ('10.0.0.2', 'tinypc')):
    Q[f'{h}_busy'] = f'100 * (1 - avg(rate(node_cpu_seconds_total{{instance="{ip}",mode="idle"}}[2m])))'
# Disk activity (MB/s) from the block devices, since ZFS's pool read counters miss scrub I/O. Device names as of
# 10-10: mementos shelf (dataPool) sdaa-sdal, internal 10K disks (vmPool) sda and sdd-sdz; sojiro backupPool sdb-sde;
# tinynas homePool sda-sdh.
for col, ip, dev, kind in (('shelf_rd', '10.0.0.10', 'sda[a-l]', 'read'), ('shelf_wr', '10.0.0.10', 'sda[a-l]', 'written'),
                           ('vm_rd', '10.0.0.10', 'sd(a|[d-z])', 'read'), ('nas_rd', '10.0.0.5', 'sd[a-h]', 'read'),
                           ('nas_wr', '10.0.0.5', 'sd[a-h]', 'written'), ('sojiro_wr', '10.0.0.8', 'sd[b-e]', 'written'),
                           ('sojiro_rd', '10.0.0.8', 'sd[b-e]', 'read')):
    Q[col] = f'sum(rate(node_disk_{kind}_bytes_total{{instance="{ip}",device=~"{dev}"}}[2m])) / 1e6'

def window(ts):
    # Rohit, 10-10: quiet until 12:00, medium 12:00-22:00 Saturday, quiet overnight until Sunday 08:00
    d = datetime.datetime.fromtimestamp(ts)
    return 'medium' if d.weekday() == 5 and 12 <= d.hour < 22 else 'quiet'

# WARN rules: name -> function(row, window) -> True when out of limits
def v(r, k):
    try:
        return float(r[k])
    except (TypeError, ValueError, KeyError):
        return None
def ge(k, lim):
    return lambda r, w: v(r, k) is not None and v(r, k) >= lim
def le(k, lim):
    return lambda r, w: v(r, k) is not None and v(r, k) <= lim
RULES = {
    'room inlet >= 27C': ge('inlet', 27),
    'R720 in iDRAC auto': ge('r720_auto', 1),
    'R720 fans above the window cap': lambda r, w: v(r, 'r720_pct') is not None and v(r, 'r720_pct') >= (25 if w == 'quiet' else 35),
    'R720 CPU >= 82C': ge('r720_cpu', 82), 'R720 exhaust >= 55C': ge('r720_exh', 55),
    'R720 HDD >= 46C': ge('r720_hdd', 46), 'R720 SSD >= 55C': ge('r720_ssd', 55), 'R720 DIMM >= 70C': ge('r720_dimm', 70),
    'shelf fans >= 22%': ge('shelf_pct', 22), 'shelf drive >= 53C': ge('shelf_drive', 53),
    'shelf backplane >= 48C': ge('shelf_bp', 48), 'shelf SIM >= 58C': ge('shelf_sim', 58),
    'shelf expander >= 88C': ge('shelf_exp', 88), 'shelf EMM not primary': le('shelf_primary', 0),
    # ryuji-fan-guard v2.3 (10-10 16:18): -40 (BUSY) is its normal level under a sustained light load
    'ryuji guard above -40': lambda r, w: v(r, 'ryuji_off') is not None and v(r, 'ryuji_off') not in (-80, -40),
    'ryuji SIO1 >= 78C': ge('ryuji_sio1', 78), 'ryuji CPU >= 75C': ge('ryuji_cpu', 75),
    'ryuji VR >= 85C': ge('ryuji_vr', 85), 'ryuji DIMM >= 70C': ge('ryuji_dimm', 70),
    'ryuji fan < 600 rpm': le('ryuji_minfan', 599),
    'sojiro CPU >= 75C': ge('sojiro_cpu', 75), 'sojiro board >= 70C': ge('sojiro_mb', 70),
    'sojiro CPU fan < 1000 rpm': le('sojiro_cpufan', 999), 'sojiro sys fan < 400 rpm': le('sojiro_sysfan', 399),
    'makoto CPU >= 70C': ge('makoto_cpu', 70), 'makoto FAN1 < 1000 rpm': le('makoto_fan1', 999),
    'tinynas Tctl >= 75C': ge('nas_tctl', 75), 'tinynas NVMe >= 45C': ge('nas_nvme0', 45),
    'fan-watchdog state stale': ge('age_fw', 180), 'md1200-fan state stale': ge('age_shelf', 180),
    'ryuji guard state stale': ge('age_guard', 180), 'rack >= 8.0 A': ge('rack_a', 8.0),
}
CHANGES = ('r720_pct', 'shelf_pct', 'ryuji_off')       # INFO on every change
ACTIVE = (('shelf_rd', 50, 'shelf disk reads'), ('shelf_wr', 50, 'shelf disk writes'), ('vm_rd', 50, 'R720 internal disk reads'),
          ('nas_rd', 50, 'tinynas disk reads'), ('nas_wr', 50, 'tinynas disk writes'), ('sojiro_wr', 20, 'sojiro disk writes'),
          ('sojiro_rd', 50, 'sojiro disk reads'))

def prom(q):
    u = PROM + '?' + urllib.parse.urlencode({'query': q})
    r = json.load(urllib.request.urlopen(u, timeout=20))['data']['result']
    return r

def event(level, msg):
    line = f'{time.strftime("%F %T")} {level} {msg}'
    with open(EVENTS, 'a') as f:
        f.write(line + '\n')
    print(line, flush=True)

cols = ['time', 'window'] + list(Q)
new = not os.path.exists(CSV)
out = open(CSV, 'a', newline='', buffering=1)
w = csv.writer(out)
if new:
    w.writerow(cols)
active, last, down, alerts, fails, busy_pool = {}, {}, set(), set(), 0, {}
event('INFO', f'lab-watch started (until {sys.argv[2]})')
while time.time() < STOP:
    t0 = time.time()
    row = {'time': time.strftime('%F %T'), 'window': window(t0)}
    try:
        for k, q in Q.items():
            r = prom(q)
            row[k] = round(float(r[0]['value'][1]), 2) if r else ''
        ups = {H.get(x['metric']['instance'], x['metric']['instance']): x['value'][1]
               for x in prom('up{job="node"}')}
        fired = {f"{a['labels'].get('alertname')}:{H.get(a['labels'].get('instance', '').split(':')[0], a['labels'].get('instance', ''))}"
                 for a in json.load(urllib.request.urlopen(AM + '?active=true&silenced=false&inhibited=false', timeout=20))}
        fails = 0
    except Exception as ex:
        fails += 1
        if fails in (3, 30):
            event('WARN', f'cannot read Prometheus/Alertmanager ({fails} tries): {ex!r}')
        time.sleep(60)
        continue
    w.writerow([row.get(c, '') for c in cols])
    for name, f in RULES.items():
        bad = f(row, row['window'])
        if bad and not active.get(name):
            event('WARN', f'{name} (' + ', '.join(f'{k}={row[k]}' for k in row if k in name.lower() or k.split('_')[0] in name.lower())[:200] + ')')
        elif not bad and active.get(name):
            event('INFO', f'cleared: {name}')
        active[name] = bad
    for k in CHANGES:
        if row[k] != '' and last.get(k) not in (None, '') and row[k] != last[k]:
            event('INFO', f'{k} {last[k]} -> {row[k]}')
    for k, lim, label in ACTIVE:
        on = v(row, k) is not None and v(row, k) >= lim
        if on != busy_pool.get(k, False):
            event('INFO', f'{label} {"started" if on else "ended"} ({row[k]} MB/s)')
        busy_pool[k] = on
    now_down = {h for h, x in ups.items() if x == '0'}
    for h in now_down - down:
        event('WARN', f'host down: {h}')
    for h in down - now_down:
        event('INFO', f'host up: {h}')
    down = now_down
    for a in fired - alerts:
        event('WARN', f'alert firing: {a}')
    for a in alerts - fired:
        event('INFO', f'alert resolved: {a}')
    alerts = fired
    last = dict(row)
    time.sleep(max(1, 60 - (time.time() - t0)))
event('INFO', 'lab-watch finished')
