#!/usr/bin/env python3
# fit-steady: steady-state model of makoto's temperatures from every fanstep phase. Per phase (>= MIN minutes, the
# last LAST minutes): medians of package W, FAN1/FAN4 rpm, each sensor, and the room (mementos inlet, Prometheus).
# Fits, by least squares, each sensor's rise over the room as
#   rise = a + b*P + c*P*u1 + d*u1 + e*u4         u1 = 1000/rpm1, u4 = 1000/rpm4  (airflow ~ rpm)
# and prints the fit, its residuals, and a table of predictions.
# usage: fit-steady.py RUN.csv [RUN.csv ...]
import csv, json, statistics as st, sys, time, urllib.parse, urllib.request
import numpy as np

D = '/home/rohit/lab-thermal-2026-10-19/data/'
LAST, MIN = 3.0, 6.0
ms = [r for r in csv.DictReader(open(D + 'msample.csv')) if r['fan1']]
mt = np.array([int(r['epoch']) for r in ms])


def room_series(t0, t1):
    q = 'max(lab_r720_temp_celsius{sensor="inlet"})'
    u = 'http://10.0.0.3:9090/api/v1/query_range?' + urllib.parse.urlencode({'query': q, 'start': t0 - 600, 'end': t1, 'step': 60})
    r = json.load(urllib.request.urlopen(u, timeout=60))['data']['result']
    return {int(float(t)): float(v) for t, v in r[0]['values']} if r else {}


phases = []
for f in sys.argv[1:]:
    rows = list(csv.DictReader(open(f)))
    for r in rows:
        if not phases or phases[-1]['label'] != r['label'] or phases[-1]['file'] != f:
            phases.append({'file': f, 'label': r['label'], 't0': int(r['epoch']), 't1': int(r['epoch']), 'ev': ''})
        phases[-1]['t1'] = int(r['epoch'])
        phases[-1]['ev'] += r.get('event', '')
room = room_series(min(p['t0'] for p in phases), max(p['t1'] for p in phases))
rt = sorted(room)
data = []
for p in phases:
    if p['t1'] - p['t0'] < MIN * 60 or 'load off' in p['ev'] or 'abort' in p['ev']:
        continue
    sel = [ms[i] for i in np.nonzero((mt >= p['t1'] - LAST * 60) & (mt <= p['t1']))[0]]
    if len(sel) < 20:
        continue
    med = lambda k: st.median(float(r[k]) for r in sel if r[k] not in ('', 'na'))
    rm = st.median(room[t] for t in rt if p['t1'] - LAST * 60 - 120 <= t <= p['t1']) if room else 24.0
    data.append(dict(label=p['label'], P=med('rapl_w'), rpm1=med('fan1'), rpm4=med('fan4'), room=rm, cpu=med('pkg'),
                     ddr=max(med('ddra'), med('ddrb')), mb=med('mb'), card=med('card'), nvme=med('nvme'),
                     busy=med('busy')))
print(f'{len(data)} phases; room {min(d["room"] for d in data):.0f}-{max(d["room"] for d in data):.0f}C\n')
X = np.array([[1, d['P'], d['P'] * 1000 / d['rpm1'], 1000 / d['rpm1'], 1000 / d['rpm4']] for d in data])
fits = {}
for s in ('cpu', 'card', 'ddr', 'mb', 'nvme'):
    y = np.array([d[s] - d['room'] for d in data])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    res = y - X @ coef
    fits[s] = coef
    print(f"{s:5s} rise = {coef[0]:6.2f} {coef[1]:+.3f}*P {coef[2]:+.3f}*P*u1 {coef[3]:+.2f}*u1 {coef[4]:+.2f}*u4   "
          f"rms {np.sqrt((res ** 2).mean()):.2f}C, worst {np.abs(res).max():.1f}C")
print('\nphase              P    rpm1  rpm4 room |  cpu (fit)  card (fit)  ddr (fit)  nvme (fit)')
for d, x in zip(data, X):
    pr = {s: d['room'] + x @ c for s, c in fits.items()}
    print(f"{d['label']:16s} {d['P']:5.1f} {d['rpm1']:5.0f} {d['rpm4']:5.0f} {d['room']:4.0f} | {d['cpu']:4.0f} ({pr['cpu']:4.1f}) "
          f"{d['card']:4.0f} ({pr['card']:4.1f}) {d['ddr']:4.0f} ({pr['ddr']:4.1f}) {d['nvme']:4.0f} ({pr['nvme']:4.1f})")
json.dump({s: list(c) for s, c in fits.items()}, open(D + 'fit-steady.json', 'w'))
