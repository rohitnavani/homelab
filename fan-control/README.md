# Fan control

Quiet fans for the rack without hurting the hardware: as quiet as possible at idle and light load, a medium level
under heavy work, loud only at full load or when something is genuinely hot. Built and tested 2026-10-04 to
2026-10-06 (`makoto-fan` 2026-10-19/20); `git log -p fan-control/` shows each version and why it changed.

| Controller | Runs on | Controls | Installs to |
|---|---|---|---|
| `md1200-fan` | mementos | MD1200 shelf fans, via the EMM serial console (`_shutup <pct>` over an FTDI adapter, `/dev/ttyUSB0`, cable on the TOP EMM) | `/usr/local/bin/md1200-fan` |
| `fan-watchdog` | mementos | Dell R720xd fans, via `ipmitool raw 0x30 0x30` | `/usr/local/sbin/fan-watchdog` |
| `ryuji-fan-guard` | ryuji | Gigabyte MD70-HB0 BMC (Avocent) fan offset, via the BMC's own web API | `/usr/local/sbin/ryuji-fan-guard` |
| `makoto-fan` | makoto | its CPU heatsink fan and case fan, via the ASRock Rack BMC (`ipmitool raw 0x3a 0x01`) | `/usr/local/sbin/makoto-fan` |

`monitoring/` puts the controllers' readings into Prometheus, with a Grafana dashboard and alert rules (see
`monitoring/README.md`).

These are written for the exact machines below, not for a hardware family in general. Every temperature threshold,
fan curve and timing came from measuring these boxes in this room. Read "Hardware" and "Using this on other
hardware" before running any of it anywhere else.

## Hardware

Recorded 2026-10-06, makoto 2026-10-19 (read with `dmidecode`, `lscpu`, `lspci`, `lsusb`, `ipmitool mc info`,
`sg_inq`, `lsblk`). The controller hosts run Ubuntu 24.04.5 LTS (kernel 6.8), Python 3.12, ipmitool 1.8.19,
smartmontools 7.4, sg3-utils 1.46, python3-serial 3.5.

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
| Power | One working PSU (PS2). PS1 is a unit with a failed fan, left in its bay uncorded as a blank (the R720 needs a PSU or a blank in every bay for its airflow); the iDRAC reports it, expected |
| Serial adapter | FTDI FT232R USB-UART (USB ID 0403:6001), `/dev/ttyUSB0`, to the MD1200's top EMM |

### MD1200 shelf (controlled from mementos by `md1200-fan`)

