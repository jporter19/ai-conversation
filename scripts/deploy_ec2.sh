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
.venv/bin/pip install -q -r requirements.txt
# Load service env so import check sees SESSION_SECRET (same as systemd).
set -a
if [[ -f /etc/ai-conversation/env ]]; then
  # shellcheck disable=SC1091
  . /etc/ai-conversation/env
fi
set +a
.venv/bin/python -c "from app.main import app; print('import-ok', app.version)"
sudo systemctl restart ai-conversation
sudo systemctl reload nginx || sudo systemctl restart nginx
sudo systemctl --no-pager --full status ai-conversation | head -20
EOF

echo "✓ Deploy complete → http://${HOST}/"
