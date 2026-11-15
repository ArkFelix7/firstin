# Deploying FirstIn

```
Browser ──HTTPS──> Vercel: Next.js dashboard (web/)          proxy.ts: SITE_ACCESS_CODE
   │
   └──HTTPS──> VPS (Ubuntu 24.04): Caddy :443 ──> uvicorn :8100 (agent/, 1 worker)   FIRSTIN_ACCESS_CODE
                                                    ⇅ 127.0.0.1:8010 Photon bridge (photon/) ⇄ iMessage
```

Nothing here changes local behaviour: with none of the variables below set, `make stage` +
`pnpm dev` work exactly as before (no auth, localhost CORS, macOS `say`).

## Access code

One shared code protects the hosted site.

| Where | How the code is sent |
|---|---|
| API `fetch` | `Authorization: Bearer <code>` (Basic with any username and password = code also works, e.g. `curl -u x:<code>`) |
| EventSource, `<audio>`, `<img>`, static files | `?key=<code>`, accepted only on `/stream/*`, `/static/*`, `/incab/active` |
| Dashboard pages | cookie `firstin_key`, set by the `/signin` screen, or once via `?key=<code>` on any page URL (handy for the in-cab kiosk: `https://<app>/incab?key=<code>`) |

`GET /health` and CORS preflights stay open. When `SITE_ACCESS_CODE` and `FIRSTIN_ACCESS_CODE` are
the same, the officer types the code once: the page cookie is reused for the API. If they differ,
a second "Access code" screen appears for the API. Comparisons are constant-time.

## 1. Provision the VPS (once)

```bash
scp -i ~/.ssh/firstin_deploy deploy/setup_server.sh root@2.25.149.18:/root/
ssh -i ~/.ssh/firstin_deploy root@2.25.149.18 'FIRSTIN_DOMAIN=2.25.149.18.sslip.io bash /root/setup_server.sh'
```

This installs uv, Python 3.12, Node 24, pnpm, ffmpeg, espeak-ng, piper (optional, `INSTALL_PIPER=0` to skip)
and Caddy; creates the `firstin` user, `/opt/firstin` and `/etc/firstin/firstin.env` (with a generated
access code); opens ufw 22/80/443. It is safe to re-run. `FIRSTIN_DOMAIN` defaults to
`<public-ip>.sslip.io`; use your own domain by pointing an A record at the VPS and passing it instead.

Then edit the server settings (template: `deploy/firstin.env.example`):

```bash
ssh -i ~/.ssh/firstin_deploy root@2.25.149.18 'nano /etc/firstin/firstin.env'
```

Set `FIRSTIN_CORS_ORIGINS` and `DASHBOARD_URL` to the Vercel URL once you know it (step 3).

## 2. Push code and data, start services

```bash
deploy/push.sh 2.25.149.18           # PUSH_OUT=1 deploy/push.sh ... also sends agent/out (the active in-cab plan)
```

It rsyncs `agent/` (including the git-ignored `agent/cache/**` and `agent/data/**` with the CoStar kit),
`photon/`, `deploy/`, `Makefile`, `.env` and `photon/.env` over SSH with `~/.ssh/firstin_deploy`. It skips
`web/`, `demo/`, `hardware/`, `node_modules`, `.venv`, `.next` and `agent/out`, and never deletes on
the server. On the server it rewrites laptop paths in cached JSON to `/opt/firstin`, runs `make venv`
the first time (afterwards `uv pip install -r agent/requirements.txt`), `npm ci` in `photon/`, installs
the systemd units and Caddyfile, restarts `firstin-api`, `firstin-photon` and reloads Caddy, then
prints `/health`. Re-run it for every update. The live agent runs (no `FIRSTIN_OFFLINE`).

Restarting `firstin-api` drops runs in progress (they live in memory, one worker by design).

Check:

```bash
CODE=...   # from /etc/firstin/firstin.env
curl https://2.25.149.18.sslip.io/health                                    # 200, open
curl -o /dev/null -w '%{http_code}\n' https://2.25.149.18.sslip.io/buildings  # 401
curl -H "Authorization: Bearer $CODE" 'https://2.25.149.18.sslip.io/buildings/search?limit=1'
ssh -i ~/.ssh/firstin_deploy root@2.25.149.18 'journalctl -u firstin-api -u firstin-photon -n 50 --no-pager'
```