| Part | What is installed |
|---|---|
| Enclosure | Dell PowerVault MD1200 (2U, 12x 3.5" bays), SES product revision 1.06 |
| EMMs | 2 EMMs, firmware 1.06. The TOP EMM is the primary; the bottom EMM is secondary and carries the SAS links |
| Drives | 11x Seagate ST8000NM0075 and 1x ST8000NM0185 (8 TB 7.2K SAS), ZFS `dataPool` raidz2 |
| Fans | No separate fan modules: 2 PSU/cooling modules with 2 fans each, set together as one % |
| Fan speeds | Measured: 10% 2,330 rpm, 15% 2,800, 20% 3,290, 25% 3,770, 30% 4,250; firmware default about 5,000; thermal ramp about 7,600 |
| Control path | EMM serial console at 38400 baud, 8N1 (pyserial defaults), from the FTDI adapter on mementos; SES (`sg_ses`) through the H810: the sg number moves (`/dev/sg39` until 2026-10-13, `/dev/sg38` since), so md1200-fan finds it by type |
| Slot layout | Slot 0 top left, 3 rows of 4. The hottest drives sit in the middle row, not the top row under mementos |

### ryuji: Gigabyte MD70-HB0 (runs `ryuji-fan-guard`)

| Part | What is installed |
|---|---|
| Server | Gigabyte MD70-HB0 board in a 2U 12-bay chassis, BIOS R09 |
| BMC | Avocent MergePoint, firmware 8.44 (IPMI and web UI; its clock runs on UTC) |
| CPUs | 2x Intel Xeon E5-2696 v4 since 2026-10-12 (Broadwell-EP, an OEM E5-2699 v4: 22 cores / 44 threads each, 2.2 GHz base, up to 3.7 GHz on a few cores; the BIOS sets 150 W PL1 / 180 W PL2 per package; microcode 0xb000040). The BMC warns at 82C and is critical at 85C for these CPUs. Before: 2x E5-2650 v3 (Haswell-EP, 10 cores, 105 W), which ryuji-fan-guard v2.3 and earlier were tuned for |
| Memory | 8x 16 GB DDR4-2133 (Kingston 9965640-001), 128 GB |
| Drives | Since 2026-10-15: 2x Toshiba MG04ACA400N (4 TB 7.2K SATA) as one ZFS mirror (`computePool`; four more went to sojiro), four older MG04ACA (2x 4 TB, 2x 2 TB) in the other front bays, not in use; 1x Kingston SUV400S (120 GB SSD, boot). The 1 TB 2.5-inch HGST in the rear was removed on 2026-10-14 |
| Power | One FSP Group FSP800-20ERM (800 W, 80 PLUS Platinum, one small fan, no PMBus reading in the BMC). Its fan's tone under load is ryuji's main noise. A second supply (load sharing) was tried 2026-10-14/16: the same at idle, louder at 11 workers, quieter at 22-33 (see the results) |
| Storage controller | Broadcom/LSI SAS3008 |
| Fans | `CPU0_FAN`, `CPU1_FAN`, `SYS_FAN1`-`SYS_FAN4` (`SYS_FAN5` not connected). The BMC runs its own curve; the only setting it exposes is a PWM offset (-127 to 127) added to that curve |
| Limiting sensors | At idle `SIO Temp 1` (BMC warns at 80C, critical 85C), which follows system-fan airflow more than CPU load; under load the CPUs (CPU1 runs ~10C hotter than CPU0 at the same 150 W: 74 vs 63C at full load and -80) |

### makoto: Xeon D-1622 board with an ASRock Rack BMC (runs `makoto-fan`)

| Part | What is installed |
|---|---|
| Server | Small desktop chassis, external 250 W power brick (no PSU fan). BIOS L0.07 (2020-11-16) |
| BMC | ASRock Rack (IPMI manufacturer 49622, product 0x0202), firmware 0.06. No fan settings in the BIOS or web UI; it takes ASRock Rack's older OEM commands (`raw 0x3a 0x01` / `0x02`); the newer AST2500 set (`0x3a 0xd6`-`0xda`) answers "invalid command" |
| CPU | Intel Xeon D-1622 (4 cores / 8 threads, 2.6 GHz, 3.2 GHz turbo), RAPL PL1 40 W / PL2 48 W, TjMax 105C (coretemp high 83C). The BMC warns at 91C |
| Memory | 2x 16 GB DDR4 (Kingston 9965754-008, rated 2666, runs at 2133), BMC sensors `DDR4_A Temp` / `DDR4_B Temp` (warn 84C) |
| Drives | 3x Crucial MX500 1 TB SATA SSD (ZFS `backupPool` raidz1), 1x Crucial P310 500 GB NVMe (boot; warns at 83C) |
| Fans | `FAN1` (CPU heatsink) and `FAN4` (case) on the board's headers; `FAN2`/`FAN3` empty. Neither stalls down to 1% duty |
| Other sensors | `MB Temp` (warn 65C) and `Card Side Temp` (warn 60C), the board sensors the case fan has to keep cool at idle |

### The rack and the room

- One rack in a living room, bottom to top: the MD1200, mementos, ryuji, then other gear; a CyberPower PDU20SW8FNET
  on a 20 A circuit with nothing else on it (its NEMA 5-20 plug reaches a 15 A outlet through an adapter). About
  700 W at idle; 12.9 A at most with everything at full load. sojiro, a Xeon D-1521 backup box with no fan
  controller, sits behind the rack with its BMC fan offset at -80 (set once with
  `ryuji-fan-guard/gbt-fan-offset.py`; the BMC keeps it).
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
- **makoto-fan** needs an ASRock Rack BMC that takes the older `raw 0x3a 0x01` fan command (tested: firmware 0.06;
  `raw 0x3a 0x02` must answer 8 bytes; newer AST2500 firmware uses `0x3a 0xd6`-`0xda` instead). Map bytes to
  headers one at a time below the BMC's own duty (`testing/makoto/map-test.sh`) and check that 1% does not stall
  your fans. The sensor names (`Card Side Temp`, `MB Temp`, `DDR4_A/B Temp`), the curves, `CARD_TARGET` and the
  CPU feedforward are fitted to this board, a 40 W Xeon D under one heatsink fan, and this case.
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
- Levels: -127 (heavy: a heavy job while the CPUs allow, v2.10), -80 (quiet: idle, light loads and full load since
  v2.7; v2.4-v2.6 used -60 for a light load, v2.3 -40), -16 (system fans follow load), 0 (Performance; also for hot
  drives, v2.8), 127 (Full Speed).
- -80 under any load (v2.7). With ryuji in the rack (2026-10-14, room 23-24C, mic about 4 ft from the rack front,
  20 min A/B/A holds with the load held through, last 10 min against the idle floor): 2 threads -80 +2.3 / -60
  +4.3 dB(A); 4 threads -80 +4.2 / -60 +4.1 to +4.9 / -40 +5.8; 11 workers -80 +3.9 / -60 +6.3 / -40 +9.1. More
  system-fan air moves the power-supply fan's whine below the 680-830 Hz band the rack and room ring at (to 560-660
  Hz), but in the rack the fans add more than the whine loses, and the lower tone is stronger (-70..-73 dBFS against
  -78..-81 at -80). Out of the rack (2026-10-12/13) -60 had matched -80 with the whine out of the band, so v2.4-v2.6
  used it for a light load (2 or more busy threads under 160 W of package power); v2.3 used -40 for the E5-2650
  v3s. A BMC left at -60 goes back to -80 at once.
