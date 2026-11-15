#!/usr/bin/env bash
# Push code + the git-ignored data the server needs, then (re)start the services.
# Run from your laptop, after setup_server.sh has run once on the server:
#
#   deploy/push.sh 2.25.149.18            # user defaults to root
#   deploy/push.sh root@2.25.149.18
#   PUSH_OUT=1 deploy/push.sh <host>      # also push agent/out (local runs + the active in-cab plan)
#
# Sends: agent/ (incl. agent/cache/**, agent/data/** with the CoStar kit), photon/, deploy/, Makefile,
#        .env, photon/.env. Skips: web/ (Vercel), demo/, hardware/, node_modules, .venv, .next, caches.
# Never deletes files on the server (runs, vision cache and plans written there are kept).
set -euo pipefail

host="${1:?usage: deploy/push.sh [user@]host}"
[[ "$host" == *@* ]] || host="root@$host"
KEY="${FIRSTIN_SSH_KEY:-$HOME/.ssh/firstin_deploy}"
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new)
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

[[ -f .env ]] || echo "warning: no .env at repo root (API keys); the agent will run offline" >&2
[[ -f photon/.env ]] || echo "warning: no photon/.env; iMessage approval texts won't send" >&2

excludes=(
  --exclude '.git/' --exclude '.DS_Store' --exclude '__pycache__/' --exclude '*.pyc' --exclude '.pytest_cache/'
  --exclude 'node_modules/' --exclude '.venv/' --exclude '.next/' --exclude '*.tsbuildinfo'
  --exclude 'co-star-creds.md' --exclude 'devpost_*.txt'
)
[[ "${PUSH_OUT:-0}" == "1" ]] || excludes+=(--exclude '/agent/out/')

echo "==> rsync to $host:/opt/firstin"
# (macOS rsync is old: no --chown/--info; ownership is fixed on the server below)
rsync -az -e "${SSH[*]}" "${excludes[@]}" \
  ./agent ./photon ./deploy ./Makefile ./.env ./CONTRACTS.md \
  "$host:/opt/firstin/"
# photon/.env is git-ignored but inside ./photon, so it goes with it.

echo "==> remote: path fix, venv, npm ci, services"
"${SSH[@]}" "$host" LOCAL_ROOT="$ROOT" bash -s <<'REMOTE'
set -euo pipefail
cd /opt/firstin
# Cached Vexcel/vision JSON stores absolute laptop paths (image_path). Point them at /opt/firstin,
# otherwise the Vexcel cache misses and the server re-downloads every tile.
grep -rlF --null "$LOCAL_ROOT/" agent/cache agent/out 2>/dev/null | xargs -0 -r sed -i "s#$LOCAL_ROOT/#/opt/firstin/#g"
chown -R firstin:firstin /opt/firstin
chmod 600 .env photon/.env 2>/dev/null || true
as_app() { runuser -u firstin -- env HOME=/var/lib/firstin PATH=/usr/local/bin:/usr/bin:/bin "$@"; }

# Python env: create once (make venv), then keep requirements in sync.
if [[ ! -x agent/.venv/bin/python ]]; then
  as_app make venv UV=/usr/local/bin/uv
else
  as_app /usr/local/bin/uv pip install --quiet --python agent/.venv/bin/python -r agent/requirements.txt
fi

(cd photon && as_app npm ci --no-audit --no-fund --loglevel=error)

install -m 644 deploy/firstin-api.service deploy/firstin-photon.service /etc/systemd/system/
install -m 644 deploy/Caddyfile /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable firstin-api firstin-photon caddy >/dev/null
systemctl restart firstin-api
systemctl restart firstin-photon
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1 || echo "warning: caddy validate failed" >&2
systemctl reload caddy || systemctl restart caddy

for i in $(seq 1 30); do
  curl -fsS http://127.0.0.1:8100/health >/dev/null 2>&1 && break
  sleep 1
done
echo "api:    $(curl -fsS http://127.0.0.1:8100/health || echo DOWN)"
echo "photon: $(curl -fsS http://127.0.0.1:8010/health || echo 'DOWN (journalctl -u firstin-photon)')"
systemctl --no-pager --lines=0 status firstin-api firstin-photon caddy | grep -E '^\S|Active:' || true
REMOTE

domain="$("${SSH[@]}" "$host" "sed -n 's/^Environment=FIRSTIN_DOMAIN=//p' /etc/systemd/system/caddy.service.d/firstin.conf" || true)"
[[ -n "$domain" ]] && echo "==> public: $(curl -fsS --max-time 20 "https://$domain/health" || echo "https://$domain/health not reachable yet (cert issuance can take a minute)")"