## 3. Dashboard on Vercel

New project, root directory `web/` (`web/vercel.json`: framework nextjs, `pnpm install --frozen-lockfile`,
`pnpm build`; `prebuild` copies the MapLibre worker into `public/`). Environment variables
(Production, and Preview if you use it):

| Variable | Value | Notes |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `https://2.25.149.18.sslip.io` | Build-time. A non-local URL turns on the API access-code screen. Redeploy after changing. |
| `SITE_ACCESS_CODE` | same as `FIRSTIN_ACCESS_CODE` | Runtime (proxy.ts). Locks every page behind `/signin`. Unset = pages open. |

Then put the Vercel URL into `FIRSTIN_CORS_ORIGINS` and `DASHBOARD_URL` in `/etc/firstin/firstin.env`
and `systemctl restart firstin-api firstin-photon`.

## Environment variables

Server, `/etc/firstin/firstin.env` (systemd `EnvironmentFile`; overrides `.env`):

| Variable | Used by | Purpose |
|---|---|---|
| `FIRSTIN_ACCESS_CODE` | backend | Shared access code. Unset/empty = no auth. |
| `FIRSTIN_PUBLIC_API_URL` | backend | Origin used for absolute `audio_url`/`pdf_url`/`html_url` (else the request host). |
| `FIRSTIN_CORS_ORIGINS` | backend | Comma list of extra allowed origins (the Vercel URL). Localhost/LAN stay allowed. |
| `PHOTON_URL` | backend | Bridge URL, `http://127.0.0.1:8010` (`off` disables texts). |
| `PIPER_MODEL` | backend | Piper voice `.onnx` for the brief. TTS chain: `say` → `piper` → `espeak-ng` → `pico2wave`, ffmpeg to mp3; the engine used is logged as `[tts] engine=...`. |
| `FIRSTIN_ESPEAK_VOICE` | backend | Optional espeak-ng voice (default `en-us`). |
| `BACKEND_ACCESS_CODE` | photon | Same as `FIRSTIN_ACCESS_CODE`; sent as `Authorization: Bearer`. |
| `BACKEND_URL` | photon | `http://127.0.0.1:8100` |
| `PHOTON_HOST` | photon | `127.0.0.1` keeps the bridge private (unset = all interfaces, as locally). |
| `DASHBOARD_URL` | photon | Vercel URL; approval texts link to `<DASHBOARD_URL>/plan/<run_id>`. |

API keys stay where they are locally: `/opt/firstin/.env` (Anthropic, Vexcel, Matterport, `COSTAR_DATA_DIR`)
and `/opt/firstin/photon/.env` (Photon project/key, `OFFICER_PHONE`, `PHOTON_MODE=v2`). Both are pushed by `push.sh`.

Vercel: `NEXT_PUBLIC_API_URL`, `SITE_ACCESS_CODE` (above).

## Files

| File | Installed to |
|---|---|
| `deploy/Caddyfile` | `/etc/caddy/Caddyfile` (domain from `FIRSTIN_DOMAIN` in `/etc/systemd/system/caddy.service.d/firstin.conf`; SSE uncompressed, `flush_interval -1`) |
| `deploy/firstin-api.service` | `/etc/systemd/system/` (uvicorn `agent.main:app`, 127.0.0.1:8100, 1 worker, no reload) |
| `deploy/firstin-photon.service` | `/etc/systemd/system/` (`tsx src/index.ts`) |
| `deploy/firstin.env.example` | template for `/etc/firstin/firstin.env` |

## Caveats

- The access code appears in URLs (`?key=`) for streams and media, so it can show up in Caddy's access log and browser history. It is a shared demo password, not per-user auth.
- The page cookie is readable by JavaScript (so the dashboard can reuse it for the API).
- Matterport's SDK key may be restricted to localhost (CONTRACTS.md); the 3D viewer can fail on the Vercel domain. Panoramas and everything else are served by the API.
- `web/public/mock/` is git-ignored; replay (mock) mode only matters when the API is unreachable.
