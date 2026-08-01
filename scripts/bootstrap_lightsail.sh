#!/usr/bin/env bash
# First-time (or re) bootstrap for Amazon Lightsail Amazon Linux 2023.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export DEPLOY_HOST="${DEPLOY_HOST:-54.175.0.107}"
export DEPLOY_KEY="${DEPLOY_KEY:-$HOME/.ssh/lightsail-ai-hub.pem}"
export DEPLOY_USER="${DEPLOY_USER:-ec2-user}"

exec bash "$ROOT/scripts/bootstrap_ec2.sh"
