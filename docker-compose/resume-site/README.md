# rohitnavani.com resume site

Static pages served by `nginx:alpine` (pinned by digest) on **futaba** (Lenovo 10HY002AUS mini PC: Core i5-6500T,
32 GB DDR4, 256 GB SATA SSD, Ubuntu Server 24.04) since 2026-10-14. Before that it ran on tinynas.

- The container publishes only on `127.0.0.1:8081`. futaba's host nginx serves `rohitnavani.com` and
  `www.rohitnavani.com` from it with `nginx/rohitnavani.com.conf` (in `/etc/nginx/sites-available/`, linked from
  `sites-enabled/`).
- The Cloudflare Tunnel route for `rohitnavani.com` points at futaba's nginx on port 80. Cloudflare handles TLS, so
  there is no certificate on the box.
- `public/uptime.json` feeds the "TinyNAS Uptime" line on the home page. `scripts/resume-uptime` rewrites it every
  minute from futaba's Prometheus (`/etc/cron.d/resume-uptime`, as rohit), so the line still shows tinynas's uptime
  although the site runs on futaba.

Using this elsewhere: put your pages in `public/`, point `resume-uptime` at your own Prometheus and node_exporter
instance, and route your hostname to the box's nginx.
