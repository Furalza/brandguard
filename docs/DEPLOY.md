# Deploying BrandGuard on a server (optional)

The free route for demos is the tunnel sidecar in `docker-compose.yml`
(`docker compose --profile tunnel up --build -d`, see `docs/RUNBOOK.md` B):
no server, the console shows its own public link. This document is for the
day the demo should not depend on a laptop at all.

A Cloudflare *quick tunnel* depends on your laptop being awake, the terminal
staying open and the URL not changing; it is fine for a five-minute show and
unreliable for anything else. For a demo someone else opens on their own
time, put BrandGuard on a small server. Twenty minutes, about 5 EUR a month.

## 1. Server

Any Linux VPS with 2 GB RAM works: Hetzner CX22, DigitalOcean 2 GB, Contabo,
a Turkish provider. Choose Ubuntu 24.04. Note the public IP, e.g. `203.0.113.10`.

```bash
ssh root@203.0.113.10
apt update && apt install -y unzip ufw
ufw allow 22 && ufw allow 80 && ufw allow 443 && ufw --force enable
curl -fsSL https://get.docker.com | sh
```

## 2. Code

From your own machine, copy the release zip and unpack it:

```bash
scp brandguard-v2.zip root@203.0.113.10:/opt/
ssh root@203.0.113.10 "cd /opt && unzip -o brandguard-v2.zip -d brandguard"
```

(Or `git clone` the repository into `/opt/brandguard`; updates are then `git pull`.)

## 3. Settings

```bash
cd /opt/brandguard
cp .env.example .env
nano .env
```

Set at least:

```
SERPER_API_KEY=...                 # APK-site search
OPENAI_API_KEY=...                 # or ANTHROPIC_API_KEY: the text reader
BRANDGUARD_BASIC_AUTH=demo:choose-a-strong-password
```

The login is what stands between the internet and your scans; pick a real password.

## 4. Start

Without a domain, use sslip.io: the server IP with dashes plus `.sslip.io`
resolves to the server and gets a real certificate.

```bash
export BRANDGUARD_DOMAIN=203-0-113-10.sslip.io       # or brandguard.yourcompany.com (A record -> server IP)
docker compose -f deploy/docker-compose.prod.yml up --build -d
docker compose -f deploy/docker-compose.prod.yml logs -f caddy   # wait for "certificate obtained"
```

Open `https://203-0-113-10.sslip.io`, log in, run a scan. Send the URL and
the login to whoever needs the demo; it works from Italy, Ankara or a phone.

## 5. Updating

```bash
scp brandguard-v2.zip root@203.0.113.10:/opt/
ssh root@203.0.113.10
cd /opt && unzip -o brandguard-v2.zip -d brandguard && cd brandguard
export BRANDGUARD_DOMAIN=203-0-113-10.sslip.io
docker compose -f deploy/docker-compose.prod.yml up --build -d
```

Scans, brands, reviews and the reader cache live in `/opt/brandguard/data`
and survive rebuilds. Back it up with `tar czf brandguard-data.tgz data`.

## 6. Useful

```bash
docker compose -f deploy/docker-compose.prod.yml ps          # both services "running"
docker compose -f deploy/docker-compose.prod.yml logs -f brandguard
docker compose -f deploy/docker-compose.prod.yml down        # stop (data stays)
```

Scheduled re-scans run while the container runs, which on a server is always.

## If you must use the quick tunnel anyway

Keep the laptop awake and the window open, start it with IPv4 and HTTP/2
(`cloudflared tunnel --url http://localhost:8000 --edge-ip-version 4 --protocol http2`),
test the URL from your phone on mobile data before sending it, and send the
login separately. Every restart makes a new URL.
