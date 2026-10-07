#!/usr/bin/env python3
# ryuji-fan-guard start-up retry (v2.2, 2026-10-08): the BMC is unreachable for the first N calls (as at boot, ENETUNREACH), then
# answers -80. Expect one "starting; BMC offset is -80 (after 30 s)" line, no "assuming" line. Second case: never
# reachable -> "assuming -80" after 2 min. usage: python3 -I ryuji-fan-guard/tests/test_guard_start.py ryuji-fan-guard/ryuji-fan-guard
import sys, types
src = open(sys.argv[1]).read().replace("if __name__ == '__main__':\n    main()", '')
class Stop(Exception): pass
def case(fail_n):
    clock = [1_000_000.0]; logs = []; calls = [0]
    g = {'__name__': 'x'}
    exec(src, g)
    def bmc(action, offset=None):
        calls[0] += 1
        if calls[0] <= fail_n:
            raise OSError(101, 'Network is unreachable')
        return -80
    def sleep(s):
        clock[0] += s
        if clock[0] - 1_000_000.0 > 200: raise Stop()
    g['bmc'] = bmc; g['log'] = logs.append
    g['time'] = types.SimpleNamespace(time=lambda: clock[0], sleep=sleep, strftime=lambda *a: 'x')
    g['temps'] = lambda: (_ for _ in ()).throw(Stop())   # stop at the first sensor read
    try: g['main']()
    except Stop: pass
    return logs
a = case(3); b = case(100)
print('fail 3:', a); print('fail all:', b)
ok = (a and 'after 30 s' in a[0] and not any('assuming' in l for l in a)) and (b and 'for 2 min' in b[0])
print('PASS' if ok else 'FAIL'); sys.exit(0 if ok else 1)
