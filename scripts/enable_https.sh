#!/usr/bin/env bash
# Issue Let's Encrypt cert and enable HTTPS for the hub domain.
# Prerequisites: Cloudflare (or other DNS) A record → Elastic IP; ports 80/443 open.
set -euo pipefail

DOMAIN="${DOMAIN:-porterfamily.us}"
EIP="${EIP:-44.208.175.27}"
KEY="${DEPLOY_KEY:-$HOME/.ssh/grok-small-ec2.pem}"
HOST="${DEPLOY_HOST:-$EIP}"

echo "Checking DNS for ${DOMAIN} → ${EIP}"
CF=$(curl -fsS --max-time 10 "https://cloudflare-dns.com/dns-query?name=${DOMAIN}&type=A" \
  -H 'accept: application/dns-json' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(' '.join(a.get('data','') for a in d.get('Answer',[]) if a.get('type')==1))" 2>/dev/null || true)
echo "  Cloudflare DNS answer: ${CF:-<none>}"
if ! echo "$CF" | grep -qw "$EIP"; then
  echo "ERROR: DNS does not yet point ${DOMAIN} to ${EIP}." >&2
  echo "In Cloudflare DNS, add:" >&2
  echo "  Type A | Name @ | IPv4 ${EIP} | Proxy OFF (DNS only / grey cloud)" >&2
  echo "  Type A | Name www | IPv4 ${EIP} | Proxy OFF (optional)" >&2
  echo "Then re-run: DOMAIN=${DOMAIN} $0" >&2
  exit 1
fi

ssh -i "$KEY" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new "ec2-user@${HOST}" \
  "DOMAIN=${DOMAIN} bash -s" <<'REMOTE'
set -euo pipefail
DOMAIN="${DOMAIN}"

sudo tee /etc/nginx/conf.d/ai-conversation.conf >/dev/null <<EOF
upstream ai_conversation_app {
    server 127.0.0.1:8000;
    keepalive 8;
}

server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name ${DOMAIN} www.${DOMAIN};

    client_max_body_size 50m;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        proxy_pass http://ai_conversation_app;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
        chunked_transfer_encoding on;
    }
}
EOF

sudo mkdir -p /var/www/certbot
sudo nginx -t
sudo systemctl reload nginx

# Cert for apex; include www if it resolves
DOMAINS=(-d "$DOMAIN")
if getent hosts "www.$DOMAIN" >/dev/null 2>&1; then
  DOMAINS+=(-d "www.$DOMAIN")
fi

sudo certbot --nginx "${DOMAINS[@]}" \
  --non-interactive --agree-tos --register-unsafely-without-email \
  --redirect

sudo systemctl enable --now certbot-renew.timer || true

if grep -q '^SESSION_HTTPS_ONLY=' /etc/ai-conversation/env 2>/dev/null; then
  sudo sed -i 's/^SESSION_HTTPS_ONLY=.*/SESSION_HTTPS_ONLY=1/' /etc/ai-conversation/env
else
  echo 'SESSION_HTTPS_ONLY=1' | sudo tee -a /etc/ai-conversation/env >/dev/null
fi

# Ensure nginx passes HTTPS scheme to the app for cookies
if ! sudo grep -q 'X-Forwarded-Proto' /etc/nginx/conf.d/ai-conversation.conf; then
  echo "WARN: X-Forwarded-Proto missing in nginx config"
fi

sudo systemctl restart ai-conversation
sudo nginx -t && sudo systemctl reload nginx
sudo certbot certificates
echo "HTTPS enabled for https://${DOMAIN}/login"
REMOTE

echo "Smoke:"
curl -sS --max-time 15 "https://${DOMAIN}/health" || true
echo
curl -sS --max-time 15 -o /dev/null -w "login %{http_code}\n" "https://${DOMAIN}/login" || true
