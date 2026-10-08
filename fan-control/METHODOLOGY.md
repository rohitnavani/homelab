# Fan and thermal testing: methodology

How the 2026-10-05/06 fan work was measured, what went wrong, and how to run it again: with the AC working, on
ryuji after the E5-2696 v4 upgrade, with a microphone for real noise readings, and on tinynas once its drive cage
has a fan. The test tools are in `testing/` (as used on 10-06, see `testing/README.md`) and `tools/`.

The short version: **verify the room first, log everything with epoch timestamps, change one thing at a time,
compare against a lagged room reference, size every phase to the slowest sensor that matters, map the hardware with
fixed fans before tuning a controller, and deploy every controller behind a watch that rolls it back by itself.**

## 1. The questions

| Box | What a test has to answer |
|---|---|
| MD1200 shelf | Hottest-drive equilibrium at each fan % (15/20/25%) for a given room; how fast it settles; whether the controller lands there and stays |
| mementos (R720xd) | Fan % each load needs (idle, 12, 18, 48 workers); a full load started from idle; the unwind after load; DIMM and drive temps under load |
| ryuji | SIO Temp 1, CPUs, VRs and DIMMs across BMC offsets x loads; what the guard does under real load; after the CPU swap, whether its thresholds still fit |
| tinynas | Which fan (if any) cools the drive cage, and by how much |
| Noise | Which box is loudest at idle and at each fan step, in measured dB at a listening spot |

## 2. Before any test

1. **Check the room.** The room was the biggest confound on 10-05/06. The AC cycled about hourly, the room swung
   24-28C, and the rack alone puts out about 700 W at idle (PDU 5.7-5.8 A) on top of the boxes outside it. Run
   `testing/ac-verify.py <HH:MM> 10` over the previous 2-3 hours: it lines up independent room proxies on four
   machines (mementos iDRAC inlet, sojiro MB_TEMP1, tinynas SYSTIN and NVMe, makoto MB and card-side temps) with the
   rack current, and only trusts a sensor while its own box's load and fans were steady. Start when they hold a flat
   band (within about 1C, no hourly sawtooth) at a temperature you can reproduce later. If the room cycles anyway,
   make phases whole multiples of the cycle and rely on the lagged reference (section 4).
   History helps here: two weeks of tinynas NVMe readings (its old Prometheus) showed the room flat and cool on the
   night of 10-03/04 with mementos, the shelf and ryuji all running, then an hourly cycle from 16:00 on 10-04 when
   the AC developed a fault (by 10-07 it cooled about 20 minutes an hour). A steady room looks like that night.
2. **Start the loggers** and confirm each one is writing:
   - Prometheus on the monitoring host already records the room reference, the fan controllers' readings, the BMC
     sensors of ryuji, sojiro and makoto, every host's hwmon temperatures and the rack PDU (`monitoring/README.md`,
     since 2026-10-07). Start with its "Lab - Thermal" dashboard; labmon is still needed for RAPL package power and
     per-test detail.
   - `testing/labmon.py` on every host (30 s, `/var/tmp/labmon.jsonl`): IPMI temps, fans and DCMI watts, hwmon,
     RAPL package watts per socket, CPU busy %, disk MB moved.
   - `tools/lab-inlet-guard.sh` on makoto: the mementos inlet every 60 s to `room.csv`, published to the test hosts
     as `/run/room-inlet` (the load scripts gate on it), switching test heat off above the room limit.
   - Rack PDU current by SNMP GET (never SET) every 10 s. The poller is kept out of the repo because it holds the
     PDU's address details. `testing/ac-watch.sh` every 5 min as a timer.
   - mementos DIMMs: `testing/dimm-log.sh` (memory-controller DIMMTEMPSTAT registers via `setpci`, read-only).
   - Test-specific loggers (section 3).
3. **Write the stop rules into the scripts before starting** (section 6), never rely on watching.
4. **Run a 60 min idle baseline** under the production controllers, and another at the end of the day. Compare them
   with `testing/baseline_compare.py 02:20-03:00 14:30-15:30` (any two windows, local time, today).
