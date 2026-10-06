#!/usr/bin/env python3
# gbt-fan-offset: read or set the Gigabyte/Avocent BMC "PWM offset" (ryuji 10.0.0.118, sojiro 10.0.0.14) through
# the same web calls its Utilities page makes. Usage: gbt-fan-offset.py <bmc ip> get | set <offset -127..127>
# The password is read from a 0600 file; nothing is printed or passed on a command line.
import os, re, ssl, sys, urllib.parse, urllib.request, http.cookiejar

BMC, USER = 'https://' + sys.argv[1], os.environ.get('BMC_USER', 'root')
PWFILE = os.environ.get('BMC_PWFILE', os.path.expanduser('~/.config/lab/bmc-pass'))  # 0600; recreate from ryuji: ssh ryuji 'sudo cat /root/.bmc-pass'

ctx = ssl.create_default_context()
ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
ctx.set_ciphers('DEFAULT@SECLEVEL=0')
ctx.minimum_version = ssl.TLSVersion.TLSv1
jar = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx), urllib.request.HTTPCookieProcessor(jar))

def req(path, data=None, st2=None):
    r = urllib.request.Request(BMC + path, data=data)
    if data is not None:
        r.add_header('Content-Type', 'application/x-www-form-urlencoded')
    if st2:
        r.add_header('ST2', st2)
    with op.open(r, timeout=20) as resp:
        return resp.read().decode(errors='replace')

def esc(v):  # the page's encodeSetValue()
    for a, b in [('\\', '\\\\'), (':', '\\:'), (',', '\\,'), ('(', '\\('), (')', '\\)'), ('=', '\\='), ('&', '\\&'), ('?', '\\?')]:
        v = v.replace(a, b)
    return urllib.parse.quote(v, safe='')

def login():
    pw = open(PWFILE).read().strip('\n')  # same as ryuji-fan-guard
    out = req('/data/login', f'user={USER}&password={esc(pw)}'.encode())
    if '<authResult>0</authResult>' not in out:
        sys.exit('login failed: ' + re.sub(r'\s+', ' ', out)[:200])
    idx = req('/index.html')
    m = re.search(r'CSRFHandler\(\s*"ST1",\s*"([^"]+)",\s*"ST2",\s*"([^"]+)"', idx)
    return m.group(1), m.group(2)

def current(st1, st2):
    page = req(f'/utilities.html?ST1={st1}', st2=st2)
    raw = int(re.search(r'var fanCurve\s*=\s*(\d+);', page).group(1))
    user_mode = int(re.search(r'var iFanUserMode\s*=\s*(\d+);', page).group(1))
    return raw, (raw if raw < 128 else 128 - raw), user_mode

st1, st2 = login()
try:
    raw, off, mode = current(st1, st2)
    if sys.argv[2] == 'get':
        print(f'offset {off} (raw {raw}, user mode {mode})')
    elif sys.argv[2] == 'set':
        new = int(sys.argv[3])
        assert -127 <= new <= 127
        newraw = new if new >= 0 else 128 - new
        out = req(f'/gbtdata?set=FanCurveSet(1,{newraw})&ST1={st1}', st2=st2)
        raw2, off2, mode2 = current(st1, st2)
        print(f'was {off}, asked {new}, now {off2} (raw {raw2}, user mode {mode2}); reply status: '
              + (re.search(r'<status>(\w+)</status>', out).group(1) if '<status>' in out else out[:80]))
finally:
    try:
        req(f'/data/logout?ST1={st1}', st2=st2)
    except Exception:
        pass
