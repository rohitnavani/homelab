#!/usr/bin/env python3
# fin-gate (2026-10-13; 2026-10-20 local check): ExecStartPre of each block of a thermal run. Waits while any block it
# depends on is still running, on this host or another one, and refuses to start once past its not-after time, so a late
# or overrunning block can never push load into a quiet window.
# usage: fin-gate.py <not_after_epoch> [<instance>:<unit regex> ...]
#   e.g. fin-gate.py 1792000000 '10.0.0.9:ryuji-floor-t2.*' '10.0.0.10:mementos-steps-t4.*'
#   A blocker on another host is busy while Prometheus (futaba) shows node_systemd_unit_state{state="active"} == 1 for
#   a matching service on that instance; Prometheus unreachable or the host down (up == 0 or absent) counts as busy
#   (keeps waiting until the not-after time).
#   2026-10-20: a blocker on THIS host is checked with systemctl directly (active services only), so two units waiting
#   2026-10-20 04:20: a unit that is starting (waiting in its own gate, activating) or stopping (running its
#   ExecStopPost, deactivating) counts as busy too, here and through Prometheus (REVIEW-PLAN-1 B5).
#   for the same predecessor on one host cannot both start inside Prometheus's scrape lag.
# The unit needs TimeoutStartSec=infinity (ExecStartPre otherwise times out after 90 s). Exit 0 = go, 1 = refused.
import json, re, subprocess, sys, time, urllib.parse, urllib.request

NOT_AFTER = float(sys.argv[1])
BLOCKERS = [a.split(':', 1) for a in sys.argv[2:]]
PROM = 'http://10.0.0.3:9090/api/v1/query?query='
try:
    LOCAL = set(subprocess.run(['hostname', '-I'], capture_output=True, text=True, timeout=10).stdout.split())
except Exception:
    LOCAL = set()


def local_active(rx):
    r = subprocess.run(['systemctl', 'list-units', '--type=service', '--state=active,activating,deactivating', '--no-legend', '--plain'],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError('systemctl failed')
    names = [l.split()[0] for l in r.stdout.splitlines() if l.strip()]
    return [n for n in names if re.fullmatch(rx, n) and n.endswith('.service')]


def busy():
    out = []
    for inst, rx in BLOCKERS:
        if inst in LOCAL:
            try:
                out += [f'{inst}:{n} (local)' for n in local_active(rx)]
            except Exception as e:
                out.append(f'{inst}:{rx} (systemctl: {type(e).__name__})')
            continue
        # services only: a one-shot timer stays active ("elapsed") after it fires (2026-10-14)
        q = f'node_systemd_unit_state{{state=~"active|activating|deactivating",instance="{inst}",name=~"{rx}",name=~".+[.]service"}} == 1'
        # 2026-10-20: a blocker host that is down (no fresh scrape) counts as busy, as the brief asks
        # 2026-10-20 04:35: and so does one whose systemd collector failed (its unit series vanish; REVIEW-PLAN-1 minor 16)
        qu = (f'up{{job="node",instance="{inst}"}} == 1 and on(instance) '
              f'node_scrape_collector_success{{collector="systemd",instance="{inst}"}} == 1')
        try:
            with urllib.request.urlopen(PROM + urllib.parse.quote(qu), timeout=15) as r:
                if not json.load(r)['data']['result']:
                    out.append(f'{inst}:{rx} (host down or no systemd data)')
                    continue
            with urllib.request.urlopen(PROM + urllib.parse.quote(q), timeout=15) as r:
                res = json.load(r)['data']['result']
        except Exception as e:   # unreachable or bad answer: treat as busy
            out.append(f'{inst}:{rx} (Prometheus: {type(e).__name__})')
            continue
        out += [f'{inst}:{x["metric"]["name"]}' for x in res]
    return out


last = None
while True:
    now = time.time()
    if now > NOT_AFTER:
        print(f'past not-after {time.strftime("%F %T", time.localtime(NOT_AFTER))}: refusing to start', flush=True)
        sys.exit(1)
    b = busy()
    if not b:
        print(f'go at {time.strftime("%T")}', flush=True)
        sys.exit(0)
    if b != last:
        print(f'{time.strftime("%T")} waiting for: {", ".join(b)}', flush=True)
        last = b
    time.sleep(30)