- -127 for a heavy job (v2.10): at least 2 busy threads and 220 W or more of package power (RAPL, both CPUs; v2.10:
  180 W) for 5 readings in a row, with the hottest CPU at 72C or lower; back to -80 when the hottest CPU reaches 77C
  on 2 readings
  (or on the SIO1 / VR / DIMM rules; then 15 min before -127 again) or when the package power stays under 200 W (v2.10:
  160 W) for 5 readings (the job ended). Under a heavy job the BMC's own curves drive the fans hard and the offset still
  shifts them. Measured 2026-10-15 in the rack (room 24C, 20 min A/B/A holds at -80 / -127 / -80, last 8 min):
  22 workers -62.4 / -64.1 dB(A), 1.6 dB quieter, hottest CPU 67 / 71C; 33 workers -56.4 / -60.1, 3.7 dB quieter,
  70 / 75C; 44 workers -49.6 / -57.0, 7.4 dB quieter, 73-74 / 77-78C (VR 84C). At idle -127 equals -80. A full
  load would sit at 77-78C at -127, 4-5C under the BMC's warning, so it stays at -80 (74-75C): the 72C entry line
  keeps it there. Those holds ran on two power supplies. On one (v2.11, 2026-10-16, same A/B/A): 22 workers -80
  -61.95 / -127 -60.28 / -80 -62.02 dB(A), so -127 is 1.7 dB louder there (less chassis air warms the lone supply and
  its tone drops from 973 Hz into the band at 809 Hz, 10 dB stronger), while 33 workers keep a 3.9 dB gain (-53.80 /
  -57.65 / -53.73). Hence the 220 W line (22 workers draw ~190 W, 33 ~250 W).
- Full load (44 workers, room 24C, no thermal throttling at any offset): hottest CPU 74C at -80, 72C at -60, 69C at
  -16 and at Performance, 65C at Full Speed; 534-617 W at the wall; 2,761-2,797 MHz on every core. So v2.5 holds a
  full load at -80, 8C under the BMC's warning, and goes to -16 only in a warm room (CPU 78C).
