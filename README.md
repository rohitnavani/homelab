# Homelab Infrastructure

Configuration, scripts and tools for Rohit's home lab: a 15U rack plus a few small boxes on one UniFi-routed LAN.
Every server runs Ubuntu Server 24.04 with ZFS for storage. The repo started as the config for tinynas alone and now
covers the whole lab.

## Machines

### Servers

| Host | Hardware | Function |
|---|---|---|
| **tinynas** | ASUS PRIME B650M-A AX II, Ryzen 5 9600X (6c/12t), 64 GB DDR5, 8x HGST Ultrastar 4 TB SATA, 2x Crucial P3 Plus 1 TB NVMe | Always-on main NAS and services box: Jellyfin, game servers (Valheim, Minecraft), Samba, iSCSI for tinypc, the downloader VM, a second Cloudflare Tunnel connector, and node-exporter and cAdvisor for its own metrics. Jellyfin is the only site it serves (directly, with its own certificate) |
| **mementos** | Dell PowerEdge R720xd, 2x Xeon E5-2697 v2 (12c/24t each), 256 GB DDR3-1600 RDIMM, 24x Seagate ST1200MM0007 1.2 TB 10K SAS, 2x HGST HUSMM8080 800 GB SAS SSD (rear bays), H710P mini and H810 both in IT mode, iDRAC7 | Primary storage and VM host: Nextcloud AIO (Docker on `vmPool` since 2026-10-14, user files on `dataPool`), libvirt VMs, the lab NFS shares. Runs the MD1200 and R720xd fan controllers (`fan-control/`) |
| **MD1200 shelf** | Dell PowerVault MD1200, 2 EMMs (fw 1.06), 12x 8 TB Seagate SAS (11x ST8000NM0075, 1x ST8000NM0185) | Bulk storage for mementos (`dataPool`), on the H810 |
| **ryuji** | Gigabyte MD70-HB0 in a 2U 12-bay chassis, 2x Xeon E5-2696 v4 (22c/44t each), 128 GB DDR4-2133, onboard LSI SAS3008 to a 12-bay backplane, 6x Toshiba MG04 4 TB, Avocent BMC | Compute box (`computePool`), no workload yet. Runs `ryuji-fan-guard` (`fan-control/`) |
| **sojiro** | Gigabyte MB10-series board, Xeon D-1521 (4c/8t), 32 GB DDR4, 4x Toshiba MG04 (2x 2 TB, 2x 4 TB) | Backup target: pulls ZFS replicas from tinynas and mementos nightly. Moves offsite later |
| **futaba** | Lenovo mini PC (10HY002AUS), Core i5-6500T, 32 GB DDR4, 256 GB SATA SSD | Network and web services: DNS (AdGuard Home), Cloudflare DDNS, strongSwan IPsec VPN, Home Assistant VM, a Cloudflare Tunnel connector, the lab monitoring stack (Prometheus, Alertmanager, Grafana, blackbox probes of the public sites), the Glance dashboard, the rohitnavani.com resume site, and the lab's only Cockpit |
| **makoto** | ASRock Rack board, Xeon D-1622 (4c/8t), 32 GB DDR4 ECC, 3x 1 TB Crucial MX500 SATA SSD | Admin box: runs the Claude Code sessions and the lab test loggers |
| **morgana** (formerly arsene) | Dell Latitude 5420, Core i5-1135G7, 16 GB DDR4, 256 GB NVMe | Experiments (Kubernetes candidate); its internal mic is the lab noise meter for fan tests |

### Network and rack

| Device | Function |
|---|---|
| UniFi Dream Wall (Homelab-UDW) | Router, DHCP and UniFi console for the LAN |
| Cisco Catalyst WS-C2960G-24TC-L | 24-port gigabit rack switch |
| CyberPower PDU20SW8FNET | Switched, metered rack PDU (20 A, 8 outlets); read-only SNMP for current |
| AvoSense 16-port KVM over IP | Console access to the rack |
| UniFi Cloud Key Gen2 Plus | Wiped to Debian 11; isolated front-panel status display only |

### Workstations

