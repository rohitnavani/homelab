#!/usr/bin/env python3
# gbt-power (2026-10-10): calls of the Gigabyte/Avocent BMC web UI (ryuji 10.0.0.118) with one login, logged out
# after. Powers ryuji on with: gbt-power.py 10.0.0.118 get 'gbtdata?set=PowerOn'
# usage: gbt-power.py <bmc ip> pages | dump <page> | get <path>
# Password from BMC_PWFILE (default ~/.config/lab/bmc-pass, 0600), never on the command line; login as in
# ryuji-fan-guard/gbt-fan-offset.py.
import os, re, ssl, sys, urllib.parse, urllib.request, http.cookiejar
BMC, USER = 'https://' + sys.argv[1], os.environ.get('BMC_USER', 'root')
PWFILE = os.environ.get('BMC_PWFILE', os.path.expanduser('~/.config/lab/bmc-pass'))
ctx = ssl.create_default_context(); ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
ctx.set_ciphers('DEFAULT@SECLEVEL=0'); ctx.minimum_version = ssl.TLSVersion.TLSv1
op = urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def req(path, data=None, st2=None):
    r = urllib.request.Request(BMC + path, data=data)
    if data is not None: r.add_header('Content-Type', 'application/x-www-form-urlencoded')
    if st2: r.add_header('ST2', st2)
    with op.open(r, timeout=20) as resp: return resp.read().decode(errors='replace')
def esc(v):
    for a, b in [('\\', '\\\\'), (':', '\\:'), (',', '\\,'), ('(', '\\('), (')', '\\)'), ('=', '\\='), ('&', '\\&'), ('?', '\\?')]:
        v = v.replace(a, b)
    return urllib.parse.quote(v, safe='')
pw = open(PWFILE).read().strip('\n')
out = req('/data/login', f'user={USER}&password={esc(pw)}'.encode()); del pw
if '<authResult>0</authResult>' not in out: sys.exit('login failed: ' + re.sub(r'\s+', ' ', out)[:200])
idx = req('/index.html')
st1, st2 = re.search(r'CSRFHandler\(\s*"ST1",\s*"([^"]+)",\s*"ST2",\s*"([^"]+)"', idx).groups()
try:
    if sys.argv[2] == 'pages':
        print(sorted(set(re.findall(r'[\w/-]+\.(?:html|asp|js)', idx))))
    elif sys.argv[2] == 'dump':
        print(req(f'/{sys.argv[3]}?ST1={st1}', st2=st2))
    elif sys.argv[2] == 'get':
        print(req(f'/{sys.argv[3]}' + ('&' if '?' in sys.argv[3] else '?') + f'ST1={st1}', st2=st2))
finally:
    try: req(f'/data/logout?ST1={st1}', st2=st2)
    except Exception: pass
