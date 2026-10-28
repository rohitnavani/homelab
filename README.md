# Homelab Infrastructure

Config, scripts and tools for Rohit's home lab: a 15U rack plus a few small boxes on one UniFi LAN. Servers run
Ubuntu Server 24.04; the storage and compute hosts keep their data on ZFS.

## Machines

### Servers

| Host | Hardware | Function |
|---|---|---|
| **tinynas** | ASUS PRIME B650M-A AX II, Ryzen 5 9600X (6c/12t), 64 GB DDR5, 8x HGST Ultrastar 4 TB SATA, 2x Crucial P3 Plus 1 TB NVMe | Always-on main NAS and services box: Jellyfin, game servers (Valheim, Minecraft), Samba, iSCSI for tinypc, the downloader VM, the fallback DNS resolver (an AdGuard Home replica of futaba's) and a second Cloudflare DDNS updater, a second Cloudflare Tunnel connector, and node-exporter and cAdvisor for its own metrics. Jellyfin is the only site it serves (directly, with its own certificate) |
| **mementos** | Dell PowerEdge R720xd, 2x Xeon E5-2697 v2 (12c/24t each), 256 GB DDR3-1600 RDIMM, 24x Seagate ST1200MM0007 1.2 TB 10K SAS, 2x HGST HUSMM8080 800 GB SAS SSD (rear bays), H710P mini and H810 both in IT mode, iDRAC7 | Primary storage and VM host: Nextcloud AIO (Docker on `vmPool` since 2026-10-14, user files on `vmPool/data` since 2026-10-28), libvirt VMs, the lab NFS shares, and VictoriaMetrics, the lab's long-term metrics store (since 2026-10-18, see Monitoring). Runs the MD1200 and R720xd fan controllers (`fan-control/`). It runs on one power supply: PS1's fan failed, so that unit stays seated but unplugged |
| **MD1200 shelf** | Dell PowerVault MD1200, 2 EMMs (fw 1.06), 12x 8 TB Seagate SAS (11x ST8000NM0075, 1x ST8000NM0185) | Being retired and sold, on the H810. Its `dataPool` moved into `vmPool/data` on 2026-10-28 and stays imported, frozen and read-only, until the drives are wiped |
| **ryuji** | Gigabyte MD70-HB0 in a 2U 12-bay chassis, 2x Xeon E5-2696 v4 (22c/44t each), 128 GB DDR4-2133, onboard LSI SAS3008 to a 12-bay backplane, onboard Intel X540-AT2 (2x 10GBASE-T, one port linked at 1 GbE), 2x Toshiba MG04 4 TB (its other four went to sojiro on 2026-10-15), Avocent BMC, one power supply | Compute box (`computePool`), no workload yet. Runs `ryuji-fan-guard` (`fan-control/`). For now it also holds sojiro's four old drives, not imported, as the rollback for sojiro's pool move |
| **sojiro** | Gigabyte MB10-series board, Xeon D-1521 (4c/8t), 32 GB DDR4, 4x Toshiba MG04 4 TB (from ryuji since 2026-10-15; before that 2x 2 TB and 2x 4 TB) | Backup target: pulls ZFS replicas from tinynas and mementos nightly. Moves offsite later |
| **futaba** | Lenovo mini PC (10HY002AUS), Core i5-6500T, 32 GB DDR4, 256 GB SATA SSD | Network and web services: DNS (AdGuard Home, primary; tinynas runs a synced replica), Cloudflare DDNS (tinynas runs a second updater), strongSwan IPsec VPN, Home Assistant VM, a Cloudflare Tunnel connector (also the public path to Home Assistant), the lab monitoring stack (Prometheus, Alertmanager, Grafana, blackbox probes of the public sites, see Monitoring), the Glance dashboard, the rohitnavani.com resume site, and the lab's only Cockpit |
| **makoto** | ASRock Rack board, Xeon D-1622 (4c/8t), 32 GB DDR4 ECC, 3x 1 TB Crucial MX500 SATA SSD | Admin box: runs the Claude Code sessions (`claude-code` on akechi and tinypc opens one here over SSH) and `lab-scripts`; can build VMs |
| **morgana** (formerly arsene) | Dell Latitude 5420, Core i5-1135G7, 16 GB DDR4, 256 GB NVMe | Experiments (Kubernetes candidate), can build VMs; battery capped at 75-80%. Its internal mic measured noise for the fan tests and was retired on 2026-10-18 |
| **yusuke** | Lenovo ThinkPad T14s Gen 4, Ryzen 7 PRO 7840U (8c/16t), 32 GB LPDDR5-6400, 512 GB NVMe | Headless lab box since 2026-10-13, no workload yet; sleep is disabled and its battery acts as a built-in UPS. Monitored like the servers (node-exporter, drivecheck, futaba's Cockpit) |

### Network and rack

| Device | Function |
|---|---|
| UniFi Dream Wall (Homelab-UDW) | Router, firewall, DHCP and UniFi console; the core both switches plug into |
| Cisco Catalyst WS-C2960G-24TC-L | 24-port gigabit rack switch (IOS 12.2(55)SE12 LAN Base): mementos, ryuji, sojiro and its BMC, the PDU, plus futaba, makoto, morgana and yusuke |
| Unmanaged 2.5 GbE switch | tinynas and tinypc only, so their traffic to each other runs at 2.5 GbE |
| CyberPower PDU20SW8FNET | Switched, metered rack PDU (20 A, 8 outlets); read-only SNMP for current |
| Avocent DSR2030 | 16-port KVM over IP: console access to the rack |
| UniFi Cloud Key Gen2 Plus | Wiped to Debian 11; isolated front-panel status display only |

The two switches each uplink to the UDW and are not linked to each other. Smart-home gadgets sit on an IoT VLAN
(internet only, since 2026-10-18); a management VLAN for the BMCs, PDU and switch is planned.

### Workstations and other devices

| Host | Function |
|---|---|
| tinypc | Desktop workstation (i7-12700F, RTX 3070, Fedora KDE); uses an iSCSI disk from tinynas and runs the lab's local AI stack (Ollama, Open WebUI, SearXNG) |
| akechi (formerly ultrabook) | Framework Laptop 13 Pro (Core Ultra 5 325, 32 GB, Kubuntu); Rohit's daily laptop, used as a thin client; monitored as a roaming host that pushes its metrics (see Monitoring); mounts the lab shares only while mementos answers, at home or over the VPN |
| Raspberry Pi 4 Model B | Raspbian 10 Buster (32-bit, end of life); on the LAN under the lab's SSH key policy, not in monitoring or lab-sync |

## Storage (ZFS)

| Host | Pool | Layout | Use |
|---|---|---|---|
| tinynas | `homePool` | 8x 4 TB raidz2; SLOG and L2ARC on partitions of one NVMe | Media, game servers, Samba, VM images, the iSCSI zvol, logs and `/etc` backups |
| tinynas | `nvmePool` | One NVMe partition (no redundancy) | Minecraft servers, SSD-backed VM images |
| mementos | `vmPool` | 24x 1.2 TB as 12 two-way mirrors; SLOG and L2ARC on a rear SSD | VMs and VM disks; Docker's data-root `vmPool/docker` (Nextcloud AIO's database, app and containers) and AIO's compose folder; the lab's fast NFS share `vmPool/labShare`; `vmPool/data`, mounted at `/dataPool` (since 2026-10-28): Nextcloud's user files (`vmPool/data/nextcloud`, files at `/pool/nextcloud/data`) and the lab's second NFS share `vmPool/data/labShare` |
| mementos | `dataPool` | 12x 8 TB raidz2 on the MD1200; SLOG on a rear SSD | Retired 2026-10-28: its data moved to `vmPool/data` with the same paths. Imported but frozen (unmounted, `canmount=off`, read-only) as the rollback copy until the wipe |
| ryuji | `computePool` | 2x 4 TB mirror (3 mirrors of 4 TB until 2026-10-15) | Compute working storage (empty so far) and logs |
| sojiro | `backupPool` | 4x 4 TB raidz1 (since 2026-10-15; 2 mirrors of 2 TB and 4 TB pairs before) | Replicas of tinynas and mementos |
| makoto | `backupPool` | 3x 1 TB SATA SSD, striped (no redundancy) | Logs; was the tinynas replica target until 2026-09-26 |

Every ZFS host keeps `/var/log` on a pool dataset, so logs are snapshotted too.

### Snapshots and backups

| Job | Host | When | What |
|---|---|---|---|
| `snapshot`, `retention` | tinynas | hourly, daily | All datasets |
| `zfs-snapshot`, `zfs-retention` | mementos, ryuji, sojiro, makoto | hourly, 01:00 | Datasets listed in `/etc/zfs-snapshot-targets` |
| `backup-mementos` | tinynas | 02:00 | Onsite copy of mementos's Nextcloud datasets |
| `replicate`, `prune-replica` | sojiro | 03:00 | syncoid pull of tinynas, mementos's Nextcloud and logs, and all of `vmPool/data/labShare` |

- Snapshots keep 168 hourly plus 4 weekly, 6 monthly and 2 yearly; replicas keep 72 hourly, 14 daily, 8 weekly and
  6 monthly.
- `vmPool/data/labShare` (the `/dataPool` share) also carries this repo's clone, futaba's config backups, tinypc's
  Open WebUI backups and Home Assistant's own backups, so all of them reach sojiro.
- Not backed up, by choice: VMs, Docker data other than Nextcloud's, Jellyfin, Samba, the iSCSI zvol and
  `vmPool/labShare`.

## Monitoring

Prometheus (90 days), Alertmanager, Grafana and Glance run on futaba. Prometheus remote-writes everything to
VictoriaMetrics on mementos, which keeps it for 100 years (history from 2026-10-06).

| Source | Hosts |
|---|---|
| node_exporter | All; akechi pushes from a Prometheus agent so time away isn't an alert |
| `drivecheck` (SMART), `thermal-log` | All |
| `zfs_metrics` | The five ZFS hosts |
| Fan controller state | mementos, ryuji |
| BMC sensors (ipmitool) | ryuji, sojiro, makoto (never mementos: it can upset fan-watchdog) |
| PDU (SNMP), public sites (blackbox) | Polled from futaba |

- Dashboards: Lab - Overview (home page), Network, I/O and Thermal.
- Alerts go by email. Rules: `monitoring/` (storage, lab-sync) and `fan-control/monitoring/` (thermal).
- Add a host: `deploy-monitoring HOST`, or `--roaming` for a laptop (see `monitoring/README.md`).

## Lab scripts on dataPool

This repo is cloned at `/dataPool/homelab` on mementos's NFS share, mounted on every host except sojiro (akechi
only while mementos is reachable).

