# Homelab Infrastructure

Configuration, scripts and tools for Rohit's home lab: a 15U rack plus a few small boxes on one UniFi-routed LAN.
Every server runs Ubuntu Server 24.04. The storage and compute hosts (tinynas, mementos, ryuji, sojiro and makoto)
keep their data on ZFS; futaba, morgana and yusuke have one ext4 disk and no pools. The repo started as the config
for tinynas alone and now covers the whole lab.

## Machines

### Servers

| Host | Hardware | Function |
|---|---|---|
| **tinynas** | ASUS PRIME B650M-A AX II, Ryzen 5 9600X (6c/12t), 64 GB DDR5, 8x HGST Ultrastar 4 TB SATA, 2x Crucial P3 Plus 1 TB NVMe | Always-on main NAS and services box: Jellyfin, game servers (Valheim, Minecraft), Samba, iSCSI for tinypc, the downloader VM, the fallback DNS resolver (an AdGuard Home replica of futaba's) and a second Cloudflare DDNS updater, a second Cloudflare Tunnel connector, and node-exporter and cAdvisor for its own metrics. Jellyfin is the only site it serves (directly, with its own certificate) |
| **mementos** | Dell PowerEdge R720xd, 2x Xeon E5-2697 v2 (12c/24t each), 256 GB DDR3-1600 RDIMM, 24x Seagate ST1200MM0007 1.2 TB 10K SAS, 2x HGST HUSMM8080 800 GB SAS SSD (rear bays), H710P mini and H810 both in IT mode, iDRAC7 | Primary storage and VM host: Nextcloud AIO (Docker on `vmPool` since 2026-10-14, user files on `dataPool`), libvirt VMs, the lab NFS shares. Runs the MD1200 and R720xd fan controllers (`fan-control/`) |
| **MD1200 shelf** | Dell PowerVault MD1200, 2 EMMs (fw 1.06), 12x 8 TB Seagate SAS (11x ST8000NM0075, 1x ST8000NM0185) | Bulk storage for mementos (`dataPool`), on the H810 |
| **ryuji** | Gigabyte MD70-HB0 in a 2U 12-bay chassis, 2x Xeon E5-2696 v4 (22c/44t each), 128 GB DDR4-2133, onboard LSI SAS3008 to a 12-bay backplane, 2x Toshiba MG04 4 TB (its other four went to sojiro on 2026-10-15), Avocent BMC | Compute box (`computePool`), no workload yet. Runs `ryuji-fan-guard` (`fan-control/`). For now it also holds sojiro's four old drives, not imported, as the rollback for sojiro's pool move |
| **sojiro** | Gigabyte MB10-series board, Xeon D-1521 (4c/8t), 32 GB DDR4, 4x Toshiba MG04 4 TB (from ryuji since 2026-10-15; before that 2x 2 TB and 2x 4 TB) | Backup target: pulls ZFS replicas from tinynas and mementos nightly. Moves offsite later |
| **futaba** | Lenovo mini PC (10HY002AUS), Core i5-6500T, 32 GB DDR4, 256 GB SATA SSD | Network and web services: DNS (AdGuard Home, primary; tinynas runs a synced replica), Cloudflare DDNS (tinynas runs a second updater), strongSwan IPsec VPN, Home Assistant VM, a Cloudflare Tunnel connector, the lab monitoring stack (Prometheus, Alertmanager, Grafana, blackbox probes of the public sites), the Glance dashboard, the rohitnavani.com resume site, and the lab's only Cockpit |
| **makoto** | ASRock Rack board, Xeon D-1622 (4c/8t), 32 GB DDR4 ECC, 3x 1 TB Crucial MX500 SATA SSD | Admin box: runs the Claude Code sessions and the lab test loggers |
| **morgana** (formerly arsene) | Dell Latitude 5420, Core i5-1135G7, 16 GB DDR4, 256 GB NVMe | Experiments (Kubernetes candidate); its internal mic is the lab noise meter for fan tests |
| **yusuke** | Lenovo ThinkPad T14s Gen 4, Ryzen 7 PRO 7840U (8c/16t), 32 GB LPDDR5-6400, 512 GB NVMe | Headless lab box since 2026-10-13, no workload yet; sleep is disabled and its battery acts as a built-in UPS. Monitored like the servers (node-exporter, drivecheck, futaba's Cockpit) |

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
| tinypc | Desktop workstation (i7-12700F, RTX 3070, Fedora KDE); uses an iSCSI disk from tinynas and runs the lab's local AI stack (Ollama, Open WebUI, SearXNG) |
| akechi (formerly ultrabook) | Framework Laptop 13 Pro (Core Ultra 5 325, 32 GB, Kubuntu); Rohit's daily laptop, used as a thin client; monitored as a roaming host that pushes its metrics (see `monitoring/`) |

## Storage (ZFS)

| Host | Pool | Layout | Use |
|---|---|---|---|
| tinynas | `homePool` | 8x 4 TB raidz2; SLOG and L2ARC on partitions of one NVMe | Media, game servers, Samba, VM images, the iSCSI zvol, logs and `/etc` backups |
| tinynas | `nvmePool` | One NVMe partition (no redundancy) | Minecraft servers, SSD-backed VM images |
| mementos | `vmPool` | 24x 1.2 TB as 12 two-way mirrors; SLOG and L2ARC on a rear SSD | VMs and VM disks; Docker's data-root `vmPool/docker` (Nextcloud AIO's database, app and containers) and AIO's compose folder; the lab's fast NFS share `vmPool/labShare` |
| mementos | `dataPool` | 12x 8 TB raidz2 on the MD1200; SLOG on a rear SSD | Nextcloud user files (`dataPool/nextcloud`), bulk storage; the lab's bulk NFS share `dataPool/labShare` |
| ryuji | `computePool` | 2x 4 TB mirror (3 mirrors of 4 TB until 2026-10-15) | Compute working storage (empty so far) and logs |
| sojiro | `backupPool` | 4x 4 TB raidz1 (since 2026-10-15; 2 mirrors of 2 TB and 4 TB pairs before) | Replicas of tinynas and mementos |
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
  It pulls tinynas's compose folders, `/etc` copy, logs, installed scripts, game and Minecraft servers, mementos's
  Nextcloud datasets and logs, and all of `dataPool/labShare`. That share also carries what has no ZFS dataset of its
  own: this repo's clone (`/dataPool/homelab`, the lab's scripts) and `/dataPool/backups`, where futaba's nightly
  `futaba-backup` puts its service configs (secrets redacted) and tinypc puts its Open WebUI backups. Home
  Assistant (the HAOS VM on futaba) writes its own encrypted automatic backups to the child dataset
  `dataPool/labShare/homeassistant`, exported over NFS to the VM's address only and added in HA as the backup mount
  `labshare` (Settings > System > Storage). To copy this, change the address in its `sharenfs`. VMs, Docker
  data-roots other than Nextcloud AIO's, Jellyfin, samba and the iSCSI zvol are not backed up, by choice.
