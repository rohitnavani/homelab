# AdGuard Home fallback resolver (tinynas)

A second DNS resolver for the lab, so names keep resolving while futaba (the primary AdGuard Home) is down. Added
2026-10-15.

Runs on **tinynas** (ASUS PRIME B650M-A AX II, Ryzen 5 9600X, 64 GB DDR5, Ubuntu Server 24.04) with host networking,
so it answers DNS on port 53 and serves its admin page on port 81, the same ports as futaba's.

- `adguardhome`: AdGuard Home v0.107.79 pinned by digest, the same build as futaba's. Its config and data live in
  `/var/lib/adguardhome` on tinynas's root disk, not in a replicated dataset, because the config is rebuilt from futaba.
- `adguardhome-sync` (v0.9.4, pinned): copies futaba's settings, filters, rewrites and client rules to tinynas once at
  start and then every 10 minutes. DHCP and TLS settings are not synced. Make every AdGuard change on futaba.
- The UDW's DHCP hands out both resolvers, futaba first, so clients fall back on their own.

Setting it up again:

1. Copy futaba's `AdGuardHome.yaml` to `/var/lib/adguardhome/conf/` (root, 0600).
2. Give the sync tool its own login: make a bcrypt hash with `htpasswd -niB -C 10 adguard-sync` (password on stdin)
   and add it under `users:` in both AdGuards' `AdGuardHome.yaml`. futaba's AdGuard reads it only on restart.
3. Put the login in `/etc/lab-secrets/adguardhome-sync.env` (root:docker, 0640): `ORIGIN_URL`, `ORIGIN_USERNAME`,
   `ORIGIN_PASSWORD`, `REPLICA1_URL`, `REPLICA1_USERNAME`, `REPLICA1_PASSWORD`, plus `CRON=*/10 * * * *`,
   `RUN_ON_START=true`, `API_PORT=0`, `FEATURES_DHCP_SERVER_CONFIG=false` and `FEATURES_DHCP_STATIC_LEASES=false`.
4. Start `adguardhome` and check that it answers, then start `adguardhome-sync`. AdGuard blocks an address for 15
   minutes after 5 failed logins, so start the sync tool only once both AdGuards know its user.

Using this elsewhere: change the two URLs in the env file, and list both resolvers in your DHCP server.