5. **Check `date` on each host and log epoch seconds.** ryuji's OS and BMC clocks run on UTC; mementos, sojiro,
   tinynas and makoto on local time (EDT), but fan-watchdog stamps `/run/fan-watchdog.state` in UTC. Guessed times
   caused several confused readings on 10-06.
6. **Keep the boxes otherwise quiet.** During the 10-06 overnight run another session copied and compared VM images
   on mementos and started a 4 vCPU VM. Log any such activity, and keep heavy jobs off a box under test.
7. **Check the shelf's SES device** is still `/dev/sg39` (md1200-fan and the shelf scripts use that path): the SES
   device is the `scsi_generic` entry whose `device/type` is 13 (DELL MD1200).

## 3. How the data was gathered

| Source | What | Cadence | Notes |
|---|---|---|---|
| labmon (every host) | temps, fans, DCMI W, RAPL W, CPU busy, disk I/O | 30 s | the backbone; join everything on epoch |
| Room | mementos iDRAC inlet | 60 s | 1C steps; cross-check with ac-verify's other proxies |
| Shelf | hottest drive, backplane, SIM, expander, fan % and rpm | 30-60 s | from `/run/md1200-fan.state` while the controller runs; `testing/scrub-log.sh` adds every shelf drive; during experiments the experiment owns the serial port and reads `_temp_rd` itself |
| Shelf fan speed | SES `sg_ses -p 2 /dev/sg39` | on demand | ground truth for "did the command hold" |
| mementos | fan-watchdog state line, DIMMs, DCMI W | 15-60 s | `testing/mementos-steps.py` and `testing/mementos-fixedfan.py` log their own CSVs |
| ryuji | guard state, profile CSV, HDD temps | 30-60 s | `tools/ryuji-profile.py` (30 s), `testing/hdd-temp-log.sh` (60 s) |
| tinynas | pwm values and modes, fan2, Tctl, SYSTIN, NVMe, each HDD | 60 s | `testing/tinynas-cage-test.sh` |
| Power | rack PDU current; per-server DCMI; per-socket RAPL | 10-30 s | the PDU sees only the rack circuit |

**Load generator:** `stress-ng --cpu N --cpu-method matrixprod` at 100% per worker (steady heat; the default method
cycles through very different workloads). Step by worker count: a few workers (a light job or small VM), then half,
three quarters and all of the cores. Do not duty-cycle every core: `--cpu-load 10` on all 40 of ryuji's threads drew
about 80 W of package power (260 W at the wall), which is not a light load. On ryuji the hyperthreads added nothing
with matrixprod, so full load = one worker per physical core; on mementos 48 workers (every thread) was the full
load. A real workload is the best validation for the shelf: the dataPool scrub (about 970 MB/s for 46 min).

## 4. Experiment design

- **One variable at a time.** Hold the others in a fixed, logged state.
- **A/B/A.** Return to the baseline after every change; the second baseline tells you whether the "effect" was the
  room. On 10-06, R720 fans 10% -> 15% looked like 0.3C of shelf cooling until going back to 10% showed it was drift.
- **Compare rise over a lagged room reference**, not raw temperatures: temperature minus an exponential moving average
  of the inlet with a time constant near the sensor's own (30-60 min for shelf drives).
  `testing/analyze_exp3_lagged.py` does this.
- **Size phases to the slowest sensor that matters** (measured 10-05/06):

  | Sensor | Settling | Phase length |
  |---|---|---|
  | Shelf drives, backplane | time constant 30-60 min (fits ranged 24-90 min) | 60 min, then fit an exponential for where it was heading |
  | R720 CPUs and fan curve | 2-3 min (a full load from idle reached 84-85C within about a minute under v3) | 8 min |
  | R720 DIMMs, exhaust | 5-8 min | 8-10 min |
  | ryuji SIO Temp 1 | time constant ~3.5 min when the system fans change; ~10 min climbing at -80 from a cool start | 10 min idle, 6-8 min loaded |
  | tinynas HDDs | roughly 15-30 min (estimated from the 20 min header phases) | 20 min A/B/A |

