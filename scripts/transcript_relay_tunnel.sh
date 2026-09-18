#!/usr/bin/env bash
# Open SSH reverse tunnel: cloud hub localhost:PORT → home localhost:PORT
# Run on your HOME PC while transcript_relay.py is running.
#
# Defaults target Lightsail (see DEPLOY-LIGHTSAIL.md). For EC2:
#   DEPLOY_TARGET=ec2 ./scripts/transcript_relay_tunnel.sh
# Or set DEPLOY_HOST / DEPLOY_KEY / DEPLOY_USER explicitly.
set -euo pipefail

PORT="${RELAY_PORT:-8791}"
TARGET="${DEPLOY_TARGET:-lightsail}"

case "${TARGET}" in
  lightsail|ls)
    DEFAULT_HOST="54.175.0.107"
    DEFAULT_KEY="${HOME}/.ssh/lightsail-ai-hub.pem"
    DEFAULT_USER="ec2-user"
    TARGET_LABEL="Lightsail"
    ;;
  ec2)
    DEFAULT_HOST="44.208.175.27"
    DEFAULT_KEY="${HOME}/.ssh/grok-small-ec2.pem"
    DEFAULT_USER="ec2-user"
    TARGET_LABEL="EC2"
    ;;
  *)
    echo "Unknown DEPLOY_TARGET=${TARGET} (use lightsail or ec2)" >&2
    exit 1
    ;;
esac

HOST="${DEPLOY_HOST:-$DEFAULT_HOST}"
KEY="${DEPLOY_KEY:-$DEFAULT_KEY}"
USER_NAME="${DEPLOY_USER:-$DEFAULT_USER}"

if [[ ! -f "$KEY" ]]; then
  echo "SSH key not found: $KEY" >&2
  echo "Set DEPLOY_KEY to your ${TARGET_LABEL} PEM path." >&2
  exit 1
fi

echo "Target: ${TARGET_LABEL}"
echo "Tunnel: ${USER_NAME}@${HOST} 127.0.0.1:${PORT}  ←  home 127.0.0.1:${PORT}"
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
