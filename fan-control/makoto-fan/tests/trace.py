#!/usr/bin/env python3
# trace: print the fan changes of one test scenario (debug aid). usage: trace.py WATTS [room] [from s]
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location('t', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_makoto_fan.py'))
T = importlib.util.module_from_spec(spec)
sys.argv, argv = [sys.argv[0]], sys.argv
spec.loader.exec_module(T)
w, room, frm = float(argv[1]), float(argv[2]) if len(argv) > 2 else 22, float(argv[3]) if len(argv) > 3 else 3600
prev = None
for t, cpu, temps, f1, f4 in T.run(lambda t: w, frm + 1800, room=room):
    if t >= frm and (f1, f4) != prev:
        print(f"t={t:6.0f} cpu {cpu:5.1f} {temps} f1 {f1} f4 {f4}")
        prev = (f1, f4)
