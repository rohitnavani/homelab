# Immich (photos)

Self-hosted photo and video library replacing Google Photos, since 2026-11-17. Immich v3.4.1, from the release's
own `docker-compose.yml`, split across two hosts.

| Piece | Host | Where it lives | File here |
|---|---|---|---|
| Server, Postgres (VectorChord), Valkey | **mementos** (Dell R720xd, 2x Xeon E5-2697 v2, 256 GB, Ubuntu 24.04) | `/vmPool/docker-compose/immich` (dataset `vmPool/docker-compose/immich`); listens on `:2283` | `docker-compose.yml`, `env.example` (copy to `.env`, mode 0640) |
| Library (originals, thumbnails, encoded video, Immich's own DB dumps) | mementos | `/dataPool/immich/library` = `vmPool/data/immich/library` (12 two-way mirrors of 10K SAS) | |
| Postgres data | mementos | `/dataPool/immich/postgres` = `vmPool/data/immich/postgres`, recordsize 16K | |
| Machine learning (faces, smart search, OCR) | **tinynas** (Ryzen 5 9600X, 64 GB DDR5, Ubuntu 24.04) | `/pool/docker-compose/immich-ml`; `:3003`, capped at 6 CPUs | `docker-compose.ml.yml` (its `.env` holds only `IMMICH_VERSION` and `TZ`) |
| Public front | tinynas nginx, 443 | `/etc/nginx/sites-available/immich.rohitnavani.com.conf`, certbot (nginx authenticator) | `nginx/immich.rohitnavani.com.conf` |

- **No Cloudflare tunnel.** The tunnel caps a request at 100 MB, and the Immich app uploads each file in one request,
  so phone videos would fail. `immich` is a DNS-only CNAME to `direct-ip.rohitnavani.com` (kept current by
  cloudflare-ddns), the UDW forwards 80/443 to tinynas, and an AdGuard rewrite sends LAN clients straight to
  10.0.0.5. The first-run admin sign-up is allowed from the LAN only.
- **Machine learning on tinynas** because mementos's Ivy Bridge Xeons lack AVX2 and heavy jobs there spin up the rack
  fans. The server finds it through `extra_hosts: immich-machine-learning:10.0.0.5`, so Immich's default ML URL needs
  no setting.
- **Backups:** `vmPool/data/immich` is in mementos's `/etc/zfs-snapshot-targets` (hourly, GFS), and both it and the
  compose dataset are pulled by `backup-mementos` (tinynas, 02:00) and `replicate` (sojiro, offsite, 12:00).
- **Upgrades:** set the same `IMMICH_VERSION` in both `.env` files, diff `docker-compose.yml` against the new release's
  file, then `docker compose pull && docker compose up -d` on tinynas first, then mementos.
- **Other setups:** change `UPLOAD_LOCATION`/`DB_DATA_LOCATION`, the `extra_hosts` address (or drop it and run the ML
  service from the release compose on the same host), and the `proxy_pass` address and `allow` subnet in the nginx
  site.
