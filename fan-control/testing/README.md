# Test tools (2026-10-05 to 10-16)

The scripts used to measure the rack and validate the fan controllers, kept as they ran so the tests can be
repeated. How they fit together, and what to change for the repeat runs, is in `../METHODOLOGY.md`.

## Hardware these tools were written for

The scripts assume this lab's machines by name, device path and sensor name. The three controlled boxes
(mementos, the MD1200 shelf, ryuji) are described part by part in `../README.md` ("Hardware"); the rest of the
setup the tests use:

| Host | Hardware | Role in the tests |
|---|---|---|
| mementos | Dell PowerEdge R720xd, iDRAC7 2.65, 2x Xeon E5-2697 v2, 256 GB DDR3, 24x ST1200MM0007 + 2x HUSMM SSD, H710P and H810 in IT mode, FTDI FT232R serial to the MD1200 | load and fan tests; owns the MD1200 serial console and SES device; its iDRAC inlet sensor is the room reference |
| MD1200 shelf | Dell PowerVault MD1200, 2 EMMs fw 1.06, 12x 8 TB Seagate SAS (ST8000NM0075 / ST8000NM0185) | shelf fan experiments (driven from mementos) |
| ryuji | Gigabyte MD70-HB0, Avocent MergePoint BMC 8.44, 2x Xeon E5-2696 v4 (since 2026-10-12; E5-2650 v3 before), 128 GB DDR4, one FSP800-20ERM supply | BMC fan offset profile and guard tests |
| sojiro | Gigabyte MB10-series board, Xeon D-1521, 32 GB, Avocent BMC | room proxy; since 2026-10-15 its BMC fan offset sits at -80 (`sojiro-floor.py` step test; set by hand with `../ryuji-fan-guard/gbt-fan-offset.py`, the BMC keeps it; the BMC is on DHCP: `sudo sojiro-bmc-ip` gives its address), no fan controller |
| tinynas | ASUS PRIME B650M-A AX II, Ryzen 5 9600X, 64 GB DDR5, 8x HGST HUS724040AL 4 TB, 2x Crucial P3 Plus 1 TB NVMe; Nuvoton NCT6799 super I/O (`nct6775` driver) | drive-cage fan test; NVMe and SYSTIN as room proxies |
| makoto | ASRock Rack board, Xeon D-1622, 32 GB | runs the makoto-side tools, the room logger and the PDU poller |
| morgana (formerly arsene) | Dell Latitude 5420 (i5-1135G7), Realtek codec, internal mic | noise measurements (`mic-level-log.py`) |
| Rack PDU | CyberPower PDU20SW8FNET (20 A, 8 switched outlets, fw 0.95) | rack current by SNMP v1 GET; bank load only, in 0.1 A. Never SET, never the web UI: both can switch the rack's power |

All hosts run Ubuntu 24.04.5 LTS. On other hardware, expect to change the device paths, sensor names, drive
model strings, IPMI commands and every limit before a script is safe to run; the safety rules in
`../METHODOLOGY.md` section 6 still apply.

## Conventions

- Scripts that touch hardware run as root on the box they test: copy them to `/var/tmp` and start them as transient
  systemd units with their restore script as `ExecStopPost`, so production control comes back however they end:

  ```sh
  sudo systemd-run --unit=mementos-steps -p ExecStopPost=/var/tmp/mementos-steps-restore.sh \
      python3 /var/tmp/mementos-steps.py v4val
  ```

  Never write a fallback inline with `${...}` in a unit command line (systemd expands it itself); use a script file.
- Output goes to `/var/tmp/<name>.csv` (or `.jsonl`) on the host. Copy it off before a reboot.
- The makoto-side tools reach the other boxes by ssh alias (`mementos`, `ryuji`, `sojiro`, `tinynas`, with
  passwordless `sudo ipmitool`) and keep their data in `$DATA` (default `~/fan-control-data`): `room.csv` from
  `../tools/lab-inlet-guard.sh`, `pdu.csv` from the PDU poller (not in the repo), `ac-watch.csv`.
- Hardware paths are this lab's: shelf console `/dev/ttyUSB0` (cable on the TOP EMM), shelf SES `/dev/sg39`,
  ryuji's BMC at 10.0.0.118 with its password in `/root/.bmc-pass` (0600).
