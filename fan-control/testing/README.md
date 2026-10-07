# Test tools (2026-10-05/06)

The scripts used to measure the rack and validate the fan controllers, kept as they ran so the tests can be
repeated. How they fit together, and what to change for the repeat runs, is in `../METHODOLOGY.md`.

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

## Room and baselines

| Script | Runs on | What it does |
|---|---|---|
| `ac-verify.py [HH:MM] [bucket min]` | makoto | is the room really cooling? 10 min means of independent room proxies on four machines plus the rack current |
| `baseline_compare.py HH:MM-HH:MM ...` | makoto | idle baseline per host for time windows: labmon means, room, PDU amps |

## MD1200 shelf

| Script | Runs on | What it does |
|---|---|---|
| `shelf-exp3.py` | mementos | overnight experiment: fixed shelf % per phase (re-sent every 2 s), optional R720 floor and CPU load per phase, abort limits; restore `shelf-exp2-restore.sh` |
| `shelf-decay.py <pct> <min> <label>` | mementos | does one `_shutup` hold without re-sending? Watches SES rpm and re-sends at once on a takeover |
| `emm-query.py <hold %> <out>` | mementos | read-only EMM diagnostics (`_who`, `_ver`, PSU and fan status) while holding the shelf at a fixed % |
| `analyze_exp2.py`, `analyze_exp3_lagged.py` | anywhere | per-phase settled values, exponential fits, rise over a lagged room reference |

## mementos (R720xd)

| Script | Runs on | What it does |
|---|---|---|
| `mementos-steps.py <plan>` | mementos | load steps under the production fan-watchdog (plans `v4val`, `v41val`, `steps2`, `caps`), room-gated, with CPU/DIMM/exhaust stops; restore `mementos-steps-restore.sh` (kills load, stock RAPL limits) |
| `mementos-fixedfan.py` | mementos | fixed fan % x fixed load map; stops fan-watchdog while it runs; restore `mementos-fixedfan-restore.sh` |
| `analyze_mementos_steps.py`, `analyze_fixedfan.py` | anywhere | per-step settled values, peaks, slopes |

## ryuji and tinynas

| Script | Runs on | What it does |
|---|---|---|
| `analyze_ryuji_profile.py <profile.csv> <room.csv> [hdd.csv]` | anywhere | per-phase settled values of a `../tools/ryuji-profile.py` run, joined with the room |
| `tinynas-cage-test.sh <all\|each\|pwm2>` | tinynas | does any motherboard fan header cool the drive cage? A/B/A against BIOS control; more airflow only; needs `modprobe nct6775` |

## Deploying a controller

`deploy-examples/` has the three deploy-and-watch scripts used on 10-06 (md1200-fan v3.1, fan-watchdog v4.2,
ryuji-fan-guard v2.1). Each backs up the running version, installs the new one, watches it at idle for 10-45 min
and rolls back by itself on a crash loop, repeated errors, flapping, shelf takeovers or a switch to iDRAC auto.
Copy one and change the file names and checks for the next version.