- tinynas's `scripts/backup-mementos` (02:00, from `/usr/local/sbin`) pulls mementos's Nextcloud datasets
  (`dataPool/nextcloud`, `vmPool/docker`, `vmPool/docker-compose/nextcloud-aio`) into
  `homePool/backups/mementos/<pool>/...` as the onsite copy and prunes them with `scripts/prune-replica`. The
  in-between datasets there are `canmount=off`, so the read-only replicas can mount below them.

To reuse these elsewhere: list your datasets in `/etc/zfs-snapshot-targets`; `replicate`'s `SOURCES` and `DEST` are
specific to this lab.

## Lab scripts on dataPool

Since 2026-10-16 the lab keeps one copy of its scripts: a clone of this repo at `/dataPool/homelab`, the same path on
every host that mounts mementos's `dataPool/labShare` NFS share (NFS 4.2, hard mounts; on mementos itself the path
is a symlink to `/dataPool/labShare/homelab`). That is makoto, tinypc, futaba, tinynas, morgana, ryuji, yusuke and
mementos. sojiro (the backup box, going offsite) and akechi (a laptop) do not mount the share.

- **Tools you run as yourself: straight from the share.** `/etc/profile.d/lab-scripts.sh` appends `bin/` to PATH on
  those hosts, last, so a host's own commands win: `newvm` with its profile names, `autorar`, `deploy-monitoring`
  and `lab-scripts`. An edit there is live on every host at once. On mementos and ryuji `/usr/local/bin/newvm` is a
  symlink to the share. `lab-scripts setup` also appends the two folders to sudo's `secure_path` in
  `/etc/sudoers.d/lab-scripts`, after every entry the host had, so `sudo rename-host` works; `newvm` asks for sudo itself.
- **What root runs, from cron, systemd or boot: installed on each host.** The share is a hard mount that hangs while
  mementos is down, and nothing unattended (least of all a fan controller) may wait on it; the share is also
  writable from every client, so root never runs it unattended. `deploy.list` says which repo file is installed
  where; `lab-scripts status` compares every copy with its source, `lab-scripts install NAME HOST` copies one into
  place (the old one kept as `.bak-DATE`, the new one swapped in with a rename). The same goes for `autorar` on
  tinynas, which a passwordless sudo rule names.
- **Not public yet: `private/`.** Its own git repo inside the share copy, ignored by this one and never pushed: the
  other hosts' service scripts, the local AI tools, `rename-host` (its `bin/` is on PATH too) and `sudo-grant` and
  `sudo-revoke`, which read your sudo password and so stay installed on makoto and akechi rather than run from the
  share.

