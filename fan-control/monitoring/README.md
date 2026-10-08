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
| `thermal-log` (+ `.service`, `.logrotate`) | every Linux host | A plain local record next to Prometheus: one JSON line per minute in `/var/log/thermal.jsonl` with the inlet, CPU, board, BMC and drive temperatures (added 2026-10-07 evening; see "Local temperature log") |

`lab-thermal-textfile` reads only files the controllers already write, so it adds no IPMI, serial or SES traffic.
That matters on the R720xd: `fan-watchdog` hands the fans to the loud iDRAC auto profile when one of its own sensor
reads fails, and a second in-band IPMI reader can make that happen. Do not add an `ipmitool` collector there.

## Local temperature log (thermal-log)

Every Linux host also keeps a plain record of its own temperatures, independent of the monitoring stack: `thermal-log`
appends one JSON line per minute, on the minute, to `/var/log/thermal.jsonl`; logrotate keeps 30 days, compressed.

```json
{"ts":"2026-10-07T18:10:00-0400","t":1791411000,"host":"mementos","inlet":24,"cpu":{"pkg0":44.0,"pkg1":42.0},
 "board":{"exhaust":41,"dimm_max":42},"shelf":{"backplane":43,"sim":50,"expander":78,"fan_pct":15},
 "drives":{"sda":33,"sdb":43,"sdc":42,"...":"..."}}
```

| Key | What | Source |
|---|---|---|
| `inlet` | air inlet temperature, only where the machine has a real inlet sensor (the R720xd) | `fan-watchdog`'s state file |
| `cpu` | CPU package temperatures: `pkgN` (Intel coretemp), `tctl` (AMD k10temp) | hwmon |
| `board` | Super I/O SYSTIN and CPUTIN (NCT6775 family), NCT6683 inputs, PCH, the Dell laptop EC (`dell_smm`), DDR5 SPD sensors (`spd5118`); on the R720xd also the exhaust and the hottest DIMM | hwmon; `fan-watchdog`'s state file |
| `bmc` | every BMC temperature sensor | the `ipmitool_sensor.prom` file the host's own collector writes every minute (ryuji, sojiro, makoto) |
| `shelf` | MD1200 backplane, SIM, expander and fan % | `md1200-fan`'s state file |
| `drives` | each disk by kernel name; `null` while a disk is asleep | `smartctl -n standby -j -A` (never wakes a disk) |

A line `{"event":"drives","map":{...}}` maps kernel names to model and serial when the logger starts and whenever the
set of disks changes. State files and BMC files older than 5 min are left out. Like `lab-thermal-textfile` it adds no
IPMI, serial or SES traffic of its own. Left out on purpose: ACPI thermal zones (a fixed 27.8C on these boards), the
NCT6799's AUXTIN inputs (unconnected or fixed on tinynas), inputs reading 0, NVMe hwmon entries (the drives section
has them), GPUs, Wi-Fi, batteries, and iSCSI or USB disks (tinypc's iSCSI disk lives on tinynas).

| Host | Hardware | OS | Logged (2026-10-07) |
|---|---|---|---|
| mementos | Dell PowerEdge R720xd, 2x Xeon E5-2697 v2, 24x Seagate ST1200MM0007 + 2x HGST HUSMM SSD, plus the MD1200's 12x 8 TB | Ubuntu 24.04.5 | inlet, 2 CPUs, exhaust, hottest DIMM, the shelf, 38 disks |
| ryuji | Gigabyte MD70-HB0, 2x Xeon E5-2650 v3, 6x Toshiba MG04ACA400N + a boot SSD and a spare 2.5 in HDD | Ubuntu 24.04.5 | 2 CPUs, PCH, 19 BMC sensors (SIO Temp 1/2, VRs, DIMMs), 8 disks |
| sojiro | Gigabyte MB10-series board, Xeon D-1521, 5 SATA disks | Ubuntu 24.04.5 | CPU, PCH, BMC MB_TEMP1 and CPU, 5 disks |
| tinynas | ASUS PRIME B650M-A AX II, Ryzen 5 9600X, 8x HGST HUS724040AL, 2x Crucial P3 Plus 1 TB | Ubuntu 24.04.5 | Tctl, SYSTIN, CPUTIN, 10 disks |
| makoto | ASRock Rack board, Xeon D-1622, 3x Crucial MX500 1 TB, Crucial P310 500 GB | Ubuntu 24.04.5 | CPU, BMC (MB, card side, CPU, DDR4), 4 disks |
| futaba | Lenovo ThinkCentre M700 Tiny, Core i5-6500T, Kingston 256 GB SATA SSD | Ubuntu 24.04.5 | CPU, NCT6683 (PECI, diodes), 1 disk |
| morgana | Dell Latitude 5420, Core i5-1135G7, WD SN530 256 GB | Ubuntu 24.04.5 | CPU, EC sensors, 1 disk |
| tinypc | ASUS ROG STRIX B660-I GAMING WIFI, Core i7-12700F, Samsung 970 EVO Plus 2 TB, Crucial P1 1 TB | Fedora 44 | CPU, 2 DDR5 SPD sensors, 2 disks |

Install (needs python3 and smartmontools 7.0 or later for `-j`; runs as root because of smartctl):

```sh
sudo install -m 755 monitoring/thermal-log /usr/local/sbin/thermal-log
sudo install -m 644 monitoring/thermal-log.service /etc/systemd/system/thermal-log.service
sudo install -m 644 monitoring/thermal-log.logrotate /etc/logrotate.d/thermal-log
sudo systemctl daemon-reload && sudo systemctl enable --now thermal-log
tail -1 /var/log/thermal.jsonl                       # after the next full minute
```

`THERMAL_LOG` and `THERMAL_INTERVAL` (environment) change the path and the period. On other hardware, check which
hwmon chips the board has (`cat /sys/class/hwmon/hwmon*/name`): chips `hwmon()` does not know are skipped, so add
yours there. The inlet, exhaust, DIMM and shelf values come from this repo's controllers' state files and are simply
absent elsewhere.

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
| FanControllerStale | a controller has not written its state for 300 s and no fan-control test unit is active on that host | 10 min (critical) |
| ThermalMetricsMissing | a host is up but its controller's metrics are missing | 15 min |
| R720FansInIdracAuto | `fan-watchdog` handed the R720xd fans to iDRAC auto, and no test unit is active on mementos | 15 min |
| ShelfDriveHot | hottest MD1200 drive 54C or more (`md1200-fan` targets 48.5C; the drives trip at 60C) | 10 min |
| ShelfEmmNotPrimary | the serial cable's EMM is not primary (fan commands are held) | 10 min |
| RyujiSioHot | ryuji SIO Temp 1 82C or more (BMC warns at 80, critical at 85) | 10 min |
| LabRoomHot | mementos inlet 31C or more (23-25C with the AC working, 26-28C while it was faulty) | 30 min |

A host that is down is left to the stack's own `TargetDown` rule; silence that in Alertmanager when a box is off on
purpose. Tests stop controllers and force fan modes on purpose, so the two rules above stay quiet while a test unit
named like the tools in `testing/` and `tools/` is active on that host (`shelf-exp*`, `mementos-steps*`,
`ryuji-profile*` and so on; the list is in the rules file). They read node_exporter's systemd collector, which these
hosts' Ubuntu packages enable. A test unit with another name still alerts.

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