| Host | Function |
|---|---|
| tinypc | Desktop workstation (i7-12700F, Fedora KDE); uses an iSCSI disk from tinynas |
| ultrabook | Framework Laptop 13 (Kubuntu) |

## Storage (ZFS)

| Host | Pool | Layout | Use |
|---|---|---|---|
| tinynas | `homePool` | 8x 4 TB raidz2; SLOG and L2ARC on partitions of one NVMe | Media, game servers, Samba, VM images, the iSCSI zvol, logs and `/etc` backups |
| tinynas | `nvmePool` | One NVMe partition (no redundancy) | Minecraft servers, SSD-backed VM images |
| mementos | `vmPool` | 24x 1.2 TB as 12 two-way mirrors; SLOG and L2ARC on a rear SSD | VMs and VM disks; Docker's data-root `vmPool/docker` (Nextcloud AIO's database, app and containers) and AIO's compose folder; the lab's fast NFS share `vmPool/labShare` |
| mementos | `dataPool` | 12x 8 TB raidz2 on the MD1200; SLOG on a rear SSD | Nextcloud user files (`dataPool/nextcloud`), bulk storage; the lab's bulk NFS share `dataPool/labShare` |
| ryuji | `computePool` | 6x 4 TB as 3 two-way mirrors | Compute working storage (empty so far) and logs |
| sojiro | `backupPool` | 2 mirrors (2 TB + 4 TB pairs) | Replicas of tinynas and mementos |
| makoto | `backupPool` | 3x 1 TB SATA SSD, striped (no redundancy) | Logs; was the tinynas replica target until 2026-09-26 |

Every host with a ZFS pool keeps `/var/log` on a dataset of that pool (tinynas `homePool/logBackup`, mementos
`vmPool/logs`, ryuji `computePool/logs`, sojiro and makoto `backupPool/logs`). Those datasets are snapshotted hourly
and pruned daily on a grandfather-father-son schedule: the newest 168 snapshots, plus the last one of each of 4 weeks,
6 months and 2 years. logrotate stays at the Ubuntu default (weekly, 4 kept) on purpose: with a monthly tier, nearly
every log line lands in a snapshot.

- tinynas runs `scripts/snapshot` and `scripts/retention` over all of its datasets.
- mementos, ryuji, sojiro and makoto run `scripts/zfs-snapshot` (hourly) and `scripts/zfs-retention` (01:00) from
  `/usr/local/sbin` over the dataset roots listed in `/etc/zfs-snapshot-targets`: Nextcloud, Docker, the VMs,
  the logs and the two `labShare` NFS shares on mementos, only the logs dataset on the others.
- sojiro's `scripts/replicate` (03:00) pulls replicas into `backupPool/<source pool>/...` with syncoid and prunes them
  with `scripts/prune-replica` (72 hourly, 14 daily, 8 weekly, 6 monthly), independent of the source's retention.
  Its mountpoint reset and pruning run per replica tree, so they never touch sojiro's own `backupPool/logs`.
- tinynas's `scripts/backup-mementos` (02:00, from `/usr/local/sbin`) pulls mementos's Nextcloud datasets
  (`dataPool/nextcloud`, `vmPool/docker`, `vmPool/docker-compose/nextcloud-aio`) into
  `homePool/backups/mementos/<pool>/...` as the onsite copy and prunes them with `scripts/prune-replica`. The
  in-between datasets there are `canmount=off`, so the read-only replicas can mount below them.

To reuse these elsewhere: list your datasets in `/etc/zfs-snapshot-targets`; `replicate`'s `SOURCES` and `DEST` are
specific to this lab.

## Repository structure