- Hand-run tools in `bin/` run straight from the share, which is on PATH.
- Unattended scripts run from local copies. Every 5 minutes `lab-sync` installs the version committed on main, as
  `deploy.list` says. The fan controllers are check-only, and sojiro is updated by hand.
- `private/` is a separate local repo, never pushed.

```sh
lab-scripts                        # on makoto: anything uncommitted, unpushed or out of step
lab-scripts sync HOST              # sync a host now
lab-scripts install NAME sojiro    # sojiro's only way to get an update
lab-scripts setup HOST             # new host, then: lab-scripts enable-sync HOST
lab-scripts push                   # secret scan, then push via tinynas
```

To change a script: edit in `/dataPool/homelab`, commit, `lab-scripts push`. Hosts have it within 5 minutes.

## Repository structure

```text
.
├── README.md                   # This file: the machines and what they do
├── .gitignore                  # Keeps .env secrets, databases and service data out of git
├── bin/                        # On every lab host's PATH from /dataPool/homelab: the tools you run as yourself
│                               #   (links into scripts/ and monitoring/)
├── deploy.list                 # How each host runs each script: [copies] kept in step by lab-sync, or [links]
├── private/                    # Not in git here: the share copy's own local repo of scripts that are not public
├── docker-compose/             # Container services (paths come from ${COMPOSE_BASE_PATH} in a gitignored .env)
│   ├── AdGuardHome/            # DNS ad-blocking (runs on futaba)
│   ├── adguardhome-fallback/   # AdGuard Home replica of futaba's, kept in sync by adguardhome-sync (tinynas)
│   ├── blackbox/               # Probes of the public sites with site-down and cert-expiry alerts (futaba)
│   ├── cloudflare-ddns/        # Dynamic DNS for rohitnavani.com (futaba; docker-compose.tinynas.yml for tinynas)
│   ├── exporters/              # node-exporter (tinynas)
│   └── resume-site/            # nginx for the rohitnavani.com resume site, with its host nginx site (futaba)
├── fail2ban/                   # sshd jails for futaba (reachable from the internet) and tinynas
├── fan-control/                # Fan controllers for mementos, the MD1200 shelf and ryuji, with tests and test tools
│                               #   (see fan-control/README.md for the exact hardware)
├── monitoring/                 # deploy-monitoring: adds a host to the lab's monitoring in one command; servers are
│                               #   scraped, roaming hosts such as akechi push from a Prometheus agent. Also the
│                               #   storage and lab-sync alert rules, with promtool tests
└── scripts/                    # Installed on the hosts by lab-sync (cron, services), or run by hand from bin/
    ├── autorar                 # Compresses finished downloads (tinynas; from bin/)
    ├── backup-mementos         # Nightly syncoid pull of mementos's Nextcloud datasets, the onsite copy (tinynas; sbin)
    ├── drive-selftest          # Starts SMART self-tests on every SATA, SAS and NVMe drive (weekly short, monthly long)
    ├── drivecheck              # Daily SMART check of SATA, SAS and NVMe drives (v2: Python, smartctl JSON), Prometheus
    │                           #   textfile output (all hosts)
    ├── drivecheck.cron         # /etc/cron.d/drivecheck: check 00:00, short self-tests Sat 22:00, long first Mon 08:00
    │                           #   (tinynas runs the same jobs from root's crontab)
    ├── futaba-backup           # Nightly copy of futaba's service configs to labShare, secrets redacted (futaba)
    ├── lab-bmc-ip.service      # At boot: sojiro-bmc-ip until the BMC answers, 10 tries 30 s apart (sojiro)
    ├── lab-scripts             # Compares and installs the hosts' copies, sets hosts up, pushes to GitHub (from bin/)
    ├── lab-sync                # Keeps a host's [copies] on the committed version every 5 minutes (all hosts but sojiro)
    ├── nextcloud-update        # Nextcloud AIO file permissions and rescan; skips if the data mount is missing (mementos)
    ├── newvm                   # Interactive: creates a KVM guest on whichever host it runs on (from bin/)
    ├── prune-replica           # GFS pruning of received replicas, run by replicate (sojiro)
    ├── replicate               # Nightly syncoid pull of tinynas and mementos datasets (sojiro)
    ├── resume-uptime           # Writes tinynas's uptime for the resume site from Prometheus (futaba, every minute)
    ├── retention               # GFS snapshot pruning (tinynas)
    ├── root_disk_metrics       # Root filesystem usage for Prometheus (tinynas)
    ├── snapshot                # Hourly ZFS snapshots (tinynas)
    ├── sojiro-bmc-ip           # sojiro's BMC address (DHCP) from ipmitool lan print, checked by MAC and ARP, for the
    │                           #   scripts that call its web UI (sojiro; sbin)
    ├── zfs-retention           # GFS pruning for /etc/zfs-snapshot-targets (mementos, ryuji, sojiro, makoto; sbin)
    ├── zfs-snapshot            # Hourly snapshots of /etc/zfs-snapshot-targets (same hosts; /usr/local/sbin)
    ├── zfs_metrics             # ZFS pool and I/O metrics for Prometheus (all five ZFS hosts)
    └── zfs_metrics.cron        # /etc/cron.d/zfs-metrics: every minute (makoto, sojiro; the others use root's crontab)
```

