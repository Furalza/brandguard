# BrandGuard — local runbook (Windows, Docker)

All commands run in PowerShell inside `C:\Users\alper\Downloads\brandguard-v2`.
Console: http://127.0.0.1:8000 (take exports from here, not from the tunnel address).

## Cheat sheet

```powershell
docker compose up --build -d                     # new zip: rebuild the app (tunnel untouched)
docker compose --profile tunnel up --build -d    # same, and make sure the public link is up
docker compose --profile tunnel up -d            # open the public link (new address each time)
docker compose stop cloudflared                  # close the public link (app keeps running)
docker compose ps                                # what is running
docker compose logs --tail 20                    # last log lines of the app
docker compose logs cloudflared | Select-String trycloudflare   # the public address
docker compose --profile tunnel down             # stop everything incl. the tunnel (data is kept)
```

## A. After every new zip (code update)

```powershell
# 1. In Explorer: overwrite src\, web\src and, when the zip carries one,
#    docker-compose.yml. Never touch .env (keys, password) or data\ (database,
#    profiles, reader cache).

# 2. Rebuild the image and replace the running container.
#    The old container stops automatically; the database is kept.
docker compose up --build -d
#    (if the public link is (or should be) up, use this instead:)
docker compose --profile tunnel up --build -d

# 3. Check: STATUS must say "Up", log must end with "Application startup complete".
docker compose ps
docker compose logs --tail 20
```

## B. Share a link with someone outside your network

The tunnel runs as a second container (`cloudflared`) next to the app: no
extra window, it restarts together with Docker, and the console header shows
the current public address as a green chip with a copy button.

```powershell
# One-time: make sure .env has a login line, e.g.
#   BRANDGUARD_BASIC_AUTH=demo:StrongPassword
# (the link is public; the login is what keeps strangers out)

# Open the link (first time also pulls the cloudflared image, ~1 min):
docker compose --profile tunnel up -d

# Both "brandguard" and "cloudflared" must show "Up":
docker compose ps

# The address: open http://127.0.0.1:8000 and click the green chip in the
# header (appears within 30 s; refresh the page if not), or read the log:
docker compose logs cloudflared | Select-String trycloudflare

# Before sending it: open the address on your PHONE with Wi-Fi off. If it
# loads there, it loads anywhere. Send the address and the login separately.

# Close the link (the app keeps running on 127.0.0.1:8000; the chip disappears):
docker compose stop cloudflared

# Open it again: NEW address, copy the chip again.
docker compose --profile tunnel up -d

# Remove the tunnel container entirely (optional, same effect as stop):
docker compose rm -sf cloudflared
```

Why links died before: the tunnel ran in a PowerShell window on a laptop. The
window closed, the PC slept, or cloudflared restarted, and each of those ends
the address. As a container it survives everything except a sleeping PC and a
closed Docker Desktop.

Demo day: Settings > System > Power > Screen and sleep > "Never" while
plugged in, keep Docker Desktop open, copy the chip right before the demo.
If the other person sees a Cloudflare error page (1033/1016), the tunnel
container is not running: `docker compose ps`, then
`docker compose --profile tunnel up -d` and send the new address.

## C. Day-to-day

```powershell
docker compose --profile tunnel down   # stop everything (app + tunnel); data is kept.
                                       # Plain "docker compose down" leaves the tunnel
                                       # container running and complains "network in use".
docker compose up -d                   # start the app again without rebuilding
docker compose logs -f                 # live log; Ctrl+C to leave
```

## D. Test inputs (three fields each)

```
Spotify | spotify.com | com.spotify.music
Getir   | getir.com   | com.getir
tiktok  | tiktok.com  | com.zhiliaoapp.musically
```

In "One brand" mode fill the three boxes; in "Several brands" paste the lines
as they are (the `|` separates name, domain, Play link or package id).

## Notes

- With Docker you never run `npm run build`, `pip install` or `python -m brandguard.api`; the image does all of it.
- Rebuilding the app (A2) does not restart the tunnel container; the address stays the same. `docker compose --profile tunnel down` removes both, and the next start gets a new address.
- Moving to another folder (a fresh clone): copy `.env` and `data\` over, stop the containers in the old folder first (both want port 8000), then start in the new one.
- A scan takes 1-3 minutes and spends Serper credits (and a few cents of model calls); pre-scan the brands you want to show before the demo.
- Exports: "Export JSON" on a scan page, "Export all (ZIP)" on a batch page, from 127.0.0.1:8000.
- Reader cache: `data\t2_cache.sqlite`; delete it to force every listing to be read again.