- Plans are lists at the top of each script (`PLANS`, `PLAN`, `PHASES`); edit them for a new run.

## Start the loggers

From a clone of the repo on makoto (in `fan-control/`), with `DATA` set to this run's data folder. labmon needs
root (ipmitool, smartctl, RAPL) and appends to `/var/tmp/labmon.jsonl`; lab-inlet-guard runs as you because it uses
your ssh keys. If a unit name is still taken by an old failed run, `systemctl reset-failed <unit>` first.

```sh
export DATA=~/lab-thermal-$(date +%F)/data; mkdir -p "$DATA"
for h in mementos ryuji sojiro tinynas; do
  scp testing/labmon.py $h:/var/tmp/ && ssh $h 'sudo systemd-run --unit=labmon python3 /var/tmp/labmon.py --hours 72'
done
sudo install -m 755 testing/labmon.py /var/tmp/ && sudo systemd-run --unit=labmon python3 /var/tmp/labmon.py --hours 72
scp testing/dimm-log.sh mementos:/var/tmp/ && ssh mementos 'sudo systemd-run --unit=dimm-log bash /var/tmp/dimm-log.sh'
sudo systemd-run --uid=$USER --unit=lab-inlet-guard -p Restart=on-failure --setenv=DATA=$DATA \
    --setenv=LIMIT=27 --setenv=HARD=29 $PWD/tools/lab-inlet-guard.sh
```

Check: `systemctl is-active labmon` and `tail -1 /var/tmp/labmon.jsonl` on each host, `tail -2 $DATA/room.csv`.
The PDU poller (not in the repo) writes `pdu.csv`; `ac-verify.py` and `baseline_compare.py` expect it in `$DATA`.

## Logging

| Script | Runs on | What it does |
|---|---|---|
| `labmon.py` | every host | JSON line every 30 s: IPMI temps, fans and DCMI watts, hwmon, RAPL W per socket, CPU busy %, disk MB, SMART temps every 5 min (`--hours`, default 18). Optional stepped load with `--plan` and `--limit` |
| `dimm-log.sh` | mementos | DIMM temps from the Xeon E5 v2 memory controllers (DIMMTEMPSTAT via `setpci`, read-only), every minute |
| `hdd-temp-log.sh` | any | each rotating drive's temperature every 60 s (`smartctl -n standby`, never wakes a drive) |
| `scrub-log.sh` | mementos | during a dataPool scrub: progress, md1200-fan state, fan-watchdog state, every shelf drive |
| `ac-watch.sh` | makoto | every 5 min (timer): mementos inlet, tinynas NVMe, ryuji SIO1; flags when the AC looks back |
| `lab-watch.py <data dir> <stop "YYYY-MM-DD HH:MM">` | makoto (unit `lab-watch`) | the 2026-10-10/11 monitoring run's watcher, read-only: every minute one row of `watch.csv` from Prometheus and Alertmanager (room proxies, every box's temps and fans, controller levels, rack current, CPU busy, pool read and write rates) and lines in `watch-events.log`: INFO for controller level changes and pool activity, WARN (edge-triggered) for limits, hosts down and firing alerts. The queries, limits and noise windows are at the top |

## Room and baselines

| Script | Runs on | What it does |
|---|---|---|
| `ac-verify.py [HH:MM] [bucket min]` | makoto | is the room really cooling? 10 min means of independent room proxies on four machines plus the rack current |
| `baseline_compare.py HH:MM-HH:MM ...` | makoto | idle baseline per host for time windows: labmon means, room, PDU amps |
| `ac-check-prom.py "YYYY-MM-DD HH:MM" [end\|now]` | any host that reaches Prometheus | is the room flat? 10 min means of the room proxies (mementos inlet, tinynas NVMe and SYSTIN, sojiro and makoto board temps) and the rack current, and each proxy's worst 1 h spread |
| `ac-cycles.py "YYYY-MM-DD HH:MM" [end\|now]` | same | the same proxies at 1 min steps: means and swings per period, and the turning points of the smoothed NVMe and inlet, which time the AC's on/off cycles |
| `prom-pdu-csv.py "YYYY-MM-DD HH:MM" out.csv` | same | the rack PDU current from Prometheus as the CSV `baseline_compare.py` and `window_compare.py` read |
| `prom-range-csv.py "YYYY-MM-DD HH:MM" "YYYY-MM-DD HH:MM"\|now <step s> <out.csv>` | same | `lab-watch.py`'s columns from Prometheus over any window (it reads `lab-watch.py`'s query table), for history before a watch started or to re-sample one |
| `day-summary.py <csv> ["YYYY-MM-DD HH:MM" [end]]` | anywhere | a `watch.csv` (or `prom-range-csv.py` output) summed up: p1 / p50 / p99 / max per column, minutes at each fan level, hourly medians, the busiest disk periods |
| `lab-status.py [minutes] [data dir]` | makoto | a check-in: min / median / max of the key `watch.csv` columns over the last N minutes (default 60) and the events logged in that time |

