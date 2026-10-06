# Fan control

Quiet fans for the rack without hurting the hardware: as quiet as possible at idle and light load, a medium level
under heavy work, loud only at full load or when something is genuinely hot. Built and tested 2026-10-04 to
2026-10-06; `git log -p fan-control/` shows each version and why it changed.

| Controller | Runs on | Controls | Installs to |
|---|---|---|---|
| `md1200-fan` | mementos | MD1200 shelf fans, via the EMM serial console (`_shutup <pct>` over an FTDI adapter, `/dev/ttyUSB0`, cable on the TOP EMM) | `/usr/local/bin/md1200-fan` |
| `fan-watchdog` | mementos | Dell R720xd fans, via `ipmitool raw 0x30 0x30` | `/usr/local/sbin/fan-watchdog` |
| `ryuji-fan-guard` | ryuji | Gigabyte MD70-HB0 BMC (Avocent) fan offset, via the BMC's own web API | `/usr/local/sbin/ryuji-fan-guard` |

## md1200-fan (MD1200 shelf)

- Holds the hottest shelf drive near 48.5C, with backplane 46C, SIM 58C and expander 86C as guards. Steps 1-2% up at
  most every 10 min and 1% down at most every 20 min, because the drives take 30-60 min to settle after a change.
- Urgent: +5% every 30 s at drive 52, backplane 48, SIM 61 or expander 90C. Floors of 60-80% near the hard limits.
- Only commands the primary EMM (checks `_who`). The cable must be on the TOP EMM: the bottom one is secondary, and
  a command sent to it only lasts about 15 s before the primary takes over.
- Re-sends every 2 s as insurance against the shelf firmware's own thermal ramp (a single command to the primary
  held for 45 min in testing), checks the echo, and compares the SES fan speed (`sg_ses -p 2`) with the expected one.
- Never send `_shutup` below 10. Never hot-insert or remove EMMs or PSUs (the shelf loops resets until power-cycled).
- Measured at a ~26C room: 15% puts the hottest drive at ~51-52C, 20% at ~48.5C, 25% at ~44C. It settles around
  17-22% at 26-27C and lower when the room is cooler. Stop it and the shelf goes back to its own ~5,000 rpm default.
- Needs python3-serial, sg3-utils, smartmontools.

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

## ryuji-fan-guard (ryuji)

- ryuji's limiting sensor is SIO Temp 1 (the BMC warns at 80C). It follows the system fans, which stay at their
  ~1,050 rpm floor at offset -80 until the CPUs pass 65-70C. Full load is fine at -80 (the BMC raises the system
  fans itself); light-to-moderate load in a warm room is what pushes SIO1 up.
- Levels: -80 (quiet, normal), -16 (system fans follow load), 0 (Performance), 127 (Full Speed).
- -80 to -16 when SIO1 reaches 79C for 2 min, or is at 77C or more and has risen 1C over 5 min while the CPUs are
  busy, or a CPU reaches 78C, a VR 90C or a DIMM 75C. -16 to Performance if that is not enough. Full at SIO1 83C or
  CPU 86C. Back to -80 after 10 idle minutes once SIO1 is 72C or lower (30 min at 71C or lower after a hot room).
- Re-checks the BMC offset every 30 min and puts its level back; temps unreadable for 5 min means Performance.
- Needs the BMC password in `/root/.bmc-pass` (0600, root only); the BMC web API needs legacy TLS.
  `gbt-fan-offset.py <bmc ip> get|set N` reads or sets the offset by hand (stop the guard first).

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
fan-watchdog/tests/run-tests.sh                                                        # about 2 minutes
python3 -I ryuji-fan-guard/tests/test_ryuji_fan_guard.py ryuji-fan-guard/ryuji-fan-guard  # 12 scenarios
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

## Testing on the hardware

`METHODOLOGY.md` covers how the 2026-10-05/06 data was gathered, what went wrong (mainly a room that cycled 24-28C
while the AC struggled) and how to run the tests again: the shelf and mementos with the AC working, ryuji after the
E5-2699 v4 upgrade, noise with a microphone, and tinynas after its cage fan check. `testing/` has the scripts as they
ran (see `testing/README.md`).

## Results, 2026-10-06 (room 24-28C)

Measured while the room cycled; to be repeated with the AC working (see `METHODOLOGY.md`).

| Box | Idle | Heavy load |
|---|---|---|
| MD1200 shelf | 17% (~3,000 rpm), hottest drive 48C | full scrub: 17-22%, no drive above 50C |
| mementos | 10%, CPUs ~52C, 290 W | full load 32-35%, CPUs 79-82C, ~548 W |
| ryuji | -80, CPU/system fans 2,300/1,050 rpm, SIO1 77-78C, ~150 W | full load at -80: 4,900/3,200 rpm, SIO1 55C, CPUs 60/70C, ~360 W |
