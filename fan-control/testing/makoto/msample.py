#!/usr/bin/env python3
# msample: makoto thermal sampler for the 2026-10-19 fan tests (root: RAPL and ipmitool).
# Every 2 s: coretemp package and cores, NVMe composite, RAPL package W, CPU busy (of 8 threads), mean core MHz,
# and the latest BMC reading (FAN1, FAN4, CPU1/DDR4_A/DDR4_B/MB/Card Side temps, the 0x3a 0x02 setting), which a
# thread refreshes about every 5 s (one read takes ~1 s). The phase label comes from /run/makoto-fantest.phase.
# usage: msample.py OUT.csv [hours, default 24]
import glob, os, subprocess, sys, threading, time

out, hours = sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 24
PHASE = '/run/makoto-fantest.phase'
RAPL = '/sys/class/powercap/intel-rapl:0/energy_uj'
RAPL_MAX = int(open('/sys/class/powercap/intel-rapl:0/max_energy_range_uj').read())
CORETEMP = next(d for d in glob.glob('/sys/class/hwmon/hwmon*') if open(d + '/name').read().strip() == 'coretemp')
NVME = next((d for d in glob.glob('/sys/class/hwmon/hwmon*') if open(d + '/name').read().strip() == 'nvme'), None)
SENS = ['FAN1', 'FAN4', 'CPU1 Temp', 'DDR4_A Temp', 'DDR4_B Temp', 'MB Temp', 'Card Side Temp']
bmc = {'t': 0.0, 'v': ['' for _ in SENS], 'set': ''}


def bmc_loop():
    while True:
        try:
            r = subprocess.run(['ipmitool', 'sensor', 'reading', *SENS], capture_output=True, text=True, timeout=15)
            vals = {}
            for line in r.stdout.splitlines():
                k, _, v = line.partition('|')
                vals[k.strip()] = v.strip()
            s = subprocess.run(['ipmitool', 'raw', '0x3a', '0x02'], capture_output=True, text=True, timeout=10)
            b = s.stdout.split()
            bmc.update(v=[vals.get(k, '') for k in SENS], set=f'{int(b[0], 16)}/{int(b[3], 16)}' if len(b) == 8 else '?',
                       t=time.time())
        except Exception as e:  # keep sampling; the age column shows a stale BMC
            print('bmc read failed:', e, file=sys.stderr)
        time.sleep(4)


def rd(p, div=1000):
    try:
        return int(open(p).read()) / div
    except OSError:
        return float('nan')


def cpu_times():
    f = open('/proc/stat').readline().split()[1:]
    v = list(map(int, f))
    return sum(v), v[3] + v[4]


threading.Thread(target=bmc_loop, daemon=True).start()
new = not os.path.exists(out)
log = open(out, 'a', buffering=1)
if new:
    log.write('epoch,phase,pkg,c0,c1,c2,c3,nvme,rapl_w,busy,mhz,fan1,fan4,cpu_bmc,ddra,ddrb,mb,card,bmc_age,set\n')
e0, t0 = rd(RAPL, 1), time.time()
tot0, idle0 = cpu_times()
end = time.time() + hours * 3600
time.sleep(2)
while time.time() < end:
    e1, t1 = rd(RAPL, 1), time.time()
    tot1, idle1 = cpu_times()
    watts = ((e1 - e0) % RAPL_MAX) / 1e6 / (t1 - t0)
    busy = 8 * (1 - (idle1 - idle0) / max(1, tot1 - tot0))
    e0, t0, tot0, idle0 = e1, t1, tot1, idle1
    temps = [rd(f'{CORETEMP}/temp{i}_input') for i in range(1, 6)]
    nv = rd(f'{NVME}/temp1_input') if NVME else float('nan')
    mhz = sum(rd(p) for p in glob.glob('/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq')) / 8
    try:
        phase = open(PHASE).read().strip()
    except OSError:
        phase = ''
    log.write(f'{t1:.0f},{phase},' + ','.join(f'{x:.0f}' for x in temps) + f',{nv:.0f},{watts:.1f},{busy:.2f},{mhz:.0f},'
              + ','.join(bmc['v']) + f',{t1 - bmc["t"]:.0f},{bmc["set"]}\n')
    time.sleep(max(0.1, 2 - (time.time() - t1)))