## MD1200 shelf

| Script | Runs on | What it does |
|---|---|---|
| `shelf-exp3.py` | mementos | overnight experiment: fixed shelf % per phase (re-sent every 2 s), optional R720 floor and CPU load per phase, abort limits; restore `shelf-exp2-restore.sh` |
| `shelf-decay.py <pct> <min> <label>` | mementos | does one `_shutup` hold without re-sending? Watches SES rpm and re-sends at once on a takeover |
| `emm-query.py <hold %> <out>` | mementos | read-only EMM diagnostics (`_who`, `_ver`, PSU and fan status) while holding the shelf at a fixed % |
| `analyze_exp2.py`, `analyze_exp3_lagged.py` | anywhere | per-phase settled values, exponential fits, rise over a lagged room reference |
| `shelf-exp4.py` | mementos | the steady-room overnight map (2026-10-07/08): fixed shelf % per phase (`PHASES`), no R720 changes and no ipmitool; checks `_who` once and exits unless the cabled EMM is primary and active; writes `/run/md1200-fan.state` every minute so the monitoring and md1200-fan's resume keep working; restore `shelf-exp4-restore.sh`. Ran as 15 and 20%, then (same code, new `PHASES`) 12, 10, 25 and 15% |
| `analyze_exp4.py <csv> [...]`, `refit_shelf_model.py <csv> [...]` | anywhere | per-phase settled values and fits; the fit of the hottest drive's rise over the room and its time constant against rpm (R20, EXPO, TAU, TEXP) that `../md1200-fan/tests/test_md1200_scenarios.py` uses |
| `exp4_spans.py <csv>` | anywhere | the phases of a `shelf-exp4.py` run as `--span` arguments for `analyze_mic_phases.py` |

## mementos (R720xd)

| Script | Runs on | What it does |
|---|---|---|
| `mementos-steps.py <plan>` | mementos | load steps under the production fan-watchdog (plans `v42val`, `v4val`, `v41val`, `steps2`, `caps`; `caps` is history: Rohit wants no power caps, and the others write only the stock RAPL limits), room-gated, with CPU/DIMM/exhaust stops; restore `mementos-steps-restore.sh` (kills load, stock RAPL limits) |
| `mementos-fixedfan.py` | mementos | fixed fan % x fixed load map (2026-10-08 plan: all 48, 18, 12 and 6 workers, each at falling fan levels); stops fan-watchdog while it runs; room-gated (26C to start load, off above 27C); restore `mementos-fixedfan-restore.sh` |
| `mementos-fixedfan-night.py` | mementos | the light half of that map for a night slot: 6 and 12 workers at fixed 10-20%; a CPU at 85C stops the load and only 88C raises the fans, to 24% (the day script goes to 60%) |
| `analyze_mementos_steps.py`, `analyze_fixedfan.py` | anywhere | per-step settled values, peaks, slopes |

## ryuji and tinynas