## VMs

`newvm` (or `newwin11`, `new2k22`, `new2k25`, `newubuntu`, `newrocky`) builds a KVM guest on the host it runs on,
bridged to the LAN on `br0`.

- ISOs are in `/vmPool/img`, shared by the whole lab.
- Disks go to `<pool>/kvm/<name>` on mementos and ryuji, and to `/vmPool/<host>/<name>/` on the share elsewhere
  (NFS speed, not backed up).
- Hosts with `br0`: mementos, ryuji, tinynas, futaba, makoto, morgana, yusuke, tinypc. Not sojiro or akechi.
- Big or AVX2 VMs (Rocky 10, Kubernetes) go on ryuji; mementos's Ivy Bridge Xeons lack AVX2.
- Every VM gets one socket with N cores. Windows VMs also get the full Hyper-V enlightenment set (synic, stimer,
  avic and the rest), which virt-install 4.1 leaves out. To add them to an older VM, apply the same `--xml` edits
  with `virt-xml <vm> --edit`, then shut it down and start it (a reboot from inside Windows keeps the old config).

## Not in the repo

Nextcloud AIO, cloudflared, Jellyfin, the game servers, Home Assistant, futaba's Prometheus/Alertmanager/Grafana
configs, VictoriaMetrics, Glance, tinypc's local AI stack and `private/`.

## Using this on other hardware

- Fan control is specific to these boards; read `fan-control/README.md` first.
- Snapshots: list your datasets in `/etc/zfs-snapshot-targets`. `replicate`'s `SOURCES` and `DEST` are lab-specific.
- Lab scripts: set `SHARE` in `scripts/lab-scripts`, `REPO` in `scripts/lab-sync` and the hosts in `deploy.list`.
- VMs: install libvirt, qemu, virtinst, OVMF and swtpm, bridge the LAN NIC as `br0`, set `NEWVM_SHARE` or
  `NEWVM_BASE`.
- Monitoring: change the host names and futaba paths in `deploy-monitoring`.
