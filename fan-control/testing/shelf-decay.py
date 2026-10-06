#!/usr/bin/env python3
# shelf-decay: does a single _shutup hold without re-sending? (2026-10-06)
# Stops md1200-fan, sends `_shutup PCT` once, then only watches: SES fan speed every 4s,
# temps (drives via smartctl, BP/SIM/EXP via the read-only _temp_rd) every 30s, and anything the
# EMM prints on its own. If the fans leave the expected speed for two reads in a row (a takeover),
# that's logged with the temps at that moment and _shutup is re-sent at once, so a loud spell
# lasts seconds. Runs MINUTES, then starts md1200-fan again (the unit's ExecStopPost does too).
# Usage: shelf-decay.py <pct> <minutes> <label> [max takeovers before giving up]
import os, re, subprocess, sys, time, serial

PORT, SG = '/dev/ttyUSB0', '/dev/sg39'
pct, minutes, label = int(sys.argv[1]), float(sys.argv[2]), sys.argv[3]
max_takeovers = int(sys.argv[4]) if len(sys.argv) > 4 else 3
LOG = f'/var/tmp/shelf-decay-{label}.log'
PROMPT = re.compile(r'(BlueDress|RedDress)\.[0-9.]+\s*>\s*$')
SENS_RE = r'((?:BP_|SIM|EXP)\d\[\d\]) = (\d+)c'
assert 10 <= pct <= 100
out = open(LOG, 'a', buffering=1)

def note(msg):
    out.write(f'{time.strftime("%F %T")} {msg}\n')

def run(*a):
    return subprocess.run(a, capture_output=True, text=True).stdout

s = None

def cmd(c, secs=1.0):
    pending = s.read(4096).decode(errors='replace')
    if re.sub(r'(BlueDress|RedDress)[\w.]*\s*>|\s', '', pending):
        note('EMM said on its own: ' + ' | '.join(l.strip() for l in pending.splitlines() if l.strip()))
    s.write((c + '\r').encode())
    buf, end = b'', time.time() + secs
    while time.time() < end:
        d = s.read(4096)
        if d:
            buf += d
            if PROMPT.search(buf.decode(errors='replace')):
                break
    return buf.decode(errors='replace')

def shelf_disks():
    o = run('zpool', 'list', '-vHP', 'dataPool')
    devs = []
    for line in o.splitlines()[1:]:
        if line and not line[0].isspace():
            break
        devs += re.findall(r'(/dev/\S+)', line)
    return sorted({re.sub(r'-part\d+$', '', d) for d in devs})

def temps():
    dr = []
    for d in shelf_disks():
        m = re.search(r'Current Drive Temperature:\s+(\d+)', run('smartctl', '-n', 'standby', '-A', d))
        if m:
            dr.append(int(m.group(1)))
    raw = cmd('_temp_rd', secs=3)
    v = {}
    for k, t in re.findall(SENS_RE, raw):
        g = re.match(r'[A-Z]+', k).group(0)
        v[g] = max(v.get(g, 0), int(t))
    return f"drive={max(dr) if dr else '?'} BP={v.get('BP', '?')} SIM={v.get('SIM', '?')} EXP={v.get('EXP', '?')}"

def rpm():
    r = [int(x) for x in re.findall(r'Actual speed=(\d+) rpm', run('sg_ses', '-p', '2', SG))][-4:]
    return round(sum(r) / len(r)) if r else None

expected = 2330 + (pct - 10) * 96
# never share the serial port with the overnight experiment: wait (up to 40 min) for it to finish
for _ in range(240):
    if subprocess.run(['systemctl', 'is-active', '--quiet', 'shelf-exp3']).returncode != 0:
        break
    time.sleep(10)
else:
    note('shelf-exp3 still running after 40 min; not starting')
    sys.exit(1)
subprocess.run(['systemctl', 'stop', 'md1200-fan'])
s = serial.Serial(PORT, 38400, timeout=0.1)
try:
    reply = cmd('_shutup %d' % pct)
    note(f'{label}: sent _shutup {pct} once (echo {"ok" if f"_shutup {pct}" in reply else "MISSING"}); '
         f'expect about {expected} rpm; watching {minutes:g} min. {temps()}')
    start, next_temp, off, takeovers, sent_at = time.time(), time.time() + 30, 0, 0, time.time()
    while time.time() - start < minutes * 60:
        r = rpm()
        if r is not None and time.time() - sent_at > 20 and abs(r - expected) > max(300, 0.15 * expected):
            off += 1
            if off >= 2:
                takeovers += 1
                note(f'TAKEOVER {takeovers}: fans at {r} rpm (expected ~{expected}), '
                     f'{(time.time() - sent_at) / 60:.1f} min after the last send. {temps()}')
                cmd('_shutup %d' % pct)
                sent_at, off = time.time(), 0
                note(f're-sent _shutup {pct}')
                if takeovers >= max_takeovers:
                    note('giving up after repeated takeovers')
                    break
        else:
            off = 0
        if time.time() >= next_temp:
            next_temp = time.time() + 30
            note(f'rpm {r}  {temps()}')
        time.sleep(4)
    note(f'{label}: done, {takeovers} takeovers in {(time.time() - start) / 60:.1f} min')
finally:
    s.close()
    subprocess.run(['systemctl', 'start', 'md1200-fan'])
