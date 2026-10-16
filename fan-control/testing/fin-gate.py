#!/usr/bin/env python3
# fin-gate (2026-10-13): ExecStartPre of each block of the final rack run. Waits while any block it depends on is still
# running, on this host or another one, and refuses to start once past its not-after time, so a late or overrunning
# block can never push load into a quiet window.
# usage: fin-gate.py <not_after_epoch> [<instance>:<unit regex> ...]
#   e.g. fin-gate.py 1792000000 '10.0.0.9:ryuji-floor-fin.*' '10.0.0.10:mementos-steps-fin.*'
#   A blocker is busy while Prometheus (futaba) shows node_systemd_unit_state{state="active"} == 1 for a matching
#   unit on that instance. Prometheus unreachable counts as busy (keeps waiting until the not-after time).
# The unit needs TimeoutStartSec=infinity (ExecStartPre otherwise times out after 90 s). Exit 0 = go, 1 = refused.
import json, sys, time, urllib.parse, urllib.request

NOT_AFTER = float(sys.argv[1])
BLOCKERS = [a.split(':', 1) for a in sys.argv[2:]]
PROM = 'http://10.0.0.3:9090/api/v1/query?query='


def busy():
    out = []
    for inst, rx in BLOCKERS:
        # 2026-10-14: services only. A unit's one-shot timer stays active ("elapsed") after it fires, and the old query
        # matched it too, so a finished block looked busy forever (mementos-steps-fin-steps waited at 12:25 for
        # ryuji-floor-fin-light.timer).
        q = f'node_systemd_unit_state{{state="active",instance="{inst}",name=~"{rx}",name=~".+[.]service"}} == 1'
        try:
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
