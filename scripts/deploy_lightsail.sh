#!/usr/bin/env bash
# Deploy ai-conversation to the Lightsail hub host.
# Defaults match the provisioned instance (override with env vars).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export DEPLOY_HOST="${DEPLOY_HOST:-54.175.0.107}"
export DEPLOY_KEY="${DEPLOY_KEY:-$HOME/.ssh/lightsail-ai-hub.pem}"
export DEPLOY_USER="${DEPLOY_USER:-ec2-user}"
export DEPLOY_REMOTE_DIR="${DEPLOY_REMOTE_DIR:-/opt/ai-conversation}"

exec bash "$ROOT/scripts/deploy_ec2.sh"
