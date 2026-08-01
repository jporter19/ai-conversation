#!/usr/bin/env bash
# First-time EC2 provision for AI Conversation Hub (Amazon Linux 2023).
# Run from your laptop: DEPLOY_HOST=x.x.x.x ./scripts/bootstrap_ec2.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${DEPLOY_HOST:-}"
KEY="${DEPLOY_KEY:-$HOME/.ssh/grok-small-ec2.pem}"
USER_NAME="${DEPLOY_USER:-ec2-user}"

if [[ -z "$HOST" ]]; then
  echo "Set DEPLOY_HOST" >&2
  exit 1
fi
if [[ ! -f "$KEY" ]]; then
  echo "Missing key $KEY" >&2
  exit 1
fi

SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o IdentitiesOnly=yes "${USER_NAME}@${HOST}")

echo "→ Installing packages on ${HOST}"
"${SSH[@]}" 'bash -s' <<'REMOTE'
set -euo pipefail
sudo dnf -y update
sudo dnf -y install python3.12 python3.12-pip python3.12-devel nginx git rsync gcc || \
  sudo dnf -y install python3 python3-pip python3-devel nginx git rsync gcc
sudo mkdir -p /opt/ai-conversation /var/lib/ai-conversation/data /etc/ai-conversation
sudo chown -R ec2-user:ec2-user /opt/ai-conversation /var/lib/ai-conversation
sudo chmod 750 /etc/ai-conversation
REMOTE

echo "→ Syncing code"
DEPLOY_HOST="$HOST" DEPLOY_KEY="$KEY" bash "$ROOT/scripts/deploy_ec2.sh" || true

# deploy_ec2 may fail if service not installed yet — continue install
rsync -az --delete \
  --exclude '.git/' --exclude '.venv/' --exclude 'venv/' --exclude '__pycache__/' \
  --exclude 'app/data/secrets.json' --exclude 'app/data/users.json' \
  --exclude 'app/data/conversations/' --exclude 'app/data/media/' \
  --exclude 'app/data/preferences.json' --exclude '.env' \
  -e "ssh -i $KEY -o StrictHostKeyChecking=accept-new -o IdentitiesOnly=yes" \
  "$ROOT/" "${USER_NAME}@${HOST}:/opt/ai-conversation/"

echo "→ Install venv, unit, nginx, env"
"${SSH[@]}" 'bash -s' <<'REMOTE'
set -euo pipefail
cd /opt/ai-conversation
# Prefer python3.12 if present
PY=python3.12
command -v python3.12 >/dev/null 2>&1 || PY=python3
$PY -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

# Seed providers if missing on data volume
if [[ ! -f /var/lib/ai-conversation/data/providers.json ]]; then
  cp -a app/data/providers.json /var/lib/ai-conversation/data/ 2>/dev/null || true
fi
mkdir -p /var/lib/ai-conversation/data/{conversations,media}

sudo cp deploy/ai-conversation.service /etc/systemd/system/ai-conversation.service
sudo cp deploy/nginx-ai-conversation.conf /etc/nginx/conf.d/ai-conversation.conf
# Drop default server conflict if present
if [[ -f /etc/nginx/nginx.conf ]]; then
  sudo sed -i 's/default_server//g' /etc/nginx/nginx.conf 2>/dev/null || true
fi
# Remove AL2023 default welcome if it conflicts
sudo rm -f /etc/nginx/conf.d/default.conf 2>/dev/null || true
sudo rm -f /usr/share/nginx/html/index.html 2>/dev/null || true

if [[ ! -f /etc/ai-conversation/env ]]; then
  SESSION_SECRET=$(openssl rand -hex 32)
  sudo tee /etc/ai-conversation/env >/dev/null <<EOF
AI_HUB_DATA_DIR=/var/lib/ai-conversation/data
SESSION_SECRET=${SESSION_SECRET}
EOF
  sudo chmod 600 /etc/ai-conversation/env
  sudo chown root:ec2-user /etc/ai-conversation/env
fi

sudo systemctl daemon-reload
sudo systemctl enable --now ai-conversation
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
sudo systemctl --no-pager --full status ai-conversation | head -25
REMOTE

echo "✓ Bootstrap finished. Create users.json next (hash_password.py --write)."