| Script | Runs on | What it does |
|---|---|---|
| `analyze_ryuji_profile.py <profile.csv> <room.csv> [hdd.csv]` | anywhere | per-phase settled values of a `../tools/ryuji-profile.py` run, joined with the room |
| `phase-mic.py <run.csv> <mic.csv> [last min] [clean dBFS]` | anywhere | per phase of a `ryuji-floor.py` run, over its last minutes: sensor medians, dB(A) (all clips and clips without household sounds in the 4 kHz octave), the strongest 400-1000 Hz tone and the share of clips with a tone in the 680-830 Hz ringing band |
| `psu-tone.py <mic.csv> <HH:MM>-<HH:MM>[@date] [min per row]` | anywhere | ryuji's power-supply fan tone minute by minute: strongest 400-1000 Hz tone outside the room's fixed ~791 Hz tone, with dB(A) and the 500 Hz / 1 kHz octaves |
| `phase-table.py <run.csv> [--turbo turbostat.tsv] [--mic mic.csv ...] [--last MIN] [--md]` | anywhere | one row per phase of a `ryuji-floor.py` run over its last minutes: sensors, wall and package watts, busy MHz (turbostat), throttle events, dB(A), octave bands, the strongest 400-1000 Hz tone and its share in the 680-830 Hz band (2026-10-13) |
| `bench-7zip.sh` | ryuji | 7-Zip's built-in benchmark at 1, 44 and all threads with the guard in control (2026-10-13) |
| `ryuji-rpm-tone.py <profile.csv> <mic.csv> [skip s]` | anywhere | per phase of a `ryuji-floor.py` run: CPU-fan rpm against dB(A), octave bands and the strongest 600-760 Hz tone |
| `tone_timeline.py <profile.csv> <mic.csv> [lo hi]` | anywhere | minute by minute, the strongest tone between lo and hi Hz (default 400-1000) next to DCMI watts and fan speeds; a tone that follows temperature rather than load points to a fan like ryuji's PSU fan |
| `ryuji-floor.py <label> <plan>` | ryuji | BMC offsets below -80 (down to -127) at idle, 4 threads and full load (plans `floor`, `night`, `day`, `guardval`, `ab`, `follow`, `psu`: 30 min holds at 4 threads, -80/-40/-40/-80, 2026-10-10; for the E5-2696 v4s 2026-10-12/13: `v4light`, `v4b`, `v4a2`, `v4c`, `v4idle`, `v24light`, `v4prof` (offsets 0/-16/-60/-80/Full x idle/22/44 workers), `v4heavy` (33 workers), `v4half` (22 workers, 20 min holds), `v24val`/`v25val` (the guard in control: full load, half load, a job that grows, bursts), `v4bench`; `LOAD_UNTIL` (epoch) stops new load steps after a time, 15 s samples under load, kernel thermal-throttle counters in the CSV, load off at CPU 82C and abort at 84C for these CPUs); every fan must stay at 1,000 rpm or more, checked every 5 s for 60 s after each change (a lower reading puts -80 back and skips that offset and lower); BMC event log counted before and after; restore `../tools/ryuji-profile-restore.sh` |
| `tinynas-cage-test.sh <all\|each\|pwm2>` | tinynas | does any motherboard fan header cool the drive cage? A/B/A against BIOS control; more airflow only; needs `modprobe nct6775` |

## Noise (microphone)

| Script | Runs on | What it does |
|---|---|---|
| `mic-level-log.py <minutes> <csv> [clip s]` | morgana, formerly arsene (root) | sound levels from the internal mic every 10 s at a fixed gain: dB(A), unweighted, octave bands, steady tones. Keeps only the levels and deletes each clip at once; needs alsa-utils and python3-numpy (installed 10-06). Since 10-07 a `systemctl stop` (SIGTERM) also runs its cleanup; before that the last clip stayed in /dev/shm and the mixer at the test gain |
| `mic-compare.py <mic.csv> <label>=<HH:MM>-<HH:MM>[@YYYY-MM-DD] ...` | anywhere | compares `mic-level-log.py` windows: dB(A), unweighted and octave bands, each window split by the AC's state (read from the 63 Hz octave, which the AC's hum lifts 3-5 dB), and how often each tone shows up, so a source that stops (a fan) shows as a tone that disappears |
| `mic-r720.sh` | mementos (root) | R720 fans at fixed steps at idle (10, 20, 10, 30, 10%), then fan-watchdog takes them back; restore `mic-r720-restore.sh` |
| `analyze_mic_test.py <levels.csv> <shelf-decay logs> <mic-r720.log>` | anywhere | splits the levels into states from the event logs, drops settling time and stray sounds, compares each step with the baselines on either side (dB(A) and the 1-2 kHz bands) |

The A/B test from 10-06 (17 min; the shelf holds use `shelf-decay.py`; copy the scripts to `/var/tmp` first). Place
morgana about 1 m in front of the server rack, lid open (METHODOLOGY section 8, "Noise"):

