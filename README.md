# TinyNAS Homelab Infrastructure

This is the central repository for **TinyNAS**, a self-hosted, version-controlled home lab infrastructure running on Ubuntu and backed by a ZFS storage architecture.

# ZFS Storage Architecture
* **`homePool` (Core Data & Services)**: An **8-drive RAIDZ2** array providing dual-disk parity tolerance.
  * **SLOG (Write Log)**: Accelerated by a dedicated NVMe partition (`nvme1n1p1`) to handle synchronous write logging at low latency.
  * **L2ARC (Read Cache)**: Enhanced by a dedicated NVMe caching partition (`nvme1n1p2`) to boost random read performance.
* **`mcPool` (High-Performance IOPS Pool)**: A dedicated NVMe pool running optimized explicitly for low-latency, high-throughput application workloads (such as local game servers).

This repository serves as the single source of truth for all core container deployments, dashboard configurations, and system-wide automation scripts.

---

## 📂 Repository Structure

```text
/pool
├── .gitignore                  # Global exclusion rules for databases and .env secrets
├── README.md                   # Infrastructure documentation
├── docker-compose/             # Containerized services stack
│   ├── AdGuardHome/            # DNS-layer ad-blocking & security configuration
│   ├── cloudflare-ddns/        # Dynamic DNS syncing for domain management
│   ├── exporters/              # Node-exporter metrics collections
│   ├── homepage/               # System dashboard (custom themes, widgets, and service maps)
│   ├── netdata/                # Real-time infrastructure performance tracking
│   ├── prometheus/             # Time-series metrics storage & custom ZFS alerting rules
│   └── resume-site/            # Nginx deployment for personal web portfolio hosting
└── scripts/                    # Dedicated ZFS Dataset (homePool/scripts) for automation
    ├── adguard                 # AdGuard service management wrapper
    ├── autorar                 # Automated extraction pipeline for finished downloads
    ├── drivecheck              # SMART disk health monitoring and alerting
    ├── nextcloud-update        # Automated maintenance lifecycle for Nextcloud AIO
    ├── retention               # Log rotation and backup pruning engine
    ├── root_disk_metrics       # Host disk tracking utility for Prometheus scraping
    ├── snapshot                # Automated ZFS dataset snapshot manager
    └── zfs_metrics             # Custom exporter feeding ZFS pool states to Prometheus
