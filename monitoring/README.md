# Adding a host to the lab's monitoring

`deploy-monitoring` adds a Linux host to the lab's monitoring in one command. It replaces the old checklist: packages
and scripts on the host, then the Prometheus target, the Glance card and the Cockpit list on futaba.

```sh
monitoring/deploy-monitoring HOST             # a server: futaba's Prometheus scrapes it
monitoring/deploy-monitoring HOST --roaming   # a laptop, or anything that is often away, asleep or off
monitoring/deploy-monitoring HOST --dry-run   # show what would change on both sides, change nothing
```

Other options: `--ip ADDR` (a server's scrape address, default `HOST.home.arpa` as futaba resolves it),
`--icon NAME` (a [dashboard-icons](https://github.com/homarr-labs/dashboard-icons) name for the Glance card, picked
from the host's OS by default) and `--no-cockpit`.

Run it from a checkout of this repo on a machine that can SSH to the host and to futaba. In this lab that is makoto,
tinypc or akechi; the servers hold no SSH logins. It needs sudo on the host, either passwordless (`sudo-grant HOST`
here) or typed once on a terminal. Running it again changes only what is missing or different, so it is also the way
to bring an older host up to date.

## What it sets up

| | Server (default) | Roaming (`--roaming`) |
|---|---|---|
| node_exporter | port 9100 on all interfaces | localhost only |
| How metrics reach futaba | futaba's Prometheus scrapes the host's fixed address every 15 s | a Prometheus agent on the host scrapes it every 15 s and pushes to futaba (remote write), at home or over the VPN, keeping up to 24 h on disk while futaba is out of reach |
| drivecheck | `/etc/cron.d/drivecheck`, daily at 00:00 | systemd timer, daily, plus on resume or boot after a missed day |
| SMART self-tests | short on Saturday 22:00, long on the first Monday at 08:00 | none scheduled (see below) |
| thermal-log | yes | yes |
| Cockpit | bridge, system and storaged on the host, and an entry in futaba's Cockpit list | none: futaba's Cockpit reaches hosts over SSH at a fixed address |
| Prometheus target on futaba | the host's address in the `node` job | none |
| Glance on futaba | a host card (red "offline" when down) and a row in "Drives healthy by system" and "Hottest drive by system" | a host card that says "away, last seen 3h ago" in grey when no data arrives, and the same drive rows |

The pieces:

- `install-host` is the host half. It runs as root from a temporary copy on the host and installs the Ubuntu
  packages (prometheus-node-exporter, nvme-cli, smartmontools, and prometheus for roaming hosts), this repo's
  `scripts/drivecheck`, `scripts/drive-selftest` and `scripts/drivecheck.cron`, and `fan-control/monitoring/thermal-log`
  with its unit and logrotate file.
- `futaba-register` is the futaba half. It edits `prometheus.yml`, `glance.yml` and Cockpit's `51-lab.json` in place,
  keeping the inode that Docker's single-file bind mounts need, after a dated backup (`<file>.bak-YYYY-MM-DD-<host>`).
  A new card is copied from the last plain host card, so it matches the others. A Prometheus change is checked with
  promtool and reloaded, a Glance change is checked on the rendered page, and either is put back if the check fails.
- `roaming/` holds the agent's config template and drivecheck's service and timer.

Alert rules and Grafana dashboards need nothing per host: they select by job and host name.

## Why roaming hosts push

akechi, the laptop, is away, asleep or off much of the time, and that is normal. Scraping it would need an address,
and it has two that change: a DHCP lease at home and a VPN address that strongSwan hands out from its pool on each
connection (in October 2026 it alternated between the first two pool addresses on reconnects). So nothing scrapes it.
A Prometheus agent on the laptop scrapes its own node_exporter on localhost and pushes to futaba by name
(`futaba.home.arpa`, which resolves at home and over the VPN and nowhere else). It labels everything
`job="node", instance="<host>"`, so dashboards and alert rules treat it like any other host.

What "offline is normal" means in practice:

- **No alert while it is away.** TargetDown fires on `up == 0`, and an away host sends no samples at all, so its series
  simply stop. If node_exporter dies while the laptop is online, the agent pushes `up = 0` and TargetDown fires as it
  would for a server.
- **No stale-drive alert after a long sleep.** DriveCheckStale fires after 2 days without a drivecheck run. Cron skips
  runs the machine slept through, so roaming hosts use a timer that runs drivecheck on resume or boot instead.
- **No scheduled self-tests.** A laptop is often asleep or away at any fixed time, so the results would be patchy.
  Since drivecheck v2 an aborted test no longer raises an alarm, so a weekly timer that runs only on AC power could
  be added later. Run `sudo drive-selftest short` by hand on AC power if you want one.
- **Glance shows it calmly.** The card says "away" in grey with when it last reported, instead of a red "offline". The
  Fleet tile counts it only while it reports, and its drive rows disappear while it is away.
- **Gaps fill in.** If the laptop runs for a while without reaching futaba (no VPN), the agent keeps up to 24 h of
  samples and sends them when futaba is back, and futaba accepts samples up to a day old. A reboot before it
  reconnects loses that buffer: the agent only sends samples newer than its own start.
- **Battery.** Pushes retry at most once a minute while futaba is unreachable.

## futaba prerequisites for roaming hosts

Needed once:

1. Prometheus runs with `--web.enable-remote-write-receiver` in the compose file's `command:` list. Changing it
   recreates the container.
2. `prometheus.yml` lets late samples in:

   ```yaml
   storage:
     tsdb:
       out_of_order_time_window: 1d
   ```

The script checks both before it sets up a roaming host and says what is missing. The receiver accepts writes from
anything that can reach Prometheus's port, the same exposure as the rest of its unauthenticated API on the LAN.

## Drive checks (drivecheck)

`../scripts/drivecheck` (v2 since 2026-10-16: Python 3, standard library only) reads every drive once a day with
`smartctl -x --json=o -n standby`, one drive at a time with a 1 s pause, because fan controllers on some hosts read
the same drives. It prints a report that cron (or the roaming timer) appends to `/var/log/drive_logs/drive_check_DATE.log`
(tinynas: `/pool/drive_logs`) and writes `drivecheck.prom` for node_exporter's textfile collector.

- **What it reads.** SATA: attributes 5, 10, 183, 184, 187, 188 and 196-199, every normalized value against its
  threshold, the ATA error log, device statistics (SSD wear). SAS: grown defects, uncorrected, delayed-ECC and reread
  counters, the non-medium count, background-scan results and the drive's view of its PHY link. NVMe: the health log,
  including critical warning, unsafe shutdowns, minutes over the warning and critical temperature and thermal
  throttling. For every drive: its temperature against its own limit, the newest self-test and the newest long one.
- **State.** `/var/lib/drivecheck/state.json` keeps each drive's last counters by serial. A drive seen for the first
  time is a baseline, so a fresh install raises no "0 -> N" alerts (v1 did).
- **What it alerts on itself** (`drivecheck_alerts_total`, ALERT lines in the log, email when `DRIVECHECK_NO_MAIL` is
  not 1 and a mailer exists): failed SMART health; ATA 5, 10, 187, 196, 197, 198 or 199 rising; pending or offline
  uncorrectable sectors on a hard drive; SAS grown defects rising or uncorrected errors; an NVMe critical warning,
  rising media errors or spare under 70%; a self-test that failed; kernel I/O errors in the last 24 h. An interrupted
  or aborted self-test (a reboot or suspend) is not a failure. Everything else is a metric for the rules below.
- **Skipped.** Network LUNs (iSCSI, vendor LIO-ORG) and drives asleep in standby (`drivecheck_standby 1`, never woken).
- **Offline test.** `drivecheck --fixtures DIR --out OUTDIR [--host NAME]` reads saved `smartctl -x --json=o` files
  (`DIR/smart-*.json`) instead of the drives and writes only under `OUTDIR`.

Checked on 2026-10-16 against all 70 drives in the lab (smartmontools 7.4 on Ubuntu 24.04, 7.5 on Fedora 44 and
Kubuntu 26.04; Python 3.12 and 3.14):

| Interface | Drives (firmware) | Controller |
|---|---|---|
| SAS HDD | 24x Seagate ST1200MM0007 10K (IS06); 11x Seagate ST8000NM0075 (PS26) and 1x ST8000NM0185 (PT54) in a Dell PowerVault MD1200 | two LSI SAS2308 in IT mode (firmware 20.00.07.00, mpt2sas) |
| SAS SSD | 2x HGST HUSMM8080ASS20 800 GB (J4B6) | LSI SAS2308 |
| SATA HDD | 8x HGST HUS724040ALA640 (MFAOAA70); 6x Toshiba MG04ACA400N and 2x MG04ACA200N (FJ3A) | AMD 600-series and ASMedia ASM1061 AHCI; Toshibas also behind an onboard LSI SAS3008 (mpt3sas), read through SCSI-to-ATA translation |
| SATA SSD | Crucial MX500 1 TB (M3CR032, M3CR043); Kingston SUV400 120 GB, SKC600 256 GB, OM8P0S3256Q-A0 256 GB | Intel and Xeon D AHCI |
| NVMe | Crucial P310 500 GB, P3 Plus 1 TB, P1 1 TB; Samsung 970 EVO Plus 2 TB; WD PC SN530 256 GB, WD_BLACK SN850X 1 TB; SK hynix BC901 512 GB | PCIe 3.0 and 4.0 x4 |

Using it elsewhere: it needs smartmontools 7.0 or newer for JSON output. Pass smartctl only the device path (never
`smartctl --scan`'s `-d scsi`), or SATA drives behind a SAS HBA lose their ATA attributes. Some values exist only in
smartctl's text, which `--json=o` embeds and drivecheck parses: the SAS non-medium count, background-scan entries,
and on 7.4 the NVMe throttle counters and warning temperature. The five attributes v1 reported keep v1's fixed names
in the `name` label, so their series continue. Set `DRIVECHECK_PAUSE` (seconds between drives) to 0 where nothing
else polls the drives.

## Storage alert rules

`storage-rules.yml` holds 16 Prometheus alert rules for ZFS pools and drive health; `storage-rules.test.yml` holds
promtool unit tests for them. On futaba the rules live at `prometheus/rules/storage.yml` beside `alerts.yml`, and
Prometheus loads every `rules/*.yml`. The tests sit outside that directory (in `prometheus/tests/`), so Prometheus never
tries to load them as rules.

```sh
promtool check rules storage-rules.yml
promtool test rules storage-rules.test.yml
curl -X POST http://localhost:9090/-/reload     # on the monitoring host, after copying the rules file into rules/
```

futaba has no promtool on the host; run it from the Prometheus image:
`docker run --rm --network none -v "$PWD":/w:ro --entrypoint promtool prom/prometheus:latest test rules /w/storage-rules.test.yml`.

Where the numbers come from:

- `node_zfs_zpool_state`: node_exporter's zfs collector, on every host with ZFS (one series per state, 1 for the
  current one).
- `node_zfs_zpool_errors_total`: `../scripts/zfs_metrics` (root cron, every minute, on tinynas and mementos), the READ,
  WRITE and CKSUM counters of `zpool status` summed over the pool, its vdevs and disks.
- `drivecheck_*`: `../scripts/drivecheck`, once a day on every host (on resume for a roaming host).

| Alert | Fires when | Severity |
|---|---|---|
| ZpoolNotOnline | a pool is DEGRADED, FAULTED, UNAVAIL, SUSPENDED, OFFLINE or REMOVED for 5 min | critical |
| ZpoolErrors | a pool counts read, write or checksum errors | warning |
| DrivePendingSectors | an HDD's ATA attribute 197 or 198 (unreadable sectors) is above 0 | critical |
| DriveSSDPendingPersistent | an SSD's attribute 197 or 198 stays above 0 for 25 h, two daily reads in a row (Crucial MX500 firmware blips 197 for a single read) | warning |
| DriveSectorsReallocated | ATA attribute 5, 187 or 196 rose within 7 days | warning |
| DriveAttrNearThreshold | a normalized SMART attribute is within 10 of its failure threshold | warning |
| DriveNVMeCriticalWarning | an NVMe drive sets any critical-warning bit | critical |
| DriveNVMeMediaErrors | an NVMe drive counts media and data-integrity errors | warning |
| DriveWearHigh | an SSD has used 80% of its rated endurance | warning |
| DriveSASDefectsGrowing | a SAS drive's grown defect list rose within 7 days | warning |
| DriveSASNonMediumSurge | a SAS drive adds more than 500 non-medium errors in a day | warning |
| DriveSASRecoveredReads | a SAS drive's background scan recovered more than 10 reads in its last 168 power-on hours | warning |
| DriveSASLinkErrors | a SAS link error counter is more than 10 above the same reading a day earlier | warning |
| DriveTempNearLimit | a drive is within 3C of its own temperature limit at the daily read | warning |
| DriveKernelIOErrors | the kernel logged I/O errors on the host in the last 24 h | warning |
| DriveLongSelftestFailed | the newest extended self-test failed (interrupted or aborted ones don't count) | warning |

Nothing here fires on absence: no `absent()`, no "host up but metric missing" joins and no age checks. A roaming host
that is away for days just stops sending, and when it comes back with up to 24 h of buffered samples nothing fires
either; the tests cover both cases. Alertmanager on futaba sends every alert to one email receiver, warning and
critical alike.

Tuned to this lab's drives, so change these first elsewhere:

- DriveSASNonMediumSurge: 500 a day sits well above what the eleven Seagate ST8000NM0075 (firmware PS26) in the
  PowerVault MD1200 shelf add on busy days, 1 to 180 in October 2026, on lifetime counts of 50,000 to 113,000.
- DriveSASRecoveredReads: 10 a week sits above the 0 to 2 a week of the 24 Seagate ST1200MM0007 10K drives (firmware
  IS06, about 58,700 power-on hours), several of which log hundreds of older recovered reads.
- DriveSASLinkErrors compares with the reading a day earlier instead of using `increase()`, because SAS PHY counters
  restart at every power cycle and `increase()` would count each restart's fresh readings as new errors. One of the
  R720xd's rear-bay HGST HUSMM8080 SSDs held 40 invalid dwords two days after a power cycle.
- DriveTempNearLimit uses each drive's own limit: the SATA specified maximum, the SAS drive trip temperature or the
  NVMe warning temperature, as drivecheck reads them.

## Hardware and software it has run on

As of 2026-10-16:

- **akechi** (roaming): Framework Laptop 13 Pro (Intel Core Ultra Series 3), board version A5, BIOS 03.02; Intel Core
  Ultra 5 325 (8 threads); 32 GB; WD_BLACK SN850X 1 TB NVMe (firmware 620361WD); no BMC. Kubuntu 26.04.1 LTS, kernel
  7.0.0-34. Ubuntu packages prometheus 2.53.5 (run as an agent), prometheus-node-exporter 1.10.2, smartmontools 7.5,
  nvme-cli 2.16. On Wi-Fi at home and on the strongSwan IKEv2 VPN (NetworkManager) elsewhere.
- **yusuke** (server; a dry run found its existing setup identical): Lenovo ThinkPad T14s Gen 4, AMD Ryzen 7 PRO 7840U,
  32 GB, SK hynix 512 GB NVMe. Ubuntu 24.04.5 LTS, prometheus-node-exporter 1.7.0.
- **futaba** (the monitoring host): Lenovo mini PC 10HY002AUS, Intel Core i5-6500T, 32 GB, 256 GB SATA SSD. Ubuntu
  24.04.5 LTS, Docker 29.1. Prometheus 3.15.0, Grafana, Alertmanager and Glance v0.8.6 in Docker; Cockpit 314 (cockpit-ws)
  on the host.

## Using it on another setup

- **Monitoring host.** Set `FUTABA` (its SSH name) and `PROM_URL` (its Prometheus URL as clients reach it) in the
  environment, or edit them at the top of `deploy-monitoring`. File paths and the Glance port are at the top of
  `futaba-register`.
- **Glance.** It copies the last host card (a `custom-api` widget whose query has `node_cpu_seconds_total` and an
  `instance=` matcher) and changes the instance, title and icon. A roaming card also turns the template's `offline`
  line into the "away" line. The two drive widgets are found by title (`DRIVE_WIDGETS` in `futaba-register`).
- **Hosts.** Debian or Ubuntu only (apt). Server mode needs a fixed address and DNS name for the host (a DHCP
  reservation plus a local DNS record) or `--ip`. Prometheus 2.x runs as an agent with `--enable-feature=agent` and
  3.x with `--agent`; `install-host` picks the right one.
- **Prometheus target labels.** Servers keep this lab's convention of `instance` = the bare IP (a relabel in the `node`
  job strips the port); roaming hosts use their name.

## Removing a host

Not automated. On futaba, delete the host's target from `prometheus.yml` (then `POST /-/reload`), its card and its two
drive-widget clauses from `glance.yml`, and its line in `/etc/cockpit/machines.d/51-lab.json`. On the host, purge
`prometheus-node-exporter` (and `prometheus` on a roaming host) and remove drivecheck's cron file or timer and the
thermal-log unit.

## Known limitation

drivecheck counts kernel "I/O error" lines from the last 24 h, across reboots, as a host alert. On a laptop, a USB
stick pulled out mid-write raises DriveCheckAlert and DriveKernelIOErrors for about a day.
