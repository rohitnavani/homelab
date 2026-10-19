# Homelab Infrastructure

Configuration, scripts and tools for Rohit's home lab: a 15U rack plus a few small boxes on one UniFi-routed LAN
(smart-home gadgets sit apart on their own IoT VLAN). Every server runs Ubuntu Server 24.04. The storage and compute
hosts (tinynas, mementos, ryuji, sojiro and makoto) keep their data on ZFS; futaba, morgana and yusuke have one ext4
disk and no pools. Every lab host reports to one Prometheus, the lab's scripts live in one shared clone of this
repo, and any host with a `br0` bridge can build VMs. The repo started as the config for tinynas alone and now covers
the whole lab.

## Machines

### Servers

| Host | Hardware | Function |
|---|---|---|
| **tinynas** | ASUS PRIME B650M-A AX II, Ryzen 5 9600X (6c/12t), 64 GB DDR5, 8x HGST Ultrastar 4 TB SATA, 2x Crucial P3 Plus 1 TB NVMe | Always-on main NAS and services box: Jellyfin, game servers (Valheim, Minecraft), Samba, iSCSI for tinypc, the downloader VM, the fallback DNS resolver (an AdGuard Home replica of futaba's) and a second Cloudflare DDNS updater, a second Cloudflare Tunnel connector, and node-exporter and cAdvisor for its own metrics. Jellyfin is the only site it serves (directly, with its own certificate) |
| **mementos** | Dell PowerEdge R720xd, 2x Xeon E5-2697 v2 (12c/24t each), 256 GB DDR3-1600 RDIMM, 24x Seagate ST1200MM0007 1.2 TB 10K SAS, 2x HGST HUSMM8080 800 GB SAS SSD (rear bays), H710P mini and H810 both in IT mode, iDRAC7 | Primary storage and VM host: Nextcloud AIO (Docker on `vmPool` since 2026-10-14, user files on `dataPool`), libvirt VMs, the lab NFS shares, and VictoriaMetrics, the lab's long-term metrics store (since 2026-10-18, see Monitoring). Runs the MD1200 and R720xd fan controllers (`fan-control/`). It runs on one power supply: PS1's fan failed, so that unit stays seated but unplugged |
| **MD1200 shelf** | Dell PowerVault MD1200, 2 EMMs (fw 1.06), 12x 8 TB Seagate SAS (11x ST8000NM0075, 1x ST8000NM0185) | Bulk storage for mementos (`dataPool`), on the H810 |
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

The two switches are not linked to each other: each uplinks to the UDW, so only tinynas and tinypc cross it to reach
the rack. Every Catalyst port is 1 GbE, so a host's own port is the limit for NFS from mementos.

VLANs (since 2026-10-18): the lab and its clients stay on the untagged default network. Smart-home gadgets (lights and
appliances, all cloud-controlled) moved to an IoT VLAN with its own SSID and firewall zone: internet only, the
gateway's DNS, and the LAN blocked except Home Assistant reaching in, with mDNS on. A management VLAN for the BMCs,
the iDRAC, the PDU and the switch comes later; it needs the Catalyst's login recovered first, since the 2.5 GbE switch
cannot carry tags.

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

## Monitoring

futaba runs the stack in Docker: Prometheus (90 days on its own disk), Alertmanager, Grafana and the Glance
dashboard, with Cockpit beside them for a web shell on the servers.

- **What reaches Prometheus.** node_exporter on every Linux host, scraped every 15 s. akechi is the exception: a
  Prometheus agent on the laptop pushes its samples (remote write) and keeps up to 24 hours on disk while it is away,
  so time away fills in later instead of alerting. On top of node_exporter's own metrics, each host's textfile
  directory carries `drivecheck` (SMART, every host), `zfs_metrics` (pool health, capacity, errors, scrub age and
  I/O on all five ZFS hosts), `root_disk_metrics` (tinynas), `lab-sync`, the apt, nvme and smartmon collectors, BMC
  sensors from ipmitool on ryuji, sojiro and makoto, and the fan controllers' state on mementos and ryuji
  (`fan-control/monitoring/lab-thermal-textfile`). The rack PDU's current comes over read-only SNMP, and blackbox
  probes check the six public sites every 60 s (`docker-compose/blackbox`). mementos has no in-band IPMI reader on
  purpose: a second one next to fan-watchdog can make its read fail and send the R720 to loud iDRAC auto.
- **History.** Since 2026-10-18 futaba's Prometheus also remote-writes every sample to VictoriaMetrics on mementos
  (one container, data on `vmPool/victoriametrics`, 100-year retention), backfilled to the lab's first sample on
  2026-10-06. Grafana has both: Prometheus for the live 90 days, VictoriaMetrics for everything.
- **Dashboards.** "Lab - Overview" (Grafana's home page), "Lab - Network" and "Lab - I/O" each have a host picker
  and default to VictoriaMetrics; "Lab - Thermal" (`fan-control/monitoring/lab-thermal.json`) follows the fans and
  temperatures. Glance has a card per host.
- **Alerts.** Alertmanager emails every alert. Rules: `monitoring/storage-rules.yml` (ZFS pool state and errors,
  pending sectors, wear, NVMe, SAS and temperature margins; promtool tests in `storage-rules.test.yml`),
  `monitoring/lab-sync-rules.yml`, `fan-control/monitoring/lab-thermal-rules.yml`, and site-down and certificate
  expiry from the blackbox probes. Rules fire only on samples that exist (no `absent()`), because akechi's series
  vanish while it is away.
- **Adding a host.** `deploy-monitoring HOST` for a server, `--roaming` for a laptop, `--dry-run` to preview; it sets
  up both the host and futaba's side. Details in `monitoring/README.md`.

`thermal-log` (every host) also keeps a plain JSON-lines temperature record in `/var/log/thermal.jsonl`, 30 days,
independent of Prometheus.

To reuse this elsewhere: any Prometheus with `--web.enable-remote-write-receiver` (for roaming hosts) and a
`remote_write` to VictoriaMetrics will do; the rule files load as they are, and `deploy-monitoring`'s host names and
futaba paths are the parts to change.

## Lab scripts on dataPool

The lab keeps one copy of its scripts: a clone of this repo at `/dataPool/homelab` (since 2026-10-16), the same path
on every host that mounts mementos's `dataPool/labShare` NFS share (NFS 4.2; on mementos itself a symlink to
`/dataPool/labShare/homelab`): makoto, tinypc, futaba, tinynas, morgana, ryuji, yusuke and mementos, plus akechi on
demand (soft mounts that a guard script offers only while mementos answers, at home or over the VPN, so the laptop
never hangs on a share it cannot reach). sojiro does not mount it, on purpose (below).

- **Tools you run by hand run straight from the share.** `/etc/profile.d/lab-scripts.sh` appends `bin/` and
  `private/bin` to PATH, last, so a host's own commands win: `newvm` with its profile names, `autorar`,
  `deploy-monitoring`, `lab-scripts`, `rename-host`. An edit there is live at once. A few sit at fixed paths as
  symlinks into the share (`[links]` in `deploy.list`: newvm on mementos and ryuji, autorar on tinynas, sudo-grant and
  sudo-revoke on makoto).
- **Everything unattended runs from a local copy** (`[copies]`): cron jobs, services and boot scripts are real files
  on each host, so they keep running while mementos is down. `scripts/lab-sync` keeps them in step: every 5 minutes
  on every host but sojiro (`lab-sync.timer`) it compares each copy with the version committed on main in the share,
  never the working tree, so a half-edited file never goes out. When one differs it checks the new version's syntax,
  keeps the old file in `/var/lib/lab-sync/backup` (the last 5 per file), swaps the new one in with a rename and
  restarts the unit the entry names (`restart=UNIT`). Edit, commit, and within 5 minutes every host has it.
- **The fan controllers are `check-only`** (md1200-fan, fan-watchdog, ryuji-fan-guard, tinypc's GPU fan curve):
  compared, never written. A new version goes in with a restart and a live check (see `fan-control/README.md`).
- **Each host fetches from mementos's share; nothing goes through makoto.** A push from mementos would need root SSH
  from mementos into every host, which the lab's SSH policy keeps servers from having.
- **sojiro keeps manual copies.** It is the backup box: if it synced from the share, anything that can write the share
  could change what it runs as root. `lab-scripts install NAME sojiro` puts a committed version there by hand.
- **Visibility.** lab-sync writes `lab_sync.prom` for node_exporter (last run, last success, whether the share was
  readable, files in step, installed, failed, and check-only files that differ); `monitoring/lab-sync-rules.yml`
  alerts when a host has not synced for a day or keeps failing on a file. `lab-scripts status` on makoto checks
  every copy and link against `deploy.list` and main.
- **Boot never waits for the share.** Its fstab lines are `nofail` automounts: boot only sets up the mount point, and
  the first use mounts it (30 s timeout). A `dataPool.mount` drop-in (written by `lab-scripts setup`) keeps it
  retrying, so early requests at boot can never leave it unmounted for good, as happened on ryuji on 2026-10-17.
  tinypc mounts it with `context=system_u:object_r:bin_t:s0`, so Fedora's SELinux lets programs run from it.
- **Not public yet: `private/`.** Its own git repo inside the share copy, ignored by this one and never pushed: the
  hosts' service scripts, the local AI tools, `rename-host`, `sudo-grant` and `sudo-revoke`, migration templates and
  retired scripts, with their own `deploy.list`.

```sh
lab-scripts                        # run on makoto: what is uncommitted, unpushed, or not as deploy.list and main say
lab-scripts sync tinynas           # run lab-sync there now instead of waiting up to 5 minutes
lab-scripts diff drivecheck sojiro # the committed source against a host's copy
lab-scripts install zfs-snapshot sojiro   # put the committed version in place by hand (sojiro's only way)
lab-scripts setup yusuke           # once per new host: the PATH snippet, sudo's secure_path, the mount drop-in
lab-scripts enable-sync yusuke     # once per new host: lab-sync and its timer
lab-scripts push                   # checks the new commits for secrets and vendor names, then pushes via tinynas
```

Edit in `/dataPool/homelab`, commit one version per change that works (only your own files: `git add <paths>`), and
push with `lab-scripts push`: tinynas holds the GitHub credential. To try an uncommitted edit on one host, run it
from the share by its full path; lab-sync only ever installs what is committed. `lab-scripts-pull.timer` on
mementos fast-forwards the share from GitHub every 15 minutes, so a commit pushed from another clone reaches the hosts
too. The every-minute cron jobs run under `flock -n` (zfs_metrics, root_disk_metrics and mon-watchdog on tinynas,
zfs_metrics on ryuji, resume-uptime on futaba). sudo's `secure_path` includes the share only where `lab-scripts
setup` has run since 2026-10-16 (makoto).

The trade-off, accepted on purpose: whatever is committed on the share is what root runs on the synced hosts five
minutes later, and rohit can write the share from any client. While mementos is down a shell on a client can hang
on Tab completion, because PATH searches the share last; in that shell, `export PATH=${PATH%%:/dataPool/homelab/*}`
drops it.

To reuse this elsewhere: any path every host mounts will do. Change `SHARE` at the top of `scripts/lab-scripts`,
`REPO` in `scripts/lab-sync` and the hosts in `deploy.list`. With root squashing, keep the files world-readable,
because root reads the share as nobody; on an SELinux host, mount it with a `context=` label programs may execute.

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
    ├── zfs-retention           # GFS pruning for /etc/zfs-snapshot-targets (mementos, ryuji, sojiro, makoto; sbin)
    ├── zfs-snapshot            # Hourly snapshots of /etc/zfs-snapshot-targets (same hosts; /usr/local/sbin)
    ├── zfs_metrics             # ZFS pool and I/O metrics for Prometheus (all five ZFS hosts)
    └── zfs_metrics.cron        # /etc/cron.d/zfs-metrics: every minute (makoto, sojiro; the others use root's crontab)
```

## VMs

`scripts/newvm` creates a libvirt/KVM guest on whichever lab host it runs on, bridged onto the LAN through `br0`,
with VNC on the next free port from 5900. Profiles: `win11`, `2k22`, `2k25` (Secure Boot with Microsoft keys, TPM 2.0,
the virtio-win CD), `ubuntu`, `rocky` (plain UEFI; Rocky 10 needs AVX2, which mementos's Ivy Bridge Xeons lack) and
`iso` (any ISO). It runs from `bin/` on the share (see "Lab scripts on dataPool"), where the symlinks `newwin11`,
`new2k22`, `new2k25`, `newubuntu` and `newrocky` pick the profile. It replaced tinynas's `~/newwin11`, `~/new2k22` and
`~/new2k25` on 2026-10-06.

Where things go (v3, 2026-10-18):

- ISOs: one folder for the whole lab, `img` on the shared `vmPool/labShare` (NFS from mementos): `/vmPool/img` on the
  clients, `/vmPool/labShare/img` on mementos itself. The ISO file names are in the profile table near the top.
- Disks on a host with its own VM pool: a ZFS dataset per VM, `<pool>/kvm/<name>` (recordsize 64K = the qcow2 cluster
  size): `vmPool/kvm` on mementos (12 mirrored pairs of 1.2 TB 10K SAS), `computePool/kvm` on ryuji.
- Disks on any other host: a folder on the share named after the host that runs the VM, `/vmPool/<host>/<name>/`. The
  export is `root_squash`, so newvm makes the folder and the qcow2 as you (`qemu-img create`) and sets the disk to 0666
  so libvirt's qemu user can open it; libvirt's chown to that user fails on the squashed mount and it carries on.
  These disks run at NFS speed over 1 GbE and depend on mementos being up (the mounts are `hard`). vmPool/labShare is
  not backed up.

Either way the folder holds `<name>.qcow2` and a copy of the libvirt XML; UEFI variables and TPM state stay in the
host's `/var/lib/libvirt`. `NEWVM_BASE=<pool>/kvm` picks another local dataset, `NEWVM_SHARE=<path>` another share.
newvm stops early if the share is not mounted, `img` is missing or there is no `br0`.

Hosts that can build VMs (libvirt, qemu, virt-install, OVMF, swtpm and a `br0` that carries the LAN NIC's own MAC with
`dhcp-identifier: mac`, so the UniFi DHCP reservations still match): mementos (eno1), ryuji (enp129s0f1, 2x E5-2696 v4,
88 threads), tinynas (eno1), futaba (eno1), makoto (enp10s0), morgana (enp0s31f6), yusuke (the USB NIC
enx0050b6240c00), all Ubuntu 24.04 with netplan/networkd, and tinypc (Fedora 44: a NetworkManager bridge `br0` with
port `br0-port-enp5s0` and `ethernet.cloned-mac-address` set to enp5s0's MAC; SELinux `virt_use_nfs` on). Left out on
purpose: sojiro (the backup box has no NFS and stays apart from the rest of the lab) and akechi (a laptop on Wi-Fi,
which cannot be bridged, that sleeps and mounts the shares only on demand). VMs that need many cores or AVX2 (Rocky 10,
Kubernetes nodes) belong on ryuji; small always-on VMs such as 2k25-test stay on mementos, next to their storage.

To reuse it elsewhere: install libvirt-daemon-system, qemu-system-x86, qemu-utils, virtinst, ovmf, swtpm and
swtpm-tools (Fedora: libvirt-daemon-kvm, qemu-kvm, qemu-img, virt-install, edk2-ovmf, swtpm-tools), put the LAN NIC in a
`br0` bridge, and point `NEWVM_SHARE` at any shared folder with an `img` folder of ISOs (or `NEWVM_BASE` at a local
`<pool>/kvm` dataset).

## Not in the repo

Nextcloud AIO, cloudflared, Jellyfin, the game servers, the Home Assistant VM, the rest of futaba's monitoring stack
(the Prometheus, Alertmanager and Grafana compose and configs, and the script that generates the Overview, Network
and I/O dashboards; the repo holds the alert rules, the thermal dashboard and the blackbox probe parts),
VictoriaMetrics's compose on mementos, the Glance dashboard config, tinypc's local AI stack (Ollama, Open WebUI,
SearXNG) and everything under `private/`.
