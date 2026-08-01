#!/usr/bin/env bash
# Open SSH reverse tunnel: EC2 localhost:8791 → home localhost:8791
# Run on your HOME PC while transcript_relay.py is running.
set -euo pipefail

PORT="${RELAY_PORT:-8791}"
HOST="${DEPLOY_HOST:-44.208.175.27}"
KEY="${DEPLOY_KEY:-$HOME/.ssh/grok-small-ec2.pem}"
USER_NAME="${DEPLOY_USER:-ec2-user}"

if [[ ! -f "$KEY" ]]; then
  echo "SSH key not found: $KEY" >&2
  echo "Set DEPLOY_KEY to your EC2 PEM path." >&2
  exit 1
fi

echo "Tunnel: ec2-user@${HOST} 127.0.0.1:${PORT}  ←  home 127.0.0.1:${PORT}"
echo "Keep this running. Ctrl+C to stop."
echo "Tip: install autossh for reconnects: autossh -M 0 -N -o ServerAliveInterval=30 ..."

exec ssh -i "$KEY" \
  -o StrictHostKeyChecking=accept-new \
  -o IdentitiesOnly=yes \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -N \
  -R "127.0.0.1:${PORT}:127.0.0.1:${PORT}" \
  "${USER_NAME}@${HOST}"