```sh
ssh morgana 'sudo systemd-run --collect --unit=mic-level python3 /var/tmp/mic-level-log.py 17 /var/tmp/mic-levels.csv'
ssh mementos 'sudo systemd-run --collect --on-active=70 --unit=mic-shelf30 -p "ExecStopPost=/bin/systemctl start md1200-fan" python3 /var/tmp/shelf-decay.py 30 2.5 mic30 3'
ssh mementos 'sudo systemd-run --collect --on-active=330 --unit=mic-shelf22 -p "ExecStopPost=/bin/systemctl start md1200-fan" python3 /var/tmp/shelf-decay.py 22 2.5 mic22 3'
ssh mementos 'sudo systemd-run --collect --on-active=590 --unit=mic-r720 -p ExecStopPost=/var/tmp/mic-r720-restore.sh /bin/sh /var/tmp/mic-r720.sh'
```

### Noise sweeps (2026-10-08)

| Script | Runs on | What it does |
|---|---|---|
| `noise-sweep.py` | mementos (root) | A/B/A at idle, one box at a time: the shelf at 10-40% against 15% (only the primary EMM, never under 10%), then the R720 at 15-50% against 10%; md1200-fan and fan-watchdog start again whatever happens (restore `noise-sweep-restore.sh`). Run it as unit `mic-shelf-sweep` so the alert rules stay quiet |
| `r720-notch-sweep.py` | mementos (root) | the R720 only, 36-44% in 1% steps against 10%, 90 s each, to find the edges of the rack's ~700 Hz resonance (2026-10-08: 38-40%, +11.6 dB(A) at 40% against +9.8 at 41%); restore `r720-notch-restore.sh`; unit `mic-r720-notch` |

Analyze either with `analyze_mic_phases.py <mic.csv> <sweep.csv> --skip 30`. The loudest tone of the R720 is its
fans' blade-pass frequency (5 x rpm / 60): read the `tones` column of the mic log next to the levels.

## Quiet runs (night, visitors)

Added 2026-10-07, when Rohit asked for testing while he slept with nothing loud. Each test stops itself below a fan
level, and a mic guard stops any test that makes the rack louder (limits in `../METHODOLOGY.md` section 6).

| Script | Runs on | What it does |
|---|---|---|
| `noise-guard.sh` | makoto | every 20 s reads the newest level from morgana's mic log (`MIC`) and stops `mementos-quiet`, `scrub-quiet` and `ryuji-quiet` once dB(A) is more than `RISE` above `REF` for `HOLD` readings. 10-07: REF -68.30 (the quiet baseline's median), RISE 3.0, HOLD 3 |
| `mementos-quiet.py` | mementos | `mementos-steps.py` with plan `quiet` (6 and 12 workers, 12 from idle, the unwinds) and a fan stop, `STOP['pct']` (24%); restore `mementos-quiet-restore.sh` |
| `ryuji-quiet.py` | ryuji | `../tools/ryuji-profile.py` with plan `quiet` (the guard stays in control: idle, 4 threads, unwind) and tighter stops (CPU 72, SIO1 80, VR 88, DIMM 72C, or the guard above -16); restore `ryuji-quiet-restore.sh` |
| `scrub-quiet.sh` | mementos | a dataPool scrub that cancels itself at shelf 25% or drive 51, backplane 47, SIM 60, expander 89C; `scrub-quiet-stop.sh` (ExecStopPost) cancels a scrub still running |
| `md1200-fan-quiet` | mementos | a temporary quiet mode of `md1200-fan` v3.1 for a visit: starts at 10% and lets the hottest drive reach 50.5C (v3.1: 48.5C) before stepping up; urgent ramps and floors unchanged. In a 26-28C room 10% lasts about 30-60 min before the drives need more |
| `window_compare.py "YYYY-MM-DD HH:MM-HH:MM" ...` | makoto | labmon means per host for dated windows, so one run's baselines compare with another's (`OLD`, `DATA`) |
| `analyze_mic_phases.py <mic.csv> [test.csv]` | anywhere | sound level per test phase against a reference window (default: the 30 min before the first phase) |

The CSV and log names inside the quiet scripts carry the run date (`-1007`); change them for a new run.