```sh
lab-scripts                        # run on makoto: what is uncommitted, unpushed or out of line
lab-scripts diff zfs-snapshot mementos
lab-scripts install drivecheck sojiro ryuji
lab-scripts setup yusuke           # the PATH snippet and sudo's secure_path (once per host that mounts the share)
lab-scripts timer                  # on mementos: pull GitHub's main into the share every 15 minutes
lab-scripts push                   # checks the new commits for secrets and vendor names, then pushes via tinynas
```

Edit in `/dataPool/homelab`, commit one version per change that ran (only your own files: `git add <paths>`), and
push with `lab-scripts push`: tinynas holds the GitHub credential. `lab-scripts timer` keeps the share in step with
commits pushed from other clones; it only fast-forwards, so it never touches uncommitted or unpushed work. The fan
controllers are `check-only` in `deploy.list`: a new version goes in with a service restart and a live check (see
`fan-control/README.md`), never by `lab-scripts install`.

While mementos is down, a shell on a client can hang on Tab completion or a mistyped command, because the shell
searches the share last. In that shell, `export PATH=${PATH%%:/dataPool/homelab/*}` drops the share from PATH.

To reuse this elsewhere: any path every host mounts will do. Change `SHARE` at the top of `scripts/lab-scripts`
and the hosts in `deploy.list`. With root squashing, keep the files world-readable, because root reads the share as
nobody.

## Repository structure

```text
.
├── README.md                   # This file: the machines and what they do
├── .gitignore                  # Keeps .env secrets, databases and service data out of git
├── bin/                        # On every lab host's PATH from /dataPool/homelab: the tools you run as yourself
│                               #   (links into scripts/ and monitoring/)
├── deploy.list                 # Which file here is installed where (lab-scripts status / install)
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
│                               #   scraped, roaming hosts such as akechi push from a Prometheus agent
└── scripts/                    # Installed to /usr/local/bin and run from root's cron, or run by hand from bin/
    ├── autorar                 # Compresses finished downloads (tinynas; from bin/)
    ├── backup-mementos         # Nightly syncoid pull of mementos's Nextcloud datasets, the onsite copy (tinynas; sbin)
    ├── drive-selftest          # Starts SMART self-tests on every SATA, SAS and NVMe drive (weekly short, monthly long)
    ├── drivecheck              # Daily SMART check of SATA, SAS and NVMe drives (v2: Python, smartctl JSON), Prometheus
    │                           #   textfile output (all hosts)
    ├── drivecheck.cron         # /etc/cron.d/drivecheck: check 00:00, short self-tests Sat 22:00, long first Mon 08:00
    │                           #   (tinynas runs the same jobs from root's crontab)
    ├── futaba-backup           # Nightly copy of futaba's service configs to labShare, secrets redacted (futaba)
    ├── lab-scripts             # Compares and installs the hosts' copies, sets hosts up, pushes to GitHub (from bin/)
    ├── nextcloud-update        # Nextcloud AIO file permissions and rescan; skips if the data mount is missing (mementos)
    ├── newvm                   # Interactive: creates a KVM guest in its own ZFS dataset (mementos, ryuji; from bin/)
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
It runs from `bin/` on the share (see "Lab scripts on dataPool"), where the symlinks `newwin11`, `new2k22`, `new2k25`,
`newubuntu` and `newrocky` pick the profile; elsewhere, install it to `/usr/local/bin` with the same symlinks. It
replaced tinynas's `~/newwin11`, `~/new2k22` and `~/new2k25` on 2026-10-06.

It uses the first of `vmPool/kvm` (mementos), `computePool/kvm` (ryuji) and `homePool/kvm` (tinynas) that exists, and
stops early if the `img` folder or `br0` is missing. On mementos and ryuji since 2026-10-14 (since 10-16 their
`/usr/local/bin/newvm` is a symlink to the share); ryuji still needs its `computePool/kvm` dataset, the ISOs and a
`br0` bridge before it can build VMs. VMs that need many cores
or AVX2 (Rocky 10, Kubernetes nodes) belong on ryuji (2x E5-2696 v4, 88 threads); small always-on VMs such as
2k25-test stay on mementos, next to their storage.

To reuse it elsewhere: it needs libvirt, virtinst, ovmf and swtpm, a `<pool>/kvm` dataset with an `img` folder of ISOs
(the ISO file names are in the profile table near the top), and a `br0` bridge. Set `NEWVM_BASE=<pool>/kvm` (or edit
the `BASES` list) for a dataset with another name.

Not in the repo: Nextcloud AIO, cloudflared, Jellyfin, the game servers, the Home Assistant VM, the rest of
futaba's monitoring stack (the Prometheus, Alertmanager and Grafana compose and configs; `docker-compose/blackbox`
holds only the probe parts), the Glance dashboard config and tinypc's local AI stack.