```text
.
├── README.md                   # This file: the machines and what they do
├── .gitignore                  # Keeps .env secrets, databases and service data out of git
├── docker-compose/             # Container services (paths come from ${COMPOSE_BASE_PATH} in a gitignored .env)
│   ├── AdGuardHome/            # DNS ad-blocking (runs on futaba)
│   ├── blackbox/               # Probes of the public sites with site-down and cert-expiry alerts (futaba)
│   ├── cloudflare-ddns/        # Dynamic DNS for rohitnavani.com (runs on futaba)
│   ├── exporters/              # node-exporter (tinynas)
│   └── resume-site/            # nginx for the rohitnavani.com resume site, with its host nginx site (futaba)
├── fan-control/                # Fan controllers for mementos, the MD1200 shelf and ryuji, with tests and test tools
│                               #   (see fan-control/README.md for the exact hardware)
└── scripts/                    # Installed to /usr/local/bin and run from root's cron
    ├── autorar                 # Compresses finished downloads (tinynas)
    ├── backup-mementos         # Nightly syncoid pull of mementos's Nextcloud datasets, the onsite copy (tinynas; sbin)
    ├── drive-selftest          # Starts SMART self-tests on every SATA, SAS and NVMe drive (weekly short, monthly long)
    ├── drivecheck              # Daily SMART check of SATA, SAS and NVMe drives, Prometheus textfile output (all hosts)
    ├── drivecheck.cron         # /etc/cron.d/drivecheck: check 00:00, short self-tests Sat 22:00, long the 1st 12:00
    │                           #   (tinynas runs the same jobs from root's crontab)
    ├── futaba-backup           # Nightly copy of futaba's service configs to labShare, secrets redacted (futaba)
    ├── nextcloud-update        # Nextcloud AIO file permissions and rescan; skips if the data mount is missing (mementos)
    ├── newvm                   # Interactive: creates a KVM guest in its own ZFS dataset (mementos, ryuji; not cron)
    ├── prune-replica           # GFS pruning of received replicas, run by replicate (sojiro)
    ├── replicate               # Nightly syncoid pull of tinynas and mementos datasets (sojiro)
    ├── resume-uptime           # Writes tinynas's uptime for the resume site from Prometheus (futaba, every minute)
    ├── retention               # GFS snapshot pruning (tinynas)
    ├── root_disk_metrics       # Root filesystem usage for Prometheus (tinynas)
    ├── snapshot                # Hourly ZFS snapshots (tinynas)
    ├── zfs-retention           # GFS pruning for /etc/zfs-snapshot-targets (mementos, ryuji, sojiro, makoto; sbin)
    ├── zfs-snapshot            # Hourly snapshots of /etc/zfs-snapshot-targets (same hosts; /usr/local/sbin)
    └── zfs_metrics             # ZFS pool and I/O metrics for Prometheus (tinynas, mementos, ryuji)
```

## VMs

`scripts/newvm` creates a libvirt/KVM guest in its own ZFS dataset `<pool>/kvm/<name>` (recordsize 64K, holding the
qcow2 and a copy of its XML), from ISOs in `<pool>/kvm/img`, bridged onto the LAN through `br0`, with VNC on
the next free port from 5900. Profiles: `win11`, `2k22`, `2k25` (Secure Boot with Microsoft keys, TPM 2.0, the virtio-win
CD), `ubuntu`, `rocky` (plain UEFI; Rocky 10 needs AVX2, which mementos's Ivy Bridge Xeons lack) and `iso` (any ISO).
Install it to `/usr/local/bin` with the symlinks `newwin11`, `new2k22`, `new2k25`, `newubuntu` and `newrocky`, which pick
the profile. It replaced tinynas's `~/newwin11`, `~/new2k22` and `~/new2k25` on 2026-10-06.

It uses the first of `vmPool/kvm` (mementos), `computePool/kvm` (ryuji) and `homePool/kvm` (tinynas) that exists, and
stops early if the `img` folder or `br0` is missing. Installed on mementos and ryuji since 2026-10-14; ryuji still
needs its `computePool/kvm` dataset, the ISOs and a `br0` bridge before it can build VMs. VMs that need many cores
or AVX2 (Rocky 10, Kubernetes nodes) belong on ryuji (2x E5-2696 v4, 88 threads); small always-on VMs such as
2k25-test stay on mementos, next to their storage.

To reuse it elsewhere: it needs libvirt, virtinst, ovmf and swtpm, a `<pool>/kvm` dataset with an `img` folder of ISOs
(the ISO file names are in the profile table near the top), and a `br0` bridge. Set `NEWVM_BASE=<pool>/kvm` (or edit
the `BASES` list) for a dataset with another name.

Not in the repo: Nextcloud AIO, cloudflared, Jellyfin and the game servers.