```sh
# A quiet night: the mic first, a 60 min quiet baseline, then the guard, then one test at a time.
ssh morgana 'sudo systemd-run --collect --unit=mic-level python3 /var/tmp/mic-level-log.py 450 /var/tmp/mic-levels.csv'
sudo systemd-run --uid=$USER --unit=noise-guard --setenv=HOME=$HOME --setenv=DATA=$DATA \
    --setenv=MIC=/var/tmp/mic-levels.csv --setenv=REF=-68.30 --setenv=RISE=3.0 $PWD/testing/noise-guard.sh
ssh mementos 'sudo systemd-run --unit=mementos-quiet -p ExecStopPost=/var/tmp/mementos-quiet-restore.sh python3 /var/tmp/mementos-quiet.py quiet'
# The shelf's quiet mode for a visit (here 10 h), handing back to md1200-fan at the end:
ssh mementos 'sudo systemctl stop md1200-fan && sudo systemd-run --unit=md1200-fan-quiet -p RuntimeMaxSec=36000 -p "ExecStopPost=/bin/systemctl start md1200-fan" python3 /var/tmp/md1200-fan-quiet'
```

## A day of tests without the session (2026-10-08)

The session that ran these tests was suspended for 7 hours one night, so the day's steps ran on their own:

- Each step is a systemd unit whose `ExecStopPost` hands the fans back to the production controller.
- A chain unit starts the next step only after the previous one has stopped (an unreachable host counts as busy) and
  not after a set time.
- `lab-loadoff-mementos.sh` and `lab-loadoff-ryuji.sh`, armed with `systemd-run --on-calendar=...` (ryuji's clock is
  UTC), stop every test unit, kill stress-ng, pause a scrub and start the controllers at the hard end of the window.
- `silence.py create|list|expire` manages Alertmanager silences. Since `lab-thermal.yml` v3, test units named like
  these tools need none; expire a silence only after its alerts have resolved.
- `dryrun/` runs `noise-sweep.py`, `r720-notch-sweep.py`, `mementos-fixedfan-night.py` and `ryuji-floor.py` on fake
  clocks with fake hardware: `python3 -I dryrun/dryrun_noise_sweep.py noise-sweep.py`,
  `PLAN=ab python3 -I dryrun/dryrun_ryuji_floor.py ryuji-floor.py '{"-80": 1000, "-100": 900}'`.

## The final rack run (2026-10-13/16)

72 hours with the rack in its final form (ryuji racked), every step a persistent systemd unit on the hosts, chained
across hosts, with backstops. Plans, schedule and results: `../METHODOLOGY.md` ("Done 2026-10-13/16") and
`../README.md` ("Results, 2026-10-13/16").