- -80 to -16 if SIO1 climbs past 77C under load or reaches 79C (for 2 min with the CPUs idle: a hot room), or a CPU
  reaches 78C, a VR 90C or a DIMM 75C. -16 to Performance if that is not enough. Full at SIO1 83C or CPU 83C
  (v2.4; 86C before, above the E5-2696 v4's 85C critical). Back to -80 from -16 after 10 idle minutes once SIO1 is
  72C or lower (30 min at 71C or lower after a hot room).
- Drives (v2.8): the hottest 3.5-inch spinning disk (smartctl attribute 194; a disk in standby or one that cannot be
  read is skipped) at 49C on 2 readings -> Performance, at 52C on 2 readings -> Full; from a drive-triggered Performance
  back to -80 after 10 min with the hottest disk at 46C or lower and the board and CPUs cool. At -80 with the CPUs
  idle the system fans stay at ~1,050 rpm, and a random-read job (~55 MB/s over the six MG04ACA400s, rated 55C) took
  the hottest from 47 to 50C in 6 min; Performance (~2,200 rpm) held it flat at 49-50C for 30 min, -8 let it reach
  51C (2026-10-14). Below -16 the system fans do not leave their floor at idle, so Performance is the step that
  works. 49C rather than 48: a 27C room idles the warmest disk at 47-48C at -80. Only disks that report "Form
  Factor: 3.5 inches" count (v2.9; every spinning disk if none does): v2.8 also read a spare 2.5-inch disk in the
  CPUs' exhaust, which reached 49C under an 11-worker CPU load with no disk job while the front-bay disks fell to
  38C, and went to Performance for 15 min.
- Idle means less than one logical CPU busy (`/proc/stat`) with VR and DIMMs cool (v2.3; before, the hottest CPU at
  50C or lower, which a light load at -40 in a cool room can undercut). The state file shows it as `threads`, and
  every level change logs it (v2.4).
- Re-checks the BMC offset every 30 min and puts its level back; temps unreadable for 5 min means Performance.
- At start it reads the BMC offset, retrying every 10 s for up to 2 min (v2.2): at boot ryuji's address is not
  usable yet when network-online.target is reached, which made that first read fail on 10-06 and 10-07. The unit
  wants network-online.target.
- Needs the BMC password in `/root/.bmc-pass` (0600, root only); the BMC web API needs legacy TLS.
  `gbt-fan-offset.py <bmc ip> get|set N` reads or sets the offset by hand (stop the guard first).
- Hardware: Gigabyte MD70-HB0, Avocent MergePoint BMC 8.44, 2x Xeon E5-2696 v4 since 2026-10-12 (v2.4 to v2.11
  are tuned for them); see "Hardware". The package-power lines (220 / 200 W) depend on this CPU pair and on running
  one power supply.

## makoto-fan (makoto)

- Two fans through the BMC's OEM command (ASRock Rack FAQ id 38): `ipmitool raw 0x3a 0x01 B1..B8`, one byte per
  header, 0 = the BMC's own curve, 1-100 = a fixed duty; `raw 0x3a 0x02` reads it back. Byte 1 = `FAN1`, byte 4 =
  `FAN4` (the others are empty headers). A fixed duty, not a floor: the BMC does not step in, even at 1%.
- `FAN1` (CPU heatsink) follows the CPU package temperature, smoothed so a few seconds of load do not rev it (rises
  with a 20 s time constant, falls with 60 s), with a fast path on the raw reading from 88C. `FAN4` (case) holds
  `Card Side Temp` at 50C (the BMC warns at 60) with a slow PI loop plus more air as soon as the CPU works, since
  the case takes 15-30 min to show it; DIMM, board, NVMe and SSD curves are backstops above it.
- Duties rise at once and fall only to the highest demand of the last 2 min, at 1% per 5 s; changes under 3% are
  not written. Any sensor at its emergency limit (CPU 95, DIMM 80, board 62, card side 58, NVMe 80, SSD 68C) sends
  both fans to 100% until all are 5C below.
- Fails to the BMC: on exit, a crash, an unreadable CPU sensor or 5 failed writes the fans go back to the BMC curve
  (the unit's `ExecStopPost` does the same). Without a fresh BMC reading for 3 min `FAN4` runs at least 50%. The
  setting is read back every 60 s and written again if the BMC dropped it.
- State: `/run/makoto-fan.state` (JSON, every 2 s), published by `monitoring/lab-thermal-textfile` as `lab_makoto_*`.

| Fan | 1% | 10% | 20% | 30% (BMC idle) | 40% | BMC curve, highest seen |
|---|---|---|---|---|---|---|
| FAN1 rpm | 1,800 | 2,300 | 3,000 | 3,600 | 4,100 | 7,000 |
| FAN4 rpm | 1,500 | 1,600 | 1,900 | 2,300 | 2,700 | 4,500 |

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
python3 -I ryuji-fan-guard/tests/test_ryuji_fan_guard.py ryuji-fan-guard/ryuji-fan-guard  # 50 scenarios (v2.11)
python3 -I ryuji-fan-guard/tests/test_guard_start.py ryuji-fan-guard/ryuji-fan-guard      # start-up retry (v2.2)
python3 -I makoto-fan/tests/test_makoto_fan.py                                             # 12 scenarios (v1)
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
- `tools/room-feed-local.sh` (2026-10-13): `room-feed.sh` run on ryuji itself (it reads Prometheus on futaba
  directly), so a reboot of the machine that runs the test session cannot stop the room reading a test depends on.

## Testing on the hardware

`METHODOLOGY.md` covers how the 2026-10-05/06 data was gathered, what went wrong (mainly a room that cycled 24-28C
while the AC struggled) and how to run the tests again: the shelf and mementos with the AC working, ryuji after the
E5-2696 v4 upgrade, noise with a microphone, and tinynas after its cage fan check. `testing/` has the scripts as they
ran (see `testing/README.md`; makoto's, 2026-10-19/20, in `testing/makoto/`).

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

## Results, 2026-10-12/13: ryuji on the E5-2696 v4s (room 23-25C, ryuji out of the rack)

2x Xeon E5-2696 v4 fitted 2026-10-12 (and the paste redone). All with `testing/ryuji-floor.py` (plans `v4light`,
`v4b`, `v4a2`, `v4c`, `v4idle`, `v24light`, `v4prof`, `v4heavy`, `v25val`, `v4half`, `v4bench`), `testing/phase-table.py`
(medians over each phase's last minutes, joined with turbostat and the mic), the mic 1.5 ft in front of the rack.
No thermal throttling (kernel counters) and no BMC event in any test.

Idle (guard -80, overnight 10-12/13): CPUs 37 / 43C (the E5-2650 v3s: 41-50C), SIO1 72C, CPU / system fans 2,000 /
1,050 rpm, 161 W at the wall; -70.0 dB(A) at the mic, the quietest night measured.

Light load (20-30 min holds, A/B/A): on these CPUs the BMC's own curve already lifts the system fans at 4 busy threads,
so SIO1 falls under load and v2.3's -40 step never fired, while the power-supply fan's tone still climbed into the
band the rack and room ring at.

| Load | -80 | -60 | -40 |
|---|---|---|---|
| 2 threads (~236 W) | -67.91 / -65.72 dB(A), 738-771 Hz (in the band) | -67.56, 738 Hz (in the band) | |
| 4 threads (~268 W) | -67.05 / -66.88, 782 Hz (in the band) | -67.06, 665 Hz (under it) | -65.91, 601-615 Hz |

Full-load profile (fixed offsets, 8 min holds, last 4 min; 44 workers = one per core puts both CPUs at their 150 W
limit; 88 workers add nothing):

| Workers (package W) | Offset | Hottest CPU | VR | CPU / system fans | Wall W | All-core MHz | dB(A) | PSU tone |
|---|---|---|---|---|---|---|---|---|
| 22 (188) | -80 | 66C | 68C | 4,600 / 2,525 | 368 | 2,795 | -65.09 | 729 Hz, in the band |
| 22 (190) | -60 | 64C | 69C | 4,800 / 2,975 | 370 | 2,795 | -65.47 | 442 Hz (the PSU not yet warm) |
| 22 (186) | -16 | 59C | 61C | 5,500 / 4,550 | 374 | 2,794 | -58.72 | 721 Hz |
| 22 (184) | Performance | 59C | 60C | 6,000 / 5,350 | 379 | 2,792 | -55.98 | |
| 33 (246) | -80 | 70C | 74C | 5,700 / 4,750 | 457 | 2,797 | -58.21 | 820 Hz |
| 33 (245) | -60 | 68-69C | 71-73C | 5,700-5,900 / 4,925-5,125 | 457 | 2,797 | -57.27 (A/B/A mean) | 817-820 Hz |
| 44 (296) | -80 | 74C | 80C | 6,300 / 5,900 | 534 | 2,761 | -53.01 | 899 Hz |
| 44 (296) | -60 | 72C | 78C | 6,500 / 6,225 | 538 | 2,771 | -50.30 | 920 Hz |
| 44 (293) | -16 | 69C | 74C | 6,900 / 7,225 | 554 | 2,771 | -48.30 | 949 Hz |
| 44 (293) | Performance | 69C | 73C | 7,300 / 7,900 | 565 | 2,774 | -45.97 | |
| 44 (293) | Full Speed | 65C | 67C | 8,400 / 9,800 | 617 | 2,795 | -41.27 | |

With 20 min holds at 22 workers (A/B/A, load held through, last 10 min) the power supply warms and its tone sits in
the band at both offsets: -80 -64.47, -60 -64.00, -80 -64.41 dB(A) (735-768 Hz). So -60 pays only for a light load
(2-4 busy threads), which is where ryuji-fan-guard v2.6 draws the line (160 W of package power).

The hottest CPU is always CPU1, ~10C above CPU0 at the same power (worth checking its heatsink and paste). The rack
PDU read 9.8-10.1 A with ryuji at full load (6.2-6.5 A at idle).

7-Zip 23.01 benchmark (`testing/bench-7zip.sh`, `7z b`, total rating in MIPS): ryuji 5,021 on one thread, 113,495 on
44, 179,809 on all 88; tinynas's Ryzen 5 9600X, same version: 7,644 on one thread, 70,305 on all 12. ryuji is about
two thirds of the 9600X per thread and does about 2.6 times its work in total.

Guard v2.5 live (`v25val`): from idle, a 30 min full load stayed at -80 the whole time (hottest CPU flat at 74C, VR
80C, 538 W, -53.00 dB(A)); 22 workers took it to -60 1.6 min in; growing to 44 workers took it back to -80 5 min
later; four 3 min full-load bursts 4 min apart changed nothing; back to -80 10 idle min after each load. v2.6 keeps
that logic with the line moved to 160 / 180 W.

## Results, 2026-10-13/16: the final rack (room 22-25C)

The rack in its final form for 72 hours (bottom to top: the MD1200, mementos, ryuji, racked for the first time;
sojiro about 3 ft behind it), with idle, light, medium, heavy and combined loads. Every step ran as a persistent
systemd unit on its host, chained across hosts by `testing/fin-gate.py`, with backstops and a load cut on the rack
current (`testing/pdu-cut.sh`). The mic sat on a mattress about 4 ft from the rack front, so its numbers compare only
within this run: the idle floor there is -69.5 dB(A) (-70.0 on the quietest night). Rohit's goal for the run: as
quiet as possible at all times, not audible from the living room or the kitchen (or mistakable for the A/C), with no
throttling and nothing sitting just under its limit. No thermal throttling and no BMC event in any test.

### ryuji: ryuji-fan-guard v2.6 to v2.10

Light loads, ryuji in the rack (20 min A/B/A holds, load held through, last 10 min against the idle floor):

| Load | -80 | -60 | -40 |
|---|---|---|---|
| 2 threads | +2.3 dB, tone 750 Hz at -80 dBFS | +4.3 dB, 636 Hz at -73 | |
| 4 threads | +4.2 dB, 715 Hz at -79 | +4.1 to +4.9 dB, 592-639 Hz at -72 | +5.8 dB, 609 Hz at -71 |
| 11 workers | +3.9 dB, 738 Hz at -78 | +6.3 dB, 656 Hz at -70 | +9.1 dB, 560 Hz at -74 |

More system-fan air moves the power supply's whine below the 680-830 Hz band the rack and room ring at, but in the
rack the fans add more than the whine loses, and Rohit heard the -40 step from the living room. Hence v2.7: -80 under
any light load.

Drives: at -80 with the CPUs idle the system fans stay at ~1,050 rpm, and random reads (~55 MB/s over the six
MG04ACA400s) took the hottest from 47 to 50C in 6 min. Performance (~2,200 rpm) held it flat at 49-50C for 30 min; -8
reached 51C. Hence v2.8 (Performance for a hot data disk); v2.9 counts only the 3.5-inch disks after a spare 2.5-inch
disk in the CPU exhaust (49C under an 11-worker CPU load, no disk job) triggered it falsely. The live check went to
Performance 4 min into a soak, held the disks at 50C and came back 14.5 min after it.

Idle offsets (3 min holds against -80 on either side): -127 and -60 0.0 dB, -40 +0.3, -16 +1.1, 0 (Performance) +2.5.

Heavy loads (20 min A/B/A holds at -80 / -127 / -80, last 8 min):

| Workers | dB(A) at -80 / -127 | Hottest CPU | VR | System fans |
|---|---|---|---|---|
| 22 | -62.44 / -64.05 (1.6 dB quieter) | 67 / 71C | 71 / 75C | 3,175 / 2,475 rpm |
| 33 | -56.42 / -60.08 (3.7 dB) | 70 / 75C | 74 / 80C | 4,275-4,750 / 3,875 |
| 44 | -49.62 / -57.00 (7.4 dB) | 73-74 / 77-78C | 79-81 / 84C | 5,650-6,125 / 4,525 |

Hence v2.10: -127 for a heavy job while the hottest CPU allows. Its first long run, 33 workers for two hours under the
guard: -127 from 5.5 min in to 6 min after the load, the hottest CPU flat at 75C (76C at most) in every 20 min block,
VR 80C, 452 W at the wall. A full load stays at -80 (74-76C over 100 min in the combined test).

Those holds ran on two power supplies. ryuji now runs on one, and the same A/B/A on Friday flipped the 22-worker case:
-80 -61.95 / -127 -60.28 / -80 -62.02 dB(A), because less chassis air warms the lone supply and its tone drops from
973 Hz (above the band, -74 dBFS) into the band at 809 Hz (-63 dBFS). 33 workers keep a 3.9 dB gain (-53.80 / -57.65 /
-53.73). Hence v2.11: -127 only from 220 W of package power (about 28 busy threads; 22 workers draw ~190 W, 33 ~250 W).

Friday's validation on one supply, the guard in control (15-20 min holds, against the day's idle floor of about -69.0):
2 threads +2.4 dB, 4 threads +3.8, 11 workers +5.3 (all at -80), 22 workers at -127 +8.9 (v2.10; v2.11 keeps -80
there), 33 workers at -127 +12.1, 44 workers +20.1 (back to -80 at 77C, 2.3 min in). No cycling, no throttling.

Two power supplies (both FSP800-20ERM, load sharing) against one: the same at idle over a whole night (+0.06 dB);
louder at 11 workers on Wednesday (about 3 dB, an evening with house sounds); quieter at 22-33 workers on Friday's
comparison (2.6-3.4 dB: each supply's fan runs slower, 601-694 Hz at -72..-76 dBFS against 823-858 Hz at -63/-64 with
one); the same at full load. ryuji runs on one, and the guard is tuned for that.

### mementos: fan-watchdog v4.2 (unchanged)

| Busy threads | Fans (max) | CPU (max) | dB(A) over the floor |
|---|---|---|---|
| 0 | 10% | 49-51C | 0 |
| 6 | 16% (17) | 71C (72) | +1.4 |
| 12 | 19% (20) | 73C (74) | +1.7 |
| 18 | 23% (27) | 76C (78) | +2.4 |
| 24 | 32% (35) | 80C (82) | +4.6 |
| 36 | 31-32% (41-45 at the onset) | 80C (84-85 at the onset) | +4.3 |
| 48 | 31% (33) | 80C (81) | +4.2 |

A full load from idle overshoots: the iDRAC's CPU reading lags coretemp by ~40 s, so the fans answer a peak that has
already passed (2026-10-16, room 24C: 85C and 45% for about a minute, 31% two minutes later). Bursts of 0-18 workers
take the fans to 26-31% and the unwind is 1% per loop (16 min from 31%); no hunting. A faster unwind (4% per loop once
everything asks for the floor) was modelled with `testing/mementos-thermal-model.py` and `testing/fw-sim.py` and
dropped: mementos's real load (1.5-4 busy cores) never takes its fans off 10%.

### Shelf: md1200-fan v3.2 (unchanged)

Idle nights at 10% with the hottest drive at 49-50C (the first night's 13-14% was the warm-up after a cold start).
Random reads on all 12 drives for 1-2 hours (~120 MB/s) take the hottest from 49-50C to 53C in ~14 min; md1200-fan
answers with its urgent step (11 -> 16%) and nudges to 19-22%, after which the drives sit at 48-52C. Once, during the
combined test, the shelf firmware ramped its own fans for a few seconds; md1200-fan took them back.

### Noise per fan level at this spot (idle, A/B/A against the neighbouring references)

| Shelf (vs 15%) | dB | R720 (vs 10%) | dB |
|---|---|---|---|
| 10% | -0.6 | 15% / 20% / 25% / 30% | +0.3 / +1.1 / +2.4 / +3.2 |
| 20% | +0.6 | 35% / 40% / 41% | +5.5 / +9.0 / +7.6 |
| 25% | +2.1 | 42% / 43% / 44% | +9.9 / +11.3 / +12.4 |
| 30% / 40% | +3.4 / +7.1 | 45% / 50% | +13.2 / +13.8 |

The R720's loud zone now starts at 42% (blade rate 724-760 Hz, in the ringing band); the 38-40% hump of 10-08 is a
small bump here.

### Everything at once, and the circuit

ryuji at 44 workers, mementos at 24 then 48, and random reads on every pool for an hour: the rack PDU read 6.1 A at
idle, 9.1-9.2 with ryuji at full load, 11.2-11.3 with mementos at 24 workers, 12.6-12.8 with everything (12.9 A peak).
Every temperature stayed inside its limits. At the mic the rack measured -49.0 dB(A), and ryuji alone at full load
-49.6: its power supply's whine (890-935 Hz) is the sound. The PDU's NEMA 5-20 plug reaches a 15 A outlet through an
adapter, and 12.6-12.8 A for an hour is past the 80% continuous guideline for it; real use draws about 6 A.

### sojiro

sojiro's BMC (the same Avocent firmware as ryuji's) never takes its CPU fan below 3,100 rpm (3,400 at offset 0), and
its system fan already sits at its 600 rpm floor. Offset steps at idle: 0 3,400 rpm / 62C, -31 3,300 / 64C, -61 to
-127 3,100 / 65-67C; the rack mic heard none of it. It runs at -80 (set with `gbt-fan-offset.py`; the BMC keeps it
through reboots). Load check, a 50 min scrub of its pool: CPU 74C (package 79C, critical 102C), board sensor 72C,
drives 46C.

### Listening test (Rohit, Thursday evening)

From the living room, mementos at 30% (its high and full-load level) is "pretty audible" and "what high (not full)
load would sound like", which he accepts; at 20-25% (its medium-load levels) it is lost in the idle rack. ryuji at a
medium load (11 workers, -80, two supplies at the time) "almost sounds like a small plastic gear spinning very fast"
(the power supply), and once warm, heard from the floor in front of the rack, it was "the medium load noise i want
ideally": about +6 dB(A) at this mic.
### What ryuji can do (2026-10-16, `testing/ryuji-maxbench.sh`)

7-Zip 23.01 (`7z b`, total rating in MIPS): 4,957 on one thread, 9,712 on 2, 17,502 on 4, 32,114 on 8, 44,160 on 11,
75,253 on 22, 96,470 on 33, 115,367 on 44 (one per core), 151,501 on 66 and 181,403 on all 88. Flat out for 15 minutes
under the guard it holds 182,000-186,000 with every core at 2.8 GHz (the E5-2696 v4's all-core turbo, ~139 W per
package, under the 150 W PL1), 519-550 W at the wall, the hottest CPU at 74C (78C at most). The same at Full Speed
fans: +0.5% (within run-to-run spread), the CPUs 12C cooler, 85 W more at the wall: cooling buys nothing here.
Memory bandwidth (stress-ng stream, 44 copies): 59.1 GB/s read + 39.4 GB/s write = 98.5 GB/s (8 channels of
DDR4-2133). openssl 3.0.13 on 88 processes: AES-256-GCM 119 GB/s (one thread 3.45), SHA-256 16.2 GB/s, RSA-2048
57,961 signs/s. sysbench cpu: 487 events/s on one thread, 24,598 on 88. The standard run for the comparison table
(`testing/bench-7zip.sh`'s procedure): 4,991 / 113,283 / 174,086 on ryuji, 4,152 / 68,217 / 103,448 on mementos.

## Results, 2026-10-19/20: makoto (room ~23C)

- Fans: byte 1 = FAN1 (CPU heatsink), byte 4 = FAN4 (case); a fixed duty the BMC never overrides, no stall at 1%,
  no BMC events from the mapping.
- Which fan cools what: at idle FAN4 moves every sensor (2,300 -> 1,500 rpm: +3-6C); under 2 workers (~21 W) FAN1
  3,500 -> 1,700 rpm took the CPU from 82-84 to 89-91C within a minute.
- Idle needs case air: FAN4 at 20-25% holds Card Side Temp at 50C. FAN1 can idle at 1%, but makoto's own bursts
  (Claude sessions, mirror-voice) took a fixed 1% to 85-94C, so it needs the closed loop.
- CPU cooling: stress-ng tops out at ~24 W on this CPU (4 and 8 workers alike) and 70-79C (table below), but a heavy
  mirror-voice job ran 83-88C even at the BMC's 6,900 / 4,500 rpm (case warm from a test), so real work can draw
  more. A cleaned heatsink and fan would buy margin there.
- Noise: the mirror's Pi mic, next to makoto, cannot hear it at normal speeds (broadband flat from FAN1 2,000 to
  7,000 rpm); both fans near the BMC's top add 1.2-1.4 dB(A).
- BMC event log: one CPU1 91C warning (a FAN1-at-1% test under other load), cleared 30 s later.

v1 as a trial (unit `makoto-fan-test`, 2026-10-20 00:17-06:50, no restarts, no failed writes):

| Load | FAN1 | FAN4 | CPU | Card Side |
|---|---|---|---|---|
| Idle, ~3 W | 1%, 1,700 rpm | 21-30%, 1,900-2,300 rpm | 55-57C | 50-51C |
| Bursts of ~11 W, 1-3 min | up to 28%, 3,400 rpm | up to 41%, 2,700 rpm | 69-74C | 50-51C |
| mirror-voice's heavy job, ~21 W | 47-54%, 4,600-4,900 rpm | 53-63%, 3,300-3,500 rpm | 76C (smoothed) | 50-51C |
| The BMC's own curve, idle | 30%, 3,600 rpm | 30%, 2,300 rpm | | |

Full load, 2026-10-20 13:15-14:52 (`testing/makoto/day1.sched` fixed fans, then `day1b.sched` with v1 in control;
stress-ng matrixprod, last 3 min of each step). No emergency, no BMC event; 15 min after the load v1 was back at
FAN1 1% / FAN4 28%. v1 is production since 2026-10-20 14:54.

| Load | Fans | FAN1 / FAN4 rpm | CPU | Card Side |
|---|---|---|---|---|
| 8 workers (24 W), fixed | 100 / 100% | 6,900 / 4,500 | 70-72C | 46C |
| 8 workers (24 W), fixed | 100 / 50% | 6,900 / 3,000 | 75C | 50C |
| 4 workers (24 W), fixed | 60 / 60% | 5,300 / 3,400 | 76C | 50C |
| 2 workers (16 W), makoto-fan | 39 / 47% | 4,100 / 2,900 | 74C | 51C |
| 4 workers (24 W), makoto-fan | 58 / 61% | 5,100 / 3,400 | 78C | 51C |
| 8 workers (24 W), makoto-fan | 61 / 63% | 5,300 / 3,500 | 78-79C | 52C |
