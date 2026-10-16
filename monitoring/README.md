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
| SMART self-tests | short on Saturday 22:00, long on the 1st at 12:00 | none scheduled (see below) |
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
- **No self-test false alarms.** A suspend aborts a running SMART self-test, and drivecheck reports an aborted test as a
  failure, so none are scheduled. Run `sudo drive-selftest short` by hand on AC power if you want one.
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

drivecheck counts any kernel "I/O error" since boot as a drive alert. On a laptop, a USB stick pulled out mid-write
can raise DriveCheckAlert until the next reboot.
