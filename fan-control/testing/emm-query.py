#!/usr/bin/env python3
# emm-query: read-only EMM console diagnostics (the same queries the Unraid md12xx plugin's
# diagnostics send: _who, _ver, devils, ps_status l/r, fanlog), while holding the shelf at its
# current fan % so nothing gets loud. md1200-fan is stopped for the duration and started again.
# Usage: emm-query.py <hold %> <output file>
import re, subprocess, sys, time, serial

PORT = '/dev/ttyUSB0'
PROMPT = re.compile(r'(BlueDress|RedDress)\.[0-9.]+\s*>\s*$')
hold, outpath = int(sys.argv[1]), sys.argv[2]
assert 10 <= hold <= 100

def query(s, cmd, limit=12):
    # drain, send with CR-only framing, read until the prompt comes back
    end = time.time() + 0.3
    while time.time() < end:
        s.read(4096)
    s.write((cmd + '\r').encode())
    out, end = b'', time.time() + limit
    while time.time() < end:
        d = s.read(4096)
        if d:
            out += d
            if PROMPT.search(out.decode(errors='replace')):
                break
    return out.decode(errors='replace')

subprocess.run(['systemctl', 'stop', 'md1200-fan'])
try:
    with serial.Serial(PORT, 38400, timeout=0.2) as s, open(outpath, 'w') as out:
        for cmd in ['_who', '_ver', 'devils', 'ps_status l', 'ps_status r', 'fanlog']:
            query(s, '_shutup %d' % hold, limit=2)
            reply = query(s, cmd)
            out.write(f'===== {time.strftime("%F %T")} {cmd}\n{reply}\n')
            out.flush()
            if cmd == '_who':
                # same fingerprint the plugin requires before it sends anything else
                marks = [r'Host\s+Links\s+UP\s*:', r'Expansion\s+Links\s+UP\s*:', r'Drive\(s\)\s*:', r'EMM\s*\(', r'Power\s+Supplies\s*:']
                if sum(bool(re.search(m, reply, re.I)) for m in marks) < 4:
                    out.write('===== _who reply is not an MD12xx EMM identity; no further queries sent\n')
                    break
        query(s, '_shutup %d' % hold, limit=2)
finally:
    subprocess.run(['systemctl', 'start', 'md1200-fan'])