- **Map the hardware with fixed fans first.** Hold the fans at fixed levels and step the load
  (`testing/mementos-fixedfan.py`; the overnight shelf run did the same at 15/20/25%). The map shows the quietest level
  each load needs; a controller's job is then to land near it, and its tests can be judged against the map.
- **Test transients separately:** a full load started from idle (the onset is what used to trip mementos into
  iDRAC auto), the unwind after load, and a room change.
- **Gate heat on the room.** A load step waits until `/run/room-inlet` is at or below a start threshold, drops its
  load above a stop threshold or when the reading is more than 3 min old, and is skipped after a maximum wait. If the
  room cycles, heavy steps land in its troughs. One heat source at a time unless combined heat is the question.
- **Integer sensors:** most readings move in 1C steps. Average many samples, repeat a step before believing a 1C
  difference, and fit exponentials instead of reading single points.

## 5. Controller development loop

1. **Offline harness with a plant model calibrated from data.** The first md1200 harness assumed the shelf settles
   in 15 min; it really takes 30-60, and v3 cycled 16-27% live. Sweep the uncertain parameters (shelf lag 15-90 min,
   the room's hourly cycle) and judge designs by changes per hour and range, not one scenario.
   (`md1200-fan/tests/test_md1200_lag_*.py`, `ryuji-fan-guard/tests/`, `fan-watchdog/tests/run-tests.sh`.)
2. **Run scenarios long enough to reach every steady state.** v4.1's harness scenarios ended before the fans reached
   the 10% floor, so its "stuck at 11%" bug only showed in the afternoon idle baseline.
3. **Deploy behind a watch** (`testing/deploy-examples/`): back up the running version, install, restart, watch
   10-45 min at idle, and roll back by itself on a crash loop, errors, takeovers, flapping or any emergency fallback.
4. **Load-validate live:** the load steps, a full load from idle, the unwind.
5. **Idle baseline after the load.** It catches controllers that never quite return to their idle state.
6. **Commit each version** with what changed and why.

## 6. Safety rules

- MD1200: only ever command the TOP (primary) EMM; check `_who`. Never send `_shutup` below 10. Never hot-insert or
  remove EMMs or PSUs. Never send `set_thres`, `nvramwrite`, `reset_peer`, `fpga_wr` or `_boot`.
- PDU: SNMP GET only. Its web UI or a SET switches the rack's power.
- IPMI: no guessed raw OEM commands. The R720 fan commands (`raw 0x30 0x30 ...`) are documented and used by
  fan-watchdog.
- BMC passwords only from 0600 files or stdin, never on a command line; stop after two failed logins.
- Every test unit restores production control on exit. Write the fallback as a script file: an inline
  `ExecStopPost=/bin/sh -c '... ${n} ...'` is expanded by systemd itself (write `$$` for a literal `$`), which
  silently broke the tinynas test's fallback on 10-06. Stop each new test unit once on purpose to prove its fallback.
- Set a test's own temperature stops from the controller's design range. The first v4 validation would have stopped
  the load at CPU 84C, cutting the onset test before v4's 82-88C range could act; it ran with 89C.
- `pkill -f` can match its own ssh command line; use `pkill -f "[p]attern"` or systemd units.
- While Rohit sleeps, or visitors are in, tests stay quiet: no full load, the R720xd under about 24%, the shelf
  under about 25%, no load on ryuji at all (4 busy threads spin its CPU fans to 3,700 rpm even at -80, +4.2 dB(A)
  at the mic spot), and `testing/noise-guard.sh` running against a quiet baseline (`testing/README.md`, "Quiet runs").
- Limits used on 10-06:
  - Room: test heat off above 27C (two readings in a row); raised to 29C for the later load tests after Rohit
    allowed a hotter room.
  - mementos: load off at CPU 89C, DIMM 75C, exhaust 60C; fixed-fan runs also set 60% fans at CPU 88C and iDRAC
    auto at 92C. The overnight shelf run's mementos load stopped at CPU 78C or DIMM 70C.
  - ryuji: load off at SIO1 80C, CPU 82C, VR 95C, DIMM 80C; Full Speed and exit at SIO1 83C or CPU 86C.
  - Shelf (overnight experiment): phase ends at a drive at 52C, backplane 47C, SIM 58C or expander 88C.

## 7. What went wrong on 10-05/06 and what changes

| What happened | Effect | Do this instead |
|---|---|---|
| AC cycled hourly, room 24-28C | raw temperatures unusable; ryuji test heat on a cycle peak took the room to 28C | verify the room with ac-verify first; lagged reference; room-gated load |
| Room logger read the inlet from fan-watchdog's state file | room went "unknown" whenever a test stopped fan-watchdog; a fixed-fan run lost its load | read the sensor directly (lab-inlet-guard now uses ipmitool) |
| Shelf harness assumed a 15 min lag | v3 cycled live | calibrate models from measured time constants; sweep them |
| v4.1 hysteresis never took the last step to 10% | mementos idled at 11% | long scenarios; idle baseline after load |
| Duty-cycled "10%" load on every thread | 80 W of package power, not a light load | step by worker count |
| 6 min phases for ryuji's SIO1 | some phases not settled | 10 min idle phases, or fit |
| fan-watchdog's 30 s loop really ~46 s (sensor reads take ~16 s) | larger onset overshoot than modelled | measure loop periods; test onsets explicitly |
| A test stop below the controller's range | would have hidden the result | set limits from the design |
| Inline ExecStopPost with `${n}` | fallback never ran (the script's own restore did the work) | `$$` or a script file; test the fallback |
| Several guessed clock times | confusing log entries | always `date`, log epoch |
| Another session's VM work during the overnight run | small heat and I/O confound | coordinate; log other activity |
| ryuji at -80 idled at SIO1 77-78C in a warm room | the first load step tripped guard v1 to Performance | profile across offsets before choosing a quiet offset |
| shelf-decay logged its start after reading every drive temperature (7-14 s) | event times lagged the fan change by that much | log the moment of the command (fixed) |
| The mic sat on the network shelf next to tinynas with its lid closed | the rack was a tenth of what it heard and every step looked half its size | measure about 1 m in front of the server rack, lid open (steps 2-2.5x larger, spread 0.05 dB) |
| 10-07: the mic logger stopped with `systemctl stop` | SIGTERM skipped its cleanup: the last clip stayed in /dev/shm, the mixer at the test gain | it handles SIGTERM now; check morgana's /dev/shm after a run |
| 10-07: a 24% fan cap on the quiet night | mementos's 12-core step never settled | map with fixed fans in the daytime; use caps only for quiet runs |

## 8. Plans for the repeat runs

### Shelf, with the AC working (about 5 h, can run overnight)
`testing/shelf-exp3.py` with PHASES edited to 60 min each: 20%, 15%, 20% (return), 25%, 20% (return), all with the
R720 floor at 10 (no mementos effect was found, and at 10 the script never edits fan-watchdog). Same abort limits.
It stops md1200-fan for the run; its ExecStopPost (`shelf-exp2-restore.sh`) starts it again. Expected at a 22C room:
15% about 47-48C hottest drive, 20% about 44.5C, 25% about 40C (10-06 rises over room: +25-26, +22.5, +17.5-18.7C).
Then confirm v3.1 settles around 14-16% on its own, and run a scrub to see its peak.

### mementos, with the AC working (about 1.5 h)
1. Fixed-fan map, `testing/mementos-fixedfan.py`. The 10-06 plan was full load at 50% and 40%, 18 workers at 30%,
   12 workers at 20%; add full load at 35%, 18 workers at 25% and 12 at 15% (edit PLAN) to find each load's floor.
2. `testing/mementos-steps.py v4val` under fan-watchdog v4.2: 12 and 18 workers, then a full load from idle and the
   unwind. Expect a few degrees cooler than 10-06 at every step and v4.2 settling a few % lower (10-06: 21%, 25-27%,
   32-35%).

### ryuji with the E5-2696 v4s (about 3 h)
The E5-2696 v4 is an OEM version of the E5-2699 v4: 22 cores each, 145 W in most listings (some say 150 W; Intel
publishes no spec page for it). Full load will put about 55 W more per socket through the CPUs and their VRs than
the E5-2650 v3s did (88-91 W measured).
1. Check the swap: `lscpu` shows 2 sockets x 22 cores; all 128 GB present (`free -g`); the BMC lists both CPU
   temperatures (`sudo ipmitool sdr type Temperature`). Read the BMC's CPU thresholds
   (`sudo ipmitool sensor | grep -i cpu`) and the package power limits
   (`cat /sys/class/powercap/intel-rapl:*/constraint_0_power_limit_uw`), read-only.
2. Idle baseline at -80 for 60 min with the guard running.
3. `tools/ryuji-profile.py e5-2696v4 full` with `lab-inlet-guard.sh` publishing the room: every offset, loudest first
   (0, -8, -16, -24, -80) x idle 10 min / 4 workers 6 min / full 6 min, then -80 idle; about 2 h plus room waits.
   It counts physical cores itself, so full load becomes 44 workers. Its stops (load off at CPU 82C or VR 95C, Full
   Speed at CPU 86C) stay: if a quiet offset cannot hold full load under 82C, that is the result.
4. `testing/analyze_ryuji_profile.py` for the per-phase table, and
   `tools/ryuji_profile_table.py room.csv ryuji-profile-e5-2696v4.csv` for the CPU rise per package watt. Compare
   with the e5-2650v3 CSVs.
5. Predictions to check: the 10-06 CPU rise was 0.38C per package watt with the CPU fans near 6,000 rpm (0.46 at
   4,900 rpm), so about 77-79C at full load in a 22C room (82-84C at 27C) with loud CPU fans; light loads will draw
   more package power than before.
6. The guard goes to -16 when a CPU reads 78C or more twice in a row (60 s apart), and from -16 to Performance if it
   still does, then holds Performance for 30 min after the load ends. With the new CPUs a full load will likely do
   exactly that. Decide between accepting it (Rohit: noise at full load is fine) and raising CPU_UP; keep CPU_UP well
   under the BMC's own CPU thresholds, and rerun the guard's harness (`ryuji-fan-guard/tests`) with the new numbers
   before deploying.

### Noise, with a microphone (morgana)
The mic is the internal mic of morgana (formerly arsene; the Latitude 5420 at 10.0.0.7) on its Realtek codec (ALSA
card 0, "Internal Mic"), which works with the stock driver. `testing/mic-level-log.py` (root) sets a fixed gain
(Capture 23 = 0 dB, Internal Mic Boost 0), records 10 s clips into RAM, keeps only the levels (dB(A), unweighted,
octave bands, steady tones), deletes each clip at once and restores the mixer on exit. Levels are dBFS for this mic
and gain: only differences mean anything.

Placement matters most. The same 17 min A/B test (`testing/README.md`) from two spots on 2026-10-06:

| Step, against the baselines on either side | On the network shelf above tinynas, lid closed | About 1 m in front of the server rack, lid open |
|---|---|---|
| Shelf 17 -> 30% | +1.6 dB(A) (+2.6 dB at 1-2 kHz) | +3.2 dB(A) (+3.8 dB) |
| Shelf 17 -> 22% | +0.5 to +1.3 dB(A) (room drift) | +0.7 dB(A) (+1.0 dB) |
| R720 10 -> 20% | +0.8 dB(A) | +1.4 dB(A) |
| R720 10 -> 30% | +1.6 dB(A) (+2.3 dB) | +3.7 dB(A) (+4.2 dB) |
| Spread within a steady state | 0.13-0.32 dB | 0.03-0.08 dB |

- In front of the rack the baselines before and after each step agree within 0.2 dB, so differences of a few tenths
  of a dB are measurable. The room sits about 22 dB above the mic's own floor.
- By fan laws the shelf at 17% is about a quarter of the A-weighted sound there (a tenth on the network shelf) and
  the R720 at 10% about 6% (2%); the rest is ryuji, sojiro and the room.
- The shelf fans show as a tone at about 5 x rpm / 60 Hz (295 Hz at 22%, 355 Hz at 30%), which picks the shelf out
  of a spectrum.
- After a reboot morgana's mixer came up with capture on at +12 dB; the logger sets its own gain on every run.

For the sweep:
1. Keep morgana about 1 m in front of the server rack, lid open with the screen facing the rack, on something soft
   at about the height of mementos and the shelf, on AC power. If it has moved, put it back and rerun the A/B test.
2. Use short A/B/A cycles (1-2.5 min per state) and judge by dB(A) and the 1-2 kHz bands. Note the AC's state.
3. Step one box at a time from its quiet state: shelf 15/20/25/30%; R720 10/20/30/40%; ryuji -80 / -16 /
   Performance; everything else held.
4. One short pass at the listening spot translates the ranking into what Rohit actually hears.

### tinynas, after the cage fan check (about 1 h per mode)
`testing/tinynas-cage-test.sh <mode>` as a transient unit with its fallback in a script file: `all` (BIOS 10 min,
pwm1+3+4 at full 20 min, BIOS 20 min), `each` (one header at a time) or `pwm2` (the CPU-fan header). A real cage fan
should move sda/sdc/sde by several degrees; on 10-06 pwm1/3/4 moved them 0.5C or less and the CPU-fan header at 2.5x
speed about 1C. If one does, a drive-temperature controller with a BIOS hand-back is next.

### Done on the night of 2026-10-07: quiet hot-room checks (room 26-28C, AC still faulty)
- fan-watchdog v4.2: 6 and 12 busy cores 18-24% (CPUs up to 78C); after load it steps back to exactly 10% in
  10.5-11 min (the change v4.2 made, now seen under load).
- md1200-fan v3.1 through a dataPool scrub: 18 -> 21%, one step per 10 min, hottest drive 50C (0 errors, 45:22).
- ryuji-fan-guard v2.1: -80 -> -16 -> -80 in 12.5 min after 2 min of 4-thread load (the heat soak took SIO1 to 79C).
- Noise at the mic spot: mementos 18-24% +0.5 to +1.8 dB(A); ryuji at -16 idle about +1.0; ryuji's CPU fans on 4
  threads at -80 +4.2 dB(A) with a ~700 Hz tone; a scrub inaudible. Include ryuji under light load in the sweep.

### Done 2026-10-07/08: the steady-room repeat (AC repaired, room 22-25C)
- Room: the AC was repaired the morning of 10-07; at 71F the rack inlet held 23-24C flat for 7 h (tinynas NVMe 30.9C,
  as on the healthy night of 10-03/04); at 70F it cycles normally (about 34 min on, 31 off, inlet 23-25C). The mic's
  63 Hz band rises 3-5 dB while the AC runs, which times its cycles (`testing/ac-cycles.py`).
- Shelf, overnight, 75-120 min per level (`testing/shelf-exp4.py`), hottest drive settled / mic: 10% 50.2C / -69.9
  dB(A), 12% 48.3 / -69.8, 15% 45.3-46.8 / -69.5, 20% 42.4 / -68.5, 25% 38.6 / -67.1 (room 23.5-24.5C). Fit
  (`testing/refit_shelf_model.py`): rise over the room 18.1C at 20%, rpm exponent 1.15, time constant 20 min at 20%
  (exponent 0.67), backplane 4C under the hottest drive. The 10-06 model, fitted in a cycling room, was about 4C too
  hot and twice too slow: map in a steady room, with phases of at least 75 min.
- md1200-fan v3.2 (50C target, paced urgent steps, fast easing) went live 10-08 06:59 after its harness and an 81-model
  sweep; 0 changes in its 45 min watch. Through a full scrub (0 errors, 47:16) it stepped 10 -> 18%, one step per 10
  min; the hottest drive reached 52C (a scrub adds about 5C there), the backplane 47C; about +0.8 dB(A) at the peak.
- mementos, fixed fans (`testing/mementos-fixedfan.py`, 22-23C room), peak CPU: all 48 threads 50/40/35% -> 73/74/77C;
  18 threads 30/25/20% -> 69/75/80C; 12 threads 20/15% -> 77/79C; 6 threads 15/12/10% -> 78/77/84C (a few busy
  cores make one socket hot). fan-watchdog v4.2 (`mementos-steps.py v42val`): idle 10%, 6/12/18 threads 17/19/25%,
  all 48 threads 32% at 80C (peak 38%), back to 10% in 20 min. v4.2 stays: 3% less fan would put 12-18 threads
  near 79C.
- Noise sweep at idle, empty house (`testing/noise-sweep.py`, A/B/A): shelf vs 15%: 10% -0.5, 20% +0.7, 25% +2.1,
  30% +3.7, 40% +8.1 dB(A); R720 vs 10%: 15% +0.8, 20% +1.6, 25% +3.0, 30% +4.3, 35% +6.4, 40% +12.0, 45% +9.7, 50%
  +13.5. Something in the rack or the room rings near 700 Hz: the R720's blade-pass tone (5 x rpm / 60) is 690-700 Hz
  at 40%, and the 1% sweep (`testing/r720-notch-sweep.py`) puts the band at 38-40% (40% +11.6, 41% +9.8). ryuji's CPU
  fans ring it too, at about 3,600 rpm (4 threads at -80) and about 2,600 rpm (the minutes after a load).
- ryuji (`testing/ryuji-floor.py`, plan `day`): 4 threads at -80/-100/-127/-80 -> CPU fans 3,600/3,400/2,950/3,900 rpm,
  CPUs up to 62/66/70/67C, no fan under 1,000 rpm, no BMC event; against the -80 brackets -100 was about 0.3 dB(A)
  quieter and -127 no quieter, though both remove the ~700 Hz tone. Full load (20 cores) +3.7 (-127) / +4.2 (-80) dB.
  Idle at -16 +0.7, at 0 +1.2 dB. Guard in control (`guardval`): it stayed at -80 through 4 threads and full load
  (CPUs up to 71C, SIO1 up to 77C); the BMC's own curve carries full load.
- ryuji, alternating (`ab`: -80 / -100 / -80 / -100 under 4 threads, each followed by 4 min idle at the same offset):
  -100 came out 0.8 dB(A) quieter at 4 threads counting one -80 run whose 1 kHz band jumped 4.7 dB, 0.4 dB louder
  without it; idle after the load was within 0.3 dB; the ~700 Hz tone was 2-3 dB weaker at -100 but present at both
  (fans >= 1,000 rpm, CPUs <= 65C, no BMC events). Not reliably 0.5 dB(A) quieter, so the guard's quiet level stays
  at -80 (v2.2). ryuji's light-load whine needs quieter CPU fans or coolers, not a lower offset.
- Lessons: a cycling room ruins equilibrium fits; noise is not monotonic in fan speed (check the tones against the
  700 Hz resonance); a test that stops a controller must run under a unit name the alert rules know, or under a
  silence that is expired only after its alerts resolve; and a session can be suspended for hours (23:48-06:39 on
  10-07/08), so long sequences run as chained units with time gates and a load-off timer (testing/README.md).

## 9. Checklists

**Before:** room flat for 2-3 h (ac-verify); loggers writing; stop rules in the scripts; fallbacks tested; idle
baseline running; `date` checked; SES device checked; nothing else heavy scheduled on the boxes.

**During:** one change at a time; note every action with a timestamp; check that the stop rules fire as expected;
watch the room.

**After:** all test units stopped and production controllers back (`systemctl is-active`, md5 of the installed
files against the repo); idle baseline; data copied off the hosts; results and changes written down; new controller
versions committed.
