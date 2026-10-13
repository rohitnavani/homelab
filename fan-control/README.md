# Fan control

Quiet fans for the rack without hurting the hardware: as quiet as possible at idle and light load, a medium level
under heavy work, loud only at full load or when something is genuinely hot. Built and tested 2026-10-04 to
2026-10-06; `git log -p fan-control/` shows each version and why it changed.

| Controller | Runs on | Controls | Installs to |
|---|---|---|---|
| `md1200-fan` | mementos | MD1200 shelf fans, via the EMM serial console (`_shutup <pct>` over an FTDI adapter, `/dev/ttyUSB0`, cable on the TOP EMM) | `/usr/local/bin/md1200-fan` |
| `fan-watchdog` | mementos | Dell R720xd fans, via `ipmitool raw 0x30 0x30` | `/usr/local/sbin/fan-watchdog` |
| `ryuji-fan-guard` | ryuji | Gigabyte MD70-HB0 BMC (Avocent) fan offset, via the BMC's own web API | `/usr/local/sbin/ryuji-fan-guard` |

`monitoring/` puts the controllers' readings into Prometheus, with a Grafana dashboard and alert rules (see
`monitoring/README.md`).

These are written for the exact machines below, not for a hardware family in general. Every temperature threshold,
fan curve and timing came from measuring these boxes in this room. Read "Hardware" and "Using this on other
hardware" before running any of it anywhere else.

## Hardware

Recorded 2026-10-06 (read with `dmidecode`, `lscpu`, `lspci`, `lsusb`, `ipmitool mc info`, `sg_inq`, `lsblk`).
Both controller hosts run Ubuntu 24.04.5 LTS (kernel 6.8), Python 3.12, ipmitool 1.8.19, smartmontools 7.4,
sg3-utils 1.46, python3-serial 3.5.

### mementos: Dell PowerEdge R720xd (runs `fan-watchdog` and `md1200-fan`)

