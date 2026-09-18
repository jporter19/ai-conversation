#!/usr/bin/env bash
# Deploy ai-conversation to the Lightsail hub via rsync + remote restart.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${DEPLOY_HOST:-54.175.0.107}"
KEY="${DEPLOY_KEY:-$HOME/.ssh/lightsail-ai-hub.pem}"
USER_NAME="${DEPLOY_USER:-ec2-user}"
REMOTE_DIR="${DEPLOY_REMOTE_DIR:-/opt/ai-conversation}"

if [[ ! -f "$KEY" ]]; then
  echo "SSH key not found: $KEY" >&2
  exit 1
fi

SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new -o IdentitiesOnly=yes)
RSYNC_SSH="ssh -i $KEY -o StrictHostKeyChecking=accept-new -o IdentitiesOnly=yes"

echo "→ Syncing to ${USER_NAME}@${HOST}:${REMOTE_DIR}"
rsync -az --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude 'venv/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude 'app/data/secrets.json' \
  --exclude 'app/data/users.json' \
  --exclude 'app/data/conversations/' \
  --exclude 'app/data/media/' \
  --exclude '.env' \
  --exclude 'deploy/secrets.env' \
  --exclude 'archive/' \
  -e "$RSYNC_SSH" \
  "$ROOT/" "${USER_NAME}@${HOST}:${REMOTE_DIR}/"

echo "→ Remote venv + restart"
"${SSH[@]}" "${USER_NAME}@${HOST}" bash -s <<EOF
set -euo pipefail
cd ${REMOTE_DIR}
PY=python3.12
command -v python3.12 >/dev/null 2>&1 || PY=python3
if [[ ! -d .venv ]]; then
  \$PY -m venv .venv
fi
.venv/bin/pip install -q --upgrade pip
if [[ ! -d /opt/portal-sdk ]]; then
  echo "Missing /opt/portal-sdk. Deploy portal-sdk first." >&2
  exit 1
fi
.venv/bin/pip install -q -r requirements.txt
if sudo systemctl cat ai-conversation >/dev/null 2>&1; then
  ENV_FILE=\$(sudo systemctl show ai-conversation -p EnvironmentFiles --value 2>/dev/null | awk '{print \$1}' | tr -d "'")
  if [[ -n "\$ENV_FILE" && -f "\$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    . <(sudo cat "\$ENV_FILE")
    set +a
  fi
fi
if .venv/bin/python -c "from app.main import app; print('import-ok', app.version)"; then
  true
else
  echo "WARN: import check failed (env may be unreadable); restarting service anyway" >&2
fi
sudo systemctl restart ai-conversation
sudo systemctl --no-pager --full status ai-conversation | head -20
EOF

echo "✓ Deploy complete → https://porterfamily.us/chat/"
echo "Nginx routes live in porter-family-portal (./scripts/apply_nginx.sh)."
