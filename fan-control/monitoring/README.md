# Lab thermal monitoring

Puts the three fan controllers' own readings, and the BMC sensors of the boxes without a controller, into the lab's
central Prometheus, with a Grafana dashboard and alert rules. Added 2026-10-07. The room reference for every test
(mementos's iDRAC inlet sensor) now has long-term history, so a test run can start by looking at the dashboard
instead of starting ad-hoc loggers.

| File | Runs on | What it does |
|---|---|---|
| `lab-thermal-textfile` (+ `.service`) | mementos, ryuji | Every 15 s, turns the state files of `md1200-fan`, `fan-watchdog` and `ryuji-fan-guard` into node_exporter textfile metrics. Reads no sensors itself |
| `lab-thermal-rules.yml` | the Prometheus host (`rules/`) | 7 alert rules on those metrics, set to fire only on real trouble |
| `lab-thermal.json` | the Grafana host (provisioned dashboard) | "Lab - Thermal": room proxies on four machines with the rack current, shelf, R720 and ryuji temperatures against their fan levels, controller health |

`lab-thermal-textfile` reads only files the controllers already write, so it adds no IPMI, serial or SES traffic.
That matters on the R720xd: `fan-watchdog` hands the fans to the loud iDRAC auto profile when one of its own sensor
reads fails, and a second in-band IPMI reader can make that happen. Do not add an `ipmitool` collector there.

## Hardware and software this was written for

| Box | Hardware | Role here |
|---|---|---|
| mementos | Dell PowerEdge R720xd, iDRAC7 2.65, 2x Xeon E5-2697 v2, Ubuntu 24.04.5 | runs `fan-watchdog` (R720xd fans) and `md1200-fan` (MD1200 shelf); `lab-thermal-textfile` publishes both |
| MD1200 shelf | Dell PowerVault MD1200, EMM firmware 1.06, 12x 8 TB SAS | its temperatures and fan speed come from `md1200-fan`'s state |
| ryuji | Gigabyte MD70-HB0, Avocent MergePoint BMC 8.44, 2x Xeon E5-2650 v3, Ubuntu 24.04.5 | runs `ryuji-fan-guard`; `lab-thermal-textfile` publishes it; its BMC sensors are exported too |
| sojiro | Gigabyte MB10-series board, Xeon D-1521, BMC firmware 8.65 | BMC sensors only (MB_TEMP1 is a room proxy) |
| makoto | ASRock Rack board, Xeon D-1622, BMC firmware 0.06 | BMC sensors only (MB Temp is a room proxy) |
| tinynas | ASUS PRIME B650M-A AX II, Ryzen 5 9600X, Nuvoton NCT6799 | hwmon only (NVMe Composite and SYSTIN are room proxies) |
| futaba | Lenovo ThinkCentre M700 Tiny, Core i5-6500T, 32 GB, Ubuntu 24.04.5, Docker 29.1 | the monitoring stack: Prometheus 3.15, Alertmanager 0.34, Grafana 13.2, snmp_exporter 0.30 (the rack PDU) |

Every Linux host runs `prometheus-node-exporter` 1.7.0 from Ubuntu's archive with
`--collector.textfile.directory=/var/lib/node_exporter/textfile_collector`. On ryuji, sojiro and makoto, the
`prometheus-node-exporter-collectors` package's `ipmitool-sensor` timer (every minute) writes
`/var/lib/prometheus/node-exporter/ipmitool_sensor.prom`, a directory node_exporter is not pointed at; a symlink into
the textfile directory exports it (`node_ipmi_*`).

## Metrics

| Metric | Labels | Source |
|---|---|---|
| `lab_r720_temp_celsius` | `sensor` = cpu, exhaust, inlet (the room reference), hdd, ssd, dimm | `/run/fan-watchdog.state` |
| `lab_r720_fan_percent`, `lab_r720_fan_auto` | | same (`fan_percent` is absent while in iDRAC auto) |
| `lab_md1200_temp_celsius` | `sensor` = drive (hottest), backplane, sim, expander | `/run/md1200-fan.state` |
| `lab_md1200_fan_percent`, `_fan_rpm`, `_fan_expected_rpm`, `_primary`, `_takeovers` | | same |
| `lab_ryuji_fan_offset` | | `/run/ryuji-fan-guard.state` (-80 quiet, -16 warm, 0 Performance, 127 Full) |
| `lab_ryuji_temp_celsius` | `sensor` = sio1, cpu, vr, dimm | same |
| `lab_controller_state_age_seconds` | `controller` | seconds since each controller last wrote its state (normal: under ~60 s) |

## Alert rules

| Rule | Fires when | For |
|---|---|---|
| FanControllerStale | a controller has not written its state for 300 s | 5 min (critical) |
| ThermalMetricsMissing | a host is up but its controller's metrics are missing | 15 min |
| R720FansInIdracAuto | `fan-watchdog` handed the R720xd fans to iDRAC auto | 15 min |
| ShelfDriveHot | hottest MD1200 drive 54C or more (`md1200-fan` targets 48.5C; the drives trip at 60C) | 10 min |
| ShelfEmmNotPrimary | the serial cable's EMM is not primary (fan commands are held) | 10 min |
| RyujiSioHot | ryuji SIO Temp 1 82C or more (BMC warns at 80, critical at 85) | 10 min |
| LabRoomHot | mementos inlet 31C or more (23-25C with the AC working, 26-28C while it was faulty) | 30 min |

A host that is down is left to the stack's own `TargetDown` rule; silence that in Alertmanager when a box is off on
purpose.

## Install

On mementos and ryuji:

```sh
sudo install -m 755 monitoring/lab-thermal-textfile /usr/local/bin/lab-thermal-textfile
sudo install -m 644 monitoring/lab-thermal-textfile.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now lab-thermal-textfile
cat /var/lib/node_exporter/textfile_collector/lab_thermal.prom        # check
```

On ryuji, sojiro and makoto, to export the BMC sensors:

```sh
sudo ln -sf /var/lib/prometheus/node-exporter/ipmitool_sensor.prom /var/lib/node_exporter/textfile_collector/
```

On the monitoring host, copy `lab-thermal-rules.yml` into Prometheus's rules directory (any name matching its
`rule_files` glob), check it with `promtool check rules`, then reload (`curl -X POST http://localhost:9090/-/reload`
with `--web.enable-lifecycle`). Put `lab-thermal.json` in Grafana's provisioned dashboards directory; it expects a
Prometheus datasource with uid `prometheus`.

## Using this on other hardware

- `lab-thermal-textfile` parses this repo's controllers' state files: the `fan-watchdog` state line format
  (`NN% (cpu=.. exh=.. inlet=.. hdd=.. ssd=..) (dimm=..)`) and the JSON written by `md1200-fan` and
  `ryuji-fan-guard`. With other controllers, change `metrics()`; a missing state file is skipped.
- The dashboard picks hosts by hostname (`node_uname_info{nodename=...}`) and sensors by the names these boards
  report (`MB_TEMP1`, `MB Temp`, NVMe `nvme_nvme0`, the NCT6775-family chip). Edit those for other boxes.
- The alert thresholds come from this hardware in this room (see `../README.md` and `../METHODOLOGY.md`).
