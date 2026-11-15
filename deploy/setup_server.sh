#!/usr/bin/env bash
# One-time (idempotent) provisioning for a fresh Ubuntu 24.04 VPS. Run as root ON THE SERVER:
#
#   scp -i ~/.ssh/firstin_deploy deploy/setup_server.sh root@<host>:/root/
#   ssh -i ~/.ssh/firstin_deploy root@<host> 'FIRSTIN_DOMAIN=<domain> bash /root/setup_server.sh'
#
# Installs: python3.12 + uv, Node 24 + pnpm, ffmpeg, espeak-ng (+ piper if it installs cleanly), Caddy.
# Creates: user `firstin`, /opt/firstin, /etc/firstin/firstin.env (template), ufw 22/80/443.
# Safe to re-run. Does not touch /opt/firstin contents (push.sh does that).
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }
. /etc/os-release
[[ "${VERSION_ID:-}" == "24.04" ]] || echo "warning: tested on Ubuntu 24.04, this is ${PRETTY_NAME:-unknown}" >&2

APP_DIR=/opt/firstin
ENV_DIR=/etc/firstin
INSTALL_PIPER="${INSTALL_PIPER:-1}"
PIPER_VOICE="${PIPER_VOICE:-en_US-lessac-medium}"
# Default domain: <public-ipv4>.sslip.io (resolves to the VPS, works with Let's Encrypt).
if [[ -z "${FIRSTIN_DOMAIN:-}" ]]; then
  ip4="$(curl -fsS4 --max-time 5 https://api.ipify.org || hostname -I | awk '{print $1}')"
  FIRSTIN_DOMAIN="${ip4}.sslip.io"
fi
echo "==> domain: ${FIRSTIN_DOMAIN}"

export DEBIAN_FRONTEND=noninteractive
echo "==> apt packages"
apt-get update -y
apt-get install -y --no-install-recommends \
  ca-certificates curl gnupg debian-keyring debian-archive-keyring apt-transport-https \
  git make rsync build-essential python3.12 python3.12-venv python3.12-dev \
  ffmpeg espeak-ng ufw

echo "==> uv"
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
fi
uv --version

echo "==> Node 24 + pnpm"
if ! command -v node >/dev/null || [[ "$(node -v | cut -d. -f1)" != "v24" ]]; then
  curl -fsSL https://deb.nodesource.com/setup_24.x | bash -
  apt-get install -y nodejs
fi
command -v pnpm >/dev/null || npm install -g pnpm@10
node -v; pnpm -v

echo "==> Caddy"
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -y
  apt-get install -y caddy
fi
mkdir -p /etc/systemd/system/caddy.service.d /var/log/caddy
chown caddy:caddy /var/log/caddy
cat > /etc/systemd/system/caddy.service.d/firstin.conf <<EOF
[Service]
Environment=FIRSTIN_DOMAIN=${FIRSTIN_DOMAIN}
EOF

if [[ "$INSTALL_PIPER" == "1" ]]; then
  echo "==> piper (optional neural TTS; espeak-ng is the fallback)"
  if ! command -v piper >/dev/null; then
    UV_TOOL_DIR=/opt/piper/tools UV_TOOL_BIN_DIR=/usr/local/bin uv tool install --python 3.12 piper-tts \
      || echo "warning: piper install failed; espeak-ng will be used" >&2
  fi
  if command -v piper >/dev/null && [[ ! -s "/opt/piper/voices/${PIPER_VOICE}.onnx" ]]; then
    mkdir -p /opt/piper/voices
    IFS=_- read -r lang region name quality <<<"$PIPER_VOICE"
    base="https://huggingface.co/rhasspy/piper-voices/resolve/main/${lang}/${lang}_${region}/${name}/${quality}/${PIPER_VOICE}"
    curl -fsSL -o "/opt/piper/voices/${PIPER_VOICE}.onnx" "${base}.onnx" \
      && curl -fsSL -o "/opt/piper/voices/${PIPER_VOICE}.onnx.json" "${base}.onnx.json" \
      || { echo "warning: piper voice download failed; espeak-ng will be used" >&2; rm -f "/opt/piper/voices/${PIPER_VOICE}.onnx"; }
  fi
  [[ -d /opt/piper ]] && chmod -R a+rX /opt/piper
fi

echo "==> user + directories"
id firstin >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/firstin --shell /usr/sbin/nologin firstin
mkdir -p "$APP_DIR" "$ENV_DIR"
chown firstin:firstin "$APP_DIR"
if [[ ! -f "$ENV_DIR/firstin.env" ]]; then
  code="$(openssl rand -base64 18 | tr -dc 'A-Za-z0-9' | head -c 20)"
  cat > "$ENV_DIR/firstin.env" <<EOF
# FirstIn server settings (see deploy/DEPLOY.md). Edit, then: systemctl restart firstin-api firstin-photon
FIRSTIN_ACCESS_CODE=${code}
FIRSTIN_PUBLIC_API_URL=https://${FIRSTIN_DOMAIN}
FIRSTIN_CORS_ORIGINS=https://CHANGE-ME.vercel.app
PHOTON_URL=http://127.0.0.1:8010
PIPER_MODEL=/opt/piper/voices/${PIPER_VOICE}.onnx
BACKEND_ACCESS_CODE=${code}
BACKEND_URL=http://127.0.0.1:8100
PHOTON_HOST=127.0.0.1
PHOTON_PORT=8010
DASHBOARD_URL=https://CHANGE-ME.vercel.app
EOF
  echo "==> wrote $ENV_DIR/firstin.env (access code generated; read it with: cat $ENV_DIR/firstin.env)"
fi
chown root:firstin "$ENV_DIR/firstin.env"
chmod 640 "$ENV_DIR/firstin.env"

echo "==> firewall"
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
ufw status | sed -n 1,10p

systemctl daemon-reload
systemctl enable caddy >/dev/null
echo
echo "Done. Next, from your laptop: deploy/push.sh <host>"
