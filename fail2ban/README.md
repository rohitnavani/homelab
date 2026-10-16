# fail2ban jails

| File | Goes to | Policy |
|---|---|---|
| `futaba.jail.local` | `/etc/fail2ban/jail.local` on futaba | 3 failed SSH logins within 10 minutes means a 30-minute ban; aggressive mode; the lab LAN and the VPN pool are never banned |
| `tinynas.jail.local` | `/etc/fail2ban/jail.local` on tinynas | 3 failures within 10 minutes means a 1-hour ban |

futaba (Lenovo 10HY002AUS mini PC, Core i5-6500T, Ubuntu Server 24.04) takes SSH from the internet as fallback access,
public-key only. Its jail went in on 2026-10-15, after one bot made about 795,000 failed attempts in a day and kept
tripping sshd's MaxStartups throttle, which also refused legitimate logins. tinynas (ASUS PRIME B650M-A AX II, Ryzen 5
9600X, Ubuntu Server 24.04) takes SSH from the LAN only.

Ubuntu 24.04 gotcha: sshd runs as `ssh.service`, but the stock `sshd` jail reads the journal for `sshd.service`, so it
sees nothing. Both files set `journalmatch = _SYSTEMD_UNIT=ssh.service + _COMM=sshd`. Check the "Journal matches"
line of `fail2ban-client status sshd`, and test the filter against a saved log with
`fail2ban-regex <file> 'sshd[mode=aggressive]'`.

Using this elsewhere: put your own networks in `ignoreip` (never ban an address you administer from), and check which
unit your sshd logs under with `journalctl -o verbose`.
