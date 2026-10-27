# Blackbox probes of the public sites

Checks every public lab site the way a visitor reaches it, and emails when one stops answering or its TLS
certificate is about to expire. Added 2026-10-14; it replaced Uptime Kuma, which was retired on 2026-10-15.

Runs on **futaba** (Lenovo 10HY002AUS mini PC: Core i5-6500T, 32 GB DDR4, 256 GB SATA SSD, Ubuntu Server 24.04) as the
`blackbox-exporter` service (prom/blackbox-exporter 0.29.0, pinned by digest) of the lab monitoring stack in
`/home/rohit/monitoring`, next to Prometheus, Alertmanager and Grafana.

| File | Goes to | What it does |
|---|---|---|
| `compose-service.yml` | the `services:` list of the monitoring `docker-compose.yml` | The exporter container, with `./blackbox` mounted read-only |
| `config.yml` | `/home/rohit/monitoring/blackbox/config.yml` | Modules `http_2xx`, `http_2xx_or_401` for a site behind basic auth (homelab), and `http_money_healthy`, which also needs `"healthy":true` in money-mcp's /healthz |
| `prometheus-job.yml` | the `scrape_configs:` list of `prometheus.yml` | Job `blackbox`: one probe per site every 60 s; each target's `module` label picks its module. Job `money_health`: money-mcp's /healthz with `http_money_healthy` every 5 min |
| `blackbox.yml` | `/home/rohit/monitoring/prometheus/rules/` | `SiteDown` (a probe failing for 5 min, critical), `CertExpiringSoon` (under 14 days left, warning) and `MoneyMcpUnhealthy` (money-mcp answers but reports unhealthy for 1 h, warning) |

The probes go out through the internet and Cloudflare like a visitor's. Jellyfin is the exception: its address is
direct, so its probe loops back inside the router. When every tunnel site fails at once and Jellyfin stays up, the
internet connection or Cloudflare dropped, not the sites (seen on 2026-10-14 from 22:02 to 22:07).

Applying a change: start the exporter with `docker compose up -d blackbox-exporter` so nothing else is recreated.
`prometheus.yml` is bind-mounted into its container as a single file, so change it in place (for example
`cat new > prometheus.yml`), not with tools that replace the file. Then run `promtool check config` inside the
Prometheus container and reload with `curl -X POST http://127.0.0.1:9090/-/reload` (the stack runs with
`--web.enable-lifecycle`).

Using this elsewhere: put your own URLs in `prometheus-job.yml`, and change `blackbox-exporter:9115` if the exporter
runs under another name. The alerts need an Alertmanager with a working receiver.
