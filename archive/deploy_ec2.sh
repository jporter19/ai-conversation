#!/usr/bin/env bash
# Deploy ai-conversation to the EC2 host via rsync + remote restart.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${DEPLOY_HOST:-}"
KEY="${DEPLOY_KEY:-$HOME/.ssh/grok-small-ec2.pem}"
USER_NAME="${DEPLOY_USER:-ec2-user}"
REMOTE_DIR="${DEPLOY_REMOTE_DIR:-/opt/ai-conversation}"

if [[ -z "$HOST" ]]; then
  echo "Set DEPLOY_HOST to the Elastic IP or hostname." >&2
  echo "Example: DEPLOY_HOST=54.x.x.x $0" >&2
  exit 1
fi

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
  --exclude 'app/data/preferences.json' \
  --exclude '.env' \
  --exclude 'deploy/secrets.env' \
  -e "$RSYNC_SSH" \
  "$ROOT/" "${USER_NAME}@${HOST}:${REMOTE_DIR}/"

echo "→ Remote venv + restart"
"${SSH[@]}" "${USER_NAME}@${HOST}" bash -s <<EOF
set -euo pipefail
cd ${REMOTE_DIR}
PY=python3.12
command -v python3.12 >/dev/null 2>&1 || PY=python3
\$PY -m venv .venv
.venv/bin/pip install -q --upgrade pip
if [[ ! -d /opt/portal-sdk ]]; then
  echo "Missing /opt/portal-sdk. Deploy portal-sdk first." >&2
  exit 1
fi
.venv/bin/pip install -q -r requirements.txt
# Import smoke test under the same EnvironmentFile systemd uses (via systemctl show).
# Fallback: skip import check and still restart the service.
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
sudo systemctl reload nginx || sudo systemctl restart nginx
sudo systemctl --no-pager --full status ai-conversation | head -20
EOF

echo "✓ Deploy complete → http://${HOST}/"