| Part | What is installed |
|---|---|
| Server | Dell PowerEdge R720xd (12th generation, 2U), motherboard 0VWT90, BIOS 2.5.2 |
| BMC | iDRAC7, firmware 2.65 |
| CPUs | 2x Intel Xeon E5-2697 v2 (Ivy Bridge-EP, 12 cores / 24 threads, 130 W TDP each); 48 threads total |
| Memory | 16x 16 GB DDR3-1600 dual-rank RDIMM (256 GB), 8 slots empty |
| Front bays | 24x Seagate ST1200MM0007 (1.2 TB 10K SAS, 2.5"), ZFS `vmPool` |
| Rear bays | 2x HGST HUSMM8080ASS20 (800 GB SAS SSD), SLOG for `dataPool` |
| Storage controllers | Dell H710P mini (internal bays) and Dell H810 (external, to the MD1200), both crossflashed to IT mode; both show as Broadcom/LSI SAS2308 |
| Fans | 6 system fans (`Fan1`-`Fan6` in IPMI); 10% is about 3,400 rpm, 35% about 7,600 rpm |
| Power | One PSU installed on purpose (the iDRAC reports PS1 as AC lost; expected) |
| Serial adapter | FTDI FT232R USB-UART (USB ID 0403:6001), `/dev/ttyUSB0`, to the MD1200's top EMM |

### MD1200 shelf (controlled from mementos by `md1200-fan`)

| Part | What is installed |
|---|---|
| Enclosure | Dell PowerVault MD1200 (2U, 12x 3.5" bays), SES product revision 1.06 |
| EMMs | 2 EMMs, firmware 1.06. The TOP EMM is the primary; the bottom EMM is secondary and carries the SAS links |
| Drives | 11x Seagate ST8000NM0075 and 1x ST8000NM0185 (8 TB 7.2K SAS), ZFS `dataPool` raidz2 |
| Fans | No separate fan modules: 2 PSU/cooling modules with 2 fans each, set together as one % |
| Fan speeds | Measured: 10% 2,330 rpm, 15% 2,800, 20% 3,290, 25% 3,770, 30% 4,250; firmware default about 5,000; thermal ramp about 7,600 |
| Control path | EMM serial console at 38400 baud, 8N1 (pyserial defaults), from the FTDI adapter on mementos; SES (`sg_ses`) through the H810 shows up as `/dev/sg39` |
| Slot layout | Slot 0 top left, 3 rows of 4. The hottest drives sit in the middle row, not the top row under mementos |

### ryuji: Gigabyte MD70-HB0 (runs `ryuji-fan-guard`)

| Part | What is installed |
|---|---|
| Server | Gigabyte MD70-HB0 board in a 2U 12-bay chassis, BIOS R09 |
| BMC | Avocent MergePoint, firmware 8.44 (IPMI and web UI; its clock runs on UTC) |
| CPUs | 2x Intel Xeon E5-2696 v4 since 2026-10-12 (Broadwell-EP, an OEM E5-2699 v4: 22 cores / 44 threads each, 2.2 GHz base, up to 3.7 GHz on a few cores; the BIOS sets 150 W PL1 / 180 W PL2 per package; microcode 0xb000040). The BMC warns at 82C and is critical at 85C for these CPUs. Before: 2x E5-2650 v3 (Haswell-EP, 10 cores, 105 W), which ryuji-fan-guard v2.3 and earlier were tuned for |
| Memory | 8x 16 GB DDR4-2133 (Kingston 9965640-001), 128 GB |
| Drives | 6x Toshiba MG04ACA400N (4 TB 7.2K SATA) as three ZFS mirrors (`computePool`, since 2026-10-12), 1x HGST HTS721010A9 (1 TB), 1x Kingston SUV400S (120 GB SSD) |
| Storage controller | Broadcom/LSI SAS3008 |
| Fans | `CPU0_FAN`, `CPU1_FAN`, `SYS_FAN1`-`SYS_FAN4` (`SYS_FAN5` not connected). The BMC runs its own curve; the only setting it exposes is a PWM offset (-127 to 127) added to that curve |
| Limiting sensors | At idle `SIO Temp 1` (BMC warns at 80C, critical 85C), which follows system-fan airflow more than CPU load; under load the CPUs (CPU1 runs ~10C hotter than CPU0 at the same 150 W: 74 vs 63C at full load and -80) |

### The rack and the room

- One rack in a living room: mementos, the MD1200 and ryuji (and sojiro, a Xeon D-1521
  backup box with no fan controller) on a CyberPower PDU20SW8FNET on a 20 A circuit. About 700 W at idle.
- An AC cools the room. During the 2026-10-04 to 10-06 work it was failing and the room cycled 24-28C;
  the numbers below were measured in that room.

## Using this on other hardware

Treat these as worked examples. Each controller has hardcoded device paths, sensor names, drive models and
thresholds from the hardware above. What carries over and what to change:

- **md1200-fan** needs a Dell MD1200 with its EMM serial console wired to the host, and that host must also see the
  shelf's SES device through a SAS HBA. Tested only on EMM firmware 1.06 with the drives above; the `_shutup`
  behaviour (and its rpm per %) may differ on other firmware, and an MD1220 is untested. Change `PORT` and `SG`
  (find the SES device: the `scsi_generic` entry whose `device/type` is 13), the drive model and the temperature
  targets (`ST8000NM0075` trips at 60C). Put the cable on the primary EMM and confirm with `_who`.
- **fan-watchdog** needs a Dell 12th-generation PowerEdge (R720/R720xd class, iDRAC7). The `raw 0x30 0x30` fan
  commands are Dell OEM; later iDRAC firmware on newer generations has removed manual fan control, so test before
  trusting it. The DIMM reading is specific to Xeon E5 v2 (Ivy Bridge-EP) memory controllers: it reads the
  "Thermal Control" PCI functions at offsets 0x150-0x158. On other CPUs it may find no registers or read the wrong
  ones, so check what `dimm_max` returns before deploying. The drive models (`ST1200`, `HUSMM`) and every curve are
  set by name and number in the script.
- **ryuji-fan-guard** needs a Gigabyte server board with the Avocent MergePoint BMC (tested: MD70-HB0, firmware
  8.44). It drives the same web calls as the BMC's Utilities page, which need legacy TLS. The BMC address
  (`10.0.0.118`), the sensor names (`SIO Temp 1`, `CPUn_TEMP`, `VR_*`, `DIMM*`) and every threshold are specific
  to this board and these CPUs. Profile the box first (`tools/ryuji-profile.py`) and set the thresholds from that.
- For any of them: run the offline tests, then deploy behind a watch that rolls back by itself
  (`testing/deploy-examples/`), as `METHODOLOGY.md` describes.

## md1200-fan (MD1200 shelf)

- Holds the hottest shelf drive near 50C (v3.2; v3.1 held 48.5C), with backplane 46C, SIM 58C and expander 86C as
  guards. Steps 1-2% up at most every 10 min and 1% down at most every 20 min, because the drives take 20-35 min to
  settle after a change. While the hottest drive is 5C or more under target it eases down every 5 min instead (v3.2),
  so after a spike the shelf is back near its idle level in about 2 h instead of 8-9 h.
- Urgent: +5% at once at drive 53, backplane 48, SIM 61 or expander 90C, then +5% at most every 5 min while it lasts
  (v3.2). v3.1 stepped every 30 s from drive 52: on 2026-10-07 one 52C reading in a 27C room took the shelf from 12%
  to 37% in 2.5 min, and it took 9 h to ease back. Floors of 60-80% near the hard limits.
- Only commands the primary EMM (checks `_who`). The cable must be on the TOP EMM: the bottom one is secondary, and
  a command sent to it only lasts about 15 s before the primary takes over.
- Re-sends every 2 s as insurance against the shelf firmware's own thermal ramp (a single command to the primary
  held for 45 min in testing), checks the echo, and compares the SES fan speed (`sg_ses -p 2`) with the expected one.
- Finds the shelf's SES device at start by type and model (`/sys/class/scsi_generic`, type 13, model MD1200), so a
  renumbered `/dev/sgN` after a reboot or an HBA change does not break the fan-speed check (v3.2).
- Never send `_shutup` below 10. Never hot-insert or remove EMMs or PSUs (the shelf loops resets until power-cycled).
- Measured in a steady 23.5-24.5C room (2026-10-07/08, 75-120 min per level, settled values): 10% (2,340 rpm) puts
  the hottest drive at 50C, 12% at 48C, 15% at 45-47C, 20% at 42C, 25% (3,760 rpm) at 39C; the backplane runs 3-5C
  below it. At 24C v3.2 settles around 10-12%, and each 1C more room costs about 1%. At a mic 1.5 ft in front of the
  rack, 10 -> 15% adds 0.4 dB(A), 15 -> 20% 1.0 dB and 20 -> 25% 1.4 dB: below 15% the shelf is lost in the rest of
  the rack. Stop it and the shelf goes back to its own ~5,000 rpm default.
- Needs python3-serial, sg3-utils, smartmontools.
- Hardware: Dell MD1200 (EMM firmware 1.06), FTDI FT232R serial adapter on the top EMM, SES via a Dell H810
  (IT mode); see "Hardware".

## fan-watchdog (R720xd)

- Fan % is the highest any sensor asks for. CPU: 10% up to 68C, 35% at 82C, 55% at 88C. Exhaust 48-58C, inlet
  30-36C, ST1200 HDDs 42-48C, HUSMM SSDs 52-62C and DIMMs 65-80C map to 10-35%.
- Up at once; down 1% per loop (3% while above 35%); changes only when the target is 2% or more away, and always
  finishes the step back to the 10% floor.
- iDRAC auto profile at CPU 90, exhaust 62, inlet 38, HDD 52, SSD 65, DIMM 85C or any failed read; back to the
  curve after 5 cool minutes. Stopping the service also hands the fans to the iDRAC (`ExecStopPost`).
- DIMM temperatures come from the Xeon E5 v2 memory controllers (DIMMTEMPSTAT registers via `setpci`), because the
  iDRAC does not expose them and manual fan mode bypasses its own DIMM logic.
- Measured: idle 10% (~3,500 rpm); 12 of 24 cores busy ~21%; 18 cores ~25%; full load 32-35% (~7,400 rpm) with the
  CPUs at 79-82C (peak 83C when a full load starts from idle). A fixed 50% holds full load at 72C.
- State line in `/run/fan-watchdog.state`: `10% (cpu=.. exh=.. inlet=.. hdd=.. ssd=..) (dimm=..)`.
- Needs ipmitool, smartmontools, pciutils.
- Hardware: Dell R720xd, iDRAC7 2.65, 2x Xeon E5-2697 v2 (the DIMM reads depend on this CPU family); see
  "Hardware".

## ryuji-fan-guard (ryuji)

- ryuji's limiting sensor at idle is SIO Temp 1 (the BMC warns at 80C). It follows the system fans, which stay at
  their ~1,050 rpm floor at offset -80 while the CPUs are idle. Under load the BMC raises the system fans itself
  (on the E5-2696 v4s already at 4 busy threads), so SIO1 falls; with 150 W CPUs the CPUs are what to watch there.
- Levels: -80 (quiet: idle, and heavy loads since v2.5), -60 (busy: a sustained lighter load, v2.4; -40 in v2.3),
  -16 (system fans follow load), 0 (Performance), 127 (Full Speed).
- -80 to -60 (v2.4) when at least 2 logical CPUs are busy (`/proc/stat`) for 2 readings: about 1-3 min into a job.
  Measured 2026-10-12 on the E5-2696 v4s (ryuji out of the rack, room 24-25C, 4 busy threads, 20-30 min holds,
  A/B/A/C): at -80 the BMC lifts the system fans to 1,300-1,600 rpm and SIO1 falls to 64-68C, but ryuji's
  power-supply fan tone sits at 782 Hz, in the 680-830 Hz band the rack and room ring at (-67.0 dB(A)); -60
  (system fans 2,100-2,600 rpm, SIO1 54C) reads the same -67.0 dB(A) with the tone at 665 Hz, under the band; -40
  (system fans ~2,900 rpm) keeps the tone at ~610 Hz but reads 1 dB(A) more. v2.3 used -40, entered when SIO1
  climbed past 74C under load (right for the E5-2650 v3s, where -40 was 0.7 dB(A) quieter than -80 on 2026-10-10);
  on the new CPUs SIO1 no longer climbs, so it never fired. That rule remains only as the fallback when
  `/proc/stat` cannot be read. Back to -80 after 10 idle minutes once SIO1 is 77C or lower.
- -60 only while both CPUs together draw under 215 W (RAPL package power), and back to -80 once they draw 235 W or more
  for 5 readings in a row (v2.5). Measured 2026-10-13 (room 24C, 8 min holds at fixed offsets): 22 workers (188 W)
  -60 -65.47 / -80 -65.09 dB(A) with the power-supply tone at 442 Hz / 729 Hz (in the band); 33 workers (245 W) -60
  -57.27 / -80 -58.21 (tone at the band's top, 817-820 Hz, at both); 44 workers (296 W, both CPUs at their 150 W
  limit) -60 -50.30 / -80 -53.01 dB(A) for a hottest CPU of 72 / 74C. Past ~400 W at the wall the tone sits at or
  above the band whatever the offset, the BMC's own curve already drives the fans hard, and -60 only adds fan noise.
  The trigger is power, not busy threads or temperatures: it follows the power supply's load whatever the room or
  the job (a lighter 44-thread job that draws 200 W gets -60). Between 215 and 235 W nothing changes, and the 5
  readings keep a job whose power swings across the line every few minutes at -60. Without RAPL, v2.4's rule applies.
- Full load (44 workers, room 24C, no thermal throttling at any offset): hottest CPU 74C at -80, 72C at -60, 69C at
  -16 and at Performance, 65C at Full Speed; 534-617 W at the wall; 2,761-2,797 MHz on every core. So v2.5 holds a
  full load at -80, 8C under the BMC's warning, and goes to -16 only in a warm room (CPU 78C).
- -60 to -16 if SIO1 still climbs past 77C or reaches 79C, or a CPU reaches 78C, a VR 90C or a DIMM 75C. -80 to
  -16 directly when SIO1 reaches 79C for 2 min with the CPUs idle (a hot room: -60 does not lift the system fans
  at idle) or at those CPU/VR/DIMM limits. -16 to Performance if that is not enough. Full at SIO1 83C or CPU 83C
  (v2.4; 86C before, above the E5-2696 v4's 85C critical). Back to -80 from -16 after 10 idle minutes once SIO1 is
  72C or lower (30 min at 71C or lower after a hot room).
- Idle means less than one logical CPU busy (`/proc/stat`) with VR and DIMMs cool (v2.3; before, the hottest CPU at
  50C or lower, which a light load at -40 in a cool room can undercut). The state file shows it as `threads`, and
  every level change logs it (v2.4).
- Re-checks the BMC offset every 30 min and puts its level back; temps unreadable for 5 min means Performance.
- At start it reads the BMC offset, retrying every 10 s for up to 2 min (v2.2): at boot ryuji's address is not
  usable yet when network-online.target is reached, which made that first read fail on 10-06 and 10-07. The unit
  wants network-online.target.
- Needs the BMC password in `/root/.bmc-pass` (0600, root only); the BMC web API needs legacy TLS.
  `gbt-fan-offset.py <bmc ip> get|set N` reads or sets the offset by hand (stop the guard first).
- Hardware: Gigabyte MD70-HB0, Avocent MergePoint BMC 8.44, 2x Xeon E5-2696 v4 since 2026-10-12 (v2.4 and v2.5
  are tuned for them); see "Hardware". The package-power thresholds depend on this CPU pair and this power supply.

## Install or update

```sh
sudo install -m 755 fan-watchdog/fan-watchdog /usr/local/sbin/fan-watchdog
sudo cp fan-watchdog/fan-watchdog.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now fan-watchdog
```

Same pattern for the others (`md1200-fan` goes to `/usr/local/bin`). Keep the previous version as a `.bak-<date>`
next to it so a rollback is one `cp` and a restart.

## Tests (offline, no hardware touched)

```sh
python3 -I md1200-fan/tests/test_md1200_v3.py md1200-fan/md1200-fan                   # closed loop, 5 scenarios
TAU=2700 python3 -I md1200-fan/tests/test_md1200_lag_scenarios.py md1200-fan/md1200-fan # with the measured 45 min lag
TAU=2700 CYC=1 python3 -I md1200-fan/tests/test_md1200_lag_sweep.py md1200-fan/md1200-fan
python3 -I md1200-fan/tests/test_md1200_scenarios.py md1200-fan/md1200-fan             # 9 scenarios, 10-08 shelf model
python3 -I md1200-fan/tests/sweep_md1200_scenarios.py <older md1200-fan> md1200-fan/md1200-fan  # 81 models, ~12 min
fan-watchdog/tests/run-tests.sh                                                        # about 2 minutes
python3 -I ryuji-fan-guard/tests/test_ryuji_fan_guard.py ryuji-fan-guard/ryuji-fan-guard  # 28 scenarios (v2.5)
python3 -I ryuji-fan-guard/tests/test_guard_start.py ryuji-fan-guard/ryuji-fan-guard      # start-up retry (v2.2)
```

## Tools

- `tools/ryuji-profile.py`: thermal profile of ryuji across BMC offsets and CPU loads; rerun it after the CPU
  upgrade. Copy it, `ryuji-profile-restore.sh` and `ryuji-fan-guard/gbt-fan-offset.py` to `/var/tmp` on ryuji, run
  `tools/lab-inlet-guard.sh` somewhere that can reach mementos (its load steps wait for a fresh room reading in
  `/run/room-inlet`), then
  `sudo systemd-run --unit=ryuji-profile -p ExecStopPost=/var/tmp/ryuji-profile-restore.sh python3 /var/tmp/ryuji-profile.py <label> full`
  (about 2 hours; it stops the guard while it runs and starts it again afterwards).
- `tools/ryuji_profile_table.py`: merges profile CSVs into one offset by load table, with the CPU temperature rise
  per package watt and a projection for other CPUs.
- `tools/lab-inlet-guard.sh`: reads the mementos inlet every minute, logs it, publishes it to ryuji and mementos as
  `/run/room-inlet`, and switches test load off if the room passes a limit.
- `tools/room-feed.sh` (2026-10-10): the same room reading for ryuji-only tests without a second in-band IPMI
  reader on mementos (that can make fan-watchdog's own read fail): it takes the R720 inlet that fan-watchdog already
  reads from Prometheus (only while fan-watchdog's state is fresh), writes `/run/room-inlet` on ryuji and kills
  ryuji's stress-ng above LIMIT twice in a row.
- `tools/gbt-power.py` (2026-10-10): calls of ryuji's BMC web UI with one login (the password from
  `~/.config/lab/bmc-pass`, 0600, or `BMC_PWFILE`): `pages`, `dump <page>`, `get <path>`.
  `gbt-power.py 10.0.0.118 get 'gbtdata?set=PowerOn'` powers ryuji on.

## Testing on the hardware

`METHODOLOGY.md` covers how the 2026-10-05/06 data was gathered, what went wrong (mainly a room that cycled 24-28C
while the AC struggled) and how to run the tests again: the shelf and mementos with the AC working, ryuji after the
E5-2696 v4 upgrade, noise with a microphone, and tinynas after its cage fan check. `testing/` has the scripts as they
ran (see `testing/README.md`).

## Results, 2026-10-06 (room 24-28C)

Measured while the room cycled; to be repeated with the AC working (see `METHODOLOGY.md`).

| Box | Idle | Heavy load |
|---|---|---|
| MD1200 shelf | 17% (~3,000 rpm), hottest drive 48C | full scrub: 17-22%, no drive above 50C |
| mementos | 10%, CPUs ~52C, 290 W | full load 32-35%, CPUs 79-82C, ~548 W |
| ryuji | -80, CPU/system fans 2,300/1,050 rpm, SIO1 77-78C, ~150 W | full load at -80: 4,900/3,200 rpm, SIO1 55C, CPUs 60/70C, ~360 W |

## Results, night of 2026-10-07 (room 26-28C, quiet checks)

| Box | What ran | Result |
|---|---|---|
| mementos | 6 and 12 busy cores, 12 from idle (stopped at 24%) | 18-24%, CPUs up to 78C; back to exactly 10% in 10.5-11 min |
| MD1200 shelf | full dataPool scrub | 18 -> 21%, hottest drive 50C, 0 errors |
| ryuji | 4 busy threads (stopped by the noise guard after 2 min) | guard -80 -> -16 -> -80; CPU fans 3,700 rpm at -80, +4.2 dB(A) |

## Results, 2026-10-10 (room 23-25C, AC working)

ryuji under a sustained light load (`testing/ryuji-floor.py psu1010 psu`: 4 busy threads, 30 min per offset,
A/B/B/A, each followed by 15 min idle at -80; medians over each load's last 15 min, mic 1.5 ft in front of the rack):

| Offset | CPU / system fans | SIO1 | Hottest CPU | dB(A) | ryuji's PSU-fan tone | Clips with a tone at 680-830 Hz |
|---|---|---|---|---|---|---|
| -80 (A1) | 3,900 / 1,050 rpm | 78C | 64C | -67.48 | 782 Hz | 86% |
| -40 (B1) | 4,300 / 1,875 rpm | 61C | 57C | -68.16 | 636 Hz | 0% |
| -40 (B2) | 4,300 / 1,900 rpm | 59C | 57C | -68.32 | 586 Hz | 1% |
| -80 (A2) | 3,900 / 1,062 rpm | 78C | 64C | -67.67 | 768 Hz | 93% |

-40 is 0.7 dB(A) quieter than -80 there and keeps the power-supply fan out of the band the rack rings at, with the
board 17-19C cooler; v2.2 would have gone to -16 (CPU ~4,900 / system ~3,300 rpm) about 15-20 min into such a load.
Hence ryuji-fan-guard v2.3 (-40 step). Live check with the guard in control: the guard went -80 -> -40 at 16:49:28, 4.5 min into 4
busy threads (SIO1 75C, before the PSU tone reached the band), held -40 to the end of the 40 min load (SIO1 58C,
hottest CPU 56C, CPU 4,400 / system 2,100-2,200 rpm, the PSU tone at 601-636 Hz in every clip) and went back to
-80 at 17:36:22, 11 min after the load ended. No BMC event. (Evening household sounds made that hour's dB(A)
unusable for comparing with the afternoon.)

The whole monitoring run, 10-10 00:31 to 10-11 08:00 (1,890 min, `testing/lab-watch.py`):

| Box | Fans | Temperatures |
|---|---|---|
| Room | - | rack inlet 23-25C (24C 71% of the time) |
| MD1200 shelf | 10-11% for 85% of the run; 16% at most (the monthly scrub of all six pools, 0 errors) | hottest drive median 49C, 52C at most |
| mementos | 10% for 99%; 12-15% for 2-6 min at a time in the scrub | CPUs median 51C, 71C at most |
| ryuji | -80, except 47 min at -40 (the live check) | SIO1 70-72C at idle, 75C at most |

After a warm spell the shelf can hold 1-2% high for hours, because v3.2 eases only once every reading is well under
target (10-11: 12% from 05:29 to the end after 26 min at 25C, hottest drive 48-50C, backplane 44-46C). That costs
about 0.15 dB(A), so the band stays as it is.