| Script | Runs on | What it does |
|---|---|---|
| `fin-gate.py <not-after epoch> ['<instance>:<unit regex>' ...]` | every host (ExecStartPre) | waits until none of the named services is active anywhere (Prometheus `node_systemd_unit_state`, services only: a one-shot timer stays "active" after it fires), refuses after the not-after time; an unreachable Prometheus counts as busy. Units need `TimeoutStartSec=infinity` |
| `make-units.py` | makoto | writes the run's schedule as units and timers per host into the run directory (one service + timer per block: the gate, `ExecStopPost`, `RuntimeMaxSec`, `LOAD_UNTIL`) |
| `ryuji-floor.py <label> <plan>` | ryuji | as before, plus the final run's plans: `fin_light` (2 / 4 / 11 workers at -80 / -60 / -40), `fin_psu2`, `fin_drive` (a disk soak at offsets 0 / -8 / -16), `fin_idleoff`, `fin_heavy` (22 / 33 / 44 workers at -80 / -127 / -80), `fin_comb`, `fin_val`, `fin_burst`, `fin_soak` |
| `mementos-steps.py <plan> <label>` | mementos | reworked: no IPMI reads at all while fan-watchdog runs (a second in-band reader can fail one of its reads and send the R720 to iDRAC auto): fan-watchdog's state file, coretemp, RAPL and the kernel throttle counters instead; no RAPL writes; `LOAD_UNTIL`; stops at CPU 89, DIMM 75, exhaust 60, HDD 50, SSD 60C, iDRAC auto or a stale state. Plans `fin_steps`, `fin_mixed`, `fin_burstm`, `fin_high`, `fin_comb`, `fin_val`, `fin_burst`, `fin_soak`; restore `mementos-steps-restore-fin.sh` |
| `disk-soak.py <label> <pool> <phases> [limit C]` (phases like `rand:60`) | mementos, ryuji | read-only fio load on one pool's disks (sequential or random), every disk's temperature each minute, stops at the limit. `--readonly` goes on the command line: fio rejects `readonly` in a job file and drops the job |
| `pdu-cut.sh` | mementos, ryuji | during a combined test, every 15 s reads the rack PDU's current from Prometheus (futaba polls the PDU by SNMP GET) and kills this host's test load at `LIMIT` deciamps on two fresh samples, or when no fresh sample comes for two checks |
| `lab-loadoff-mementos.sh`, `lab-loadoff-ryuji.sh` | each host (timers) | the final run's backstops: stop every test unit (incl. `pdu-cut*`), kill stress-ng and fio, start the controllers |
| `alarm.sh` | makoto (a loop every 2 min) | one pass over the run's danger signs: failed or stuck units, abort/stop notes in the run CSVs, iDRAC auto while fan-watchdog runs, the shelf EMM not primary, 2+ shelf takeovers between passes, a controller down with no test holding its fans, ryuji at Full Speed or long at Performance with cool drives, sojiro's BMC sensors (from Prometheus, once its offset is set) |
| `phase-table.py`, `mementos-phase-table.py`, `sojiro-phase-table.py` | anywhere | one row per phase of a `ryuji-floor.py` / `mementos-steps.py` / `sojiro-floor.py` run: settled sensor medians, peaks, throttle events, dB(A), octave bands and the strongest tone |
| `sweep-aba.py <mic.csv> <sweep.csv>` | anywhere | each step of a `noise-sweep.py` / `r720-notch-sweep.py` run against the mean of the reference holds before and after it |
| `mic-window.py <mic.csv> <date> <label>=<HH:MM:SS>-<HH:MM:SS> ...`, `prom-stats.py "<start>" "<end>" [label=promql ...]` | anywhere | mic medians per window; min / p50 / max of Prometheus series over a window |
| `sojiro-floor.py <label> [plan]` | sojiro | idle step test of sojiro's BMC fan offset (0 to -127, 6 min each; `proof`: -100 only, night-safe), back to production (-80) at SYS_FAN1 < 600 rpm, CPU0_FAN < 1,000 rpm, CPU 85C or MB_TEMP1 75C; the BMC's address from `sojiro-bmc-ip` at each start, no BMC call without a checked one; restore `sojiro-floor-restore.sh` (-80, read back), gate `sojiro-gate.sh` (uptime after a reboot, not-after) |
| `mic-r720-listen.sh` | mementos | the blind listening test: R720 fans at fixed levels in 90 s slots on a fixed timetable while Rohit listens from the couch and the kitchen (key kept out of sight); `listen-table.py <mic.csv> --start HH:MM:SS` joins the slots with the mic |
| `mementos-thermal-model.py <run.csv> ...`, `fw-sim.py` | anywhere | a two-node model of mementos's hotter CPU fitted to `mementos-steps.py` runs (rmse 1.1C) and fan-watchdog's loop simulated on it, to compare down-step rules (2026-10-15: a faster unwind would cut burst noise, but mementos's real load never leaves 10%) |
| `ryuji-maxbench.sh <label> [dry]` | ryuji | what the E5-2696 v4s can do: 7-Zip at 1-88 threads, 15 min sustained under the guard, 8 min at Full Speed fans, stress-ng stream and sysbench memory, openssl, sysbench cpu, with sensors and turbostat; restore `ryuji-maxbench-restore.sh` |

## Deploying a controller

`deploy-examples/` has the deploy-and-watch scripts used on 10-06 (md1200-fan v3.1, fan-watchdog v4.2,
ryuji-fan-guard v2.1) and 10-07/08 (ryuji-fan-guard v2.2, 20 min; md1200-fan v3.2, 45 min). Each backs up the running version, installs the new one, watches it at idle for 10-45 min
and rolls back by itself on a crash loop, repeated errors, flapping, shelf takeovers or a switch to iDRAC auto.
Copy one and change the file names and checks for the next version.
