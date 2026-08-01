# Deploy AI Conversation Hub on EC2

Phase 1 hosting: single **t3.micro**, nginx reverse proxy, **in-app login** (shared hub account), durable data on the instance. Friends reach the host over **VPN**; security group allows HTTP only from trusted IPs (not the open internet).

## Architecture

```
Browser (VPN) → :80 nginx → 127.0.0.1:8000 uvicorn → app
Data: /var/lib/ai-conversation/data
Code: /opt/ai-conversation
Env:  /etc/ai-conversation/env
```

## Live instance (Phase 1)

| Item | Value |
|------|--------|
| Instance | `i-00b126d39195d971e` (`small-dev`, t3.micro) |
| Elastic IP | `44.208.175.27` |
| Login URL | http://44.208.175.27/login |
| Shared user | `hub` (password set at deploy time; rotate with `hash_password.py`) |
| Data dir | `/var/lib/ai-conversation/data` |
| Code | `/opt/ai-conversation` |
| HTTP SG | Operator IP only (`96.238.177.130/32` at deploy); add VPN egress later |

## Prerequisites

- Instance running (Amazon Linux 2023)
- SSH key (default `~/.ssh/grok-small-ec2.pem`)
- AWS CLI credentials for SG / Elastic IP changes
- Your public IP (and later VPN egress IPs) for SG allowlist
- Python **3.12** on the instance (`python3.12` package)

## One-time bootstrap

```bash
export DEPLOY_HOST=<elastic-ip-or-public-ip>
export DEPLOY_KEY=~/.ssh/grok-small-ec2.pem

# From repo root
chmod +x scripts/*.sh
./scripts/bootstrap_ec2.sh
```

### Shared hub account

```bash
# On laptop (writes local app/data/users.json if AI_HUB_DATA_DIR unset)
.venv/bin/python scripts/hash_password.py -u hub -p 'YOUR_STRONG_PASSWORD' --write

# Copy only users.json to the server data dir
scp -i "$DEPLOY_KEY" app/data/users.json ec2-user@$DEPLOY_HOST:/var/lib/ai-conversation/data/users.json
ssh -i "$DEPLOY_KEY" ec2-user@$DEPLOY_HOST 'chmod 600 /var/lib/ai-conversation/data/users.json'
```

Or generate on the server:

```bash
ssh -i "$DEPLOY_KEY" ec2-user@$DEPLOY_HOST
cd /opt/ai-conversation
sudo -u ec2-user AI_HUB_DATA_DIR=/var/lib/ai-conversation/data \
  .venv/bin/python scripts/hash_password.py -u hub --write
```

### API keys

Either paste via **Admin Tools** after login, or add to `/etc/ai-conversation/env`:

```bash
sudoedit /etc/ai-conversation/env
# XAI_API_KEY=...
sudo systemctl restart ai-conversation
```

## Redeploy code

```bash
export DEPLOY_HOST=<elastic-ip>
./scripts/deploy_ec2.sh
```

Does **not** overwrite `secrets.json`, `users.json`, conversations, or media on the server.

## Security group (VPN / trusted IPs only)

Do **not** open port 80 to `0.0.0.0/0` while using plain HTTP.

```bash
SG=sg-0de759bc83debcaca   # adjust if needed
MYIP=$(curl -fsS https://checkip.amazonaws.com)

# Allow HTTP from your IP
aws ec2 authorize-security-group-ingress \
  --group-id "$SG" \
  --protocol tcp --port 80 \
  --cidr "${MYIP}/32" \
  --group-rule-description "HTTP hub admin" 2>/dev/null || true

# Later: add VPN egress
# aws ec2 authorize-security-group-ingress --group-id "$SG" \
#   --protocol tcp --port 80 --cidr "VPN.EGRESS.IP/32" \
#   --group-rule-description "HTTP hub VPN"
```

SSH should remain locked to your IP only.

## Elastic IP

Associate an Elastic IP so stop/start does not change the bookmark URL. Unassociated EIPs incur a small charge; EIPs attached to a **stopped** instance can also incur charges — release or reassociate if you stop for a long time.

## Local development

```bash
export AUTH_DISABLED=1   # skip login on laptop
.venv/bin/python go.py
```

With auth enabled locally:

```bash
unset AUTH_DISABLED
export SESSION_SECRET=dev-secret
.venv/bin/python scripts/hash_password.py -u hub -p 'devpass' --write
.venv/bin/python go.py
```

## Ops

| Task | Command |
|------|---------|
| App logs | `sudo journalctl -u ai-conversation -f` |
| Restart app | `sudo systemctl restart ai-conversation` |
| Stop instance (save compute) | `aws ec2 stop-instances --instance-ids i-00b126d39195d971e` |
| Start instance | `aws ec2 start-instances --instance-ids i-00b126d39195d971e` |
| Rotate hub password | re-run `hash_password.py --write` and replace `users.json` |

## Phase 1.5 — HTTPS with Cloudflare + Let's Encrypt

Target domain example: **porterfamily.us** → Elastic IP **44.208.175.27**.

### 1. Cloudflare DNS (required before cert)

In Cloudflare → domain → **DNS** → **Records** → **Add record**:

| Type | Name | Content | Proxy status |
|------|------|---------|--------------|
| A | `@` | `44.208.175.27` | **DNS only** (grey cloud) |
| A | `www` | `44.208.175.27` | **DNS only** (grey cloud) — optional |

Important:
- Proxy must be **off** (grey cloud) while issuing the certificate with Let's Encrypt HTTP-01.
- After HTTPS works, you may turn the orange cloud on only if SSL/TLS mode is **Full (strict)**.
- Confirm nameservers for the domain at your registrar point to Cloudflare.

TTL: Auto is fine. Propagation is often under a few minutes.

### 2. Issue certificate (from your laptop / this repo)

Server already has certbot, nginx, and port **443** open. After DNS resolves:

```bash
export DOMAIN=porterfamily.us
export EIP=44.208.175.27
export DEPLOY_HOST=44.208.175.27
./scripts/enable_https.sh
```

This will:
- Verify DNS points at the EIP
- Obtain a Let's Encrypt cert via `certbot --nginx`
- Redirect HTTP → HTTPS
- Enable `certbot-renew.timer`
- Set `SESSION_HTTPS_ONLY=1` for secure cookies

### 3. Use the site

- https://porterfamily.us/login  
- Shared user: `hub` (rotate password as documented above)

### 4. If certbot fails

- Confirm `dig +short porterfamily.us` returns `44.208.175.27`
- Confirm Cloudflare proxy is grey (DNS only)
- Confirm security group allows **80** and **443** from `0.0.0.0/0`
- Check `sudo journalctl -u nginx -n 50` and certbot output on the instance

## YouTube transcripts on AWS

YouTube blocks most **cloud provider IPs** (including this EC2 instance).  
**Preferred fix:** fetch transcripts on your **home PC** and relay results to EC2 over an SSH reverse tunnel (no public home IP needed, no paid proxy).

### Home-PC relay (recommended)

```
Browser → AWS hub → http://127.0.0.1:8791 (on EC2)
                         ↑ SSH -R tunnel
                    home PC :8791 transcript_relay.py
                         ↓
                    YouTube (home IP)
```

**1. Shared token** (same on home + EC2), e.g.:

```bash
openssl rand -hex 24
```

**2. On EC2** (`/etc/ai-conversation/env`):

```bash
YOUTUBE_TRANSCRIPT_RELAY_URL=http://127.0.0.1:8791
YOUTUBE_TRANSCRIPT_RELAY_TOKEN=<the-token>
```

```bash
sudo systemctl restart ai-conversation
```

**3. On home PC** — tray app (recommended)

```bash
cd /path/to/ai-conversation
.venv/bin/pip install -r requirements-relay-app.txt   # once
./scripts/install_relay_desktop.sh                    # menu icon + launcher
.venv/bin/python scripts/transcript_relay_app.py      # or open from app menu
```

In the window:
1. Confirm **EC2 host**, **SSH key**, **port** `8791`
2. Paste the **shared token** (same as EC2)
3. Click **Save settings**, then **Start both**
4. Status should show relay + tunnel **running** (green tray icon)

Close the window to keep it in the **system tray**. Tray menu: Start / Stop / Quit.

Optional login autostart: `cp ~/.local/share/applications/ai-conversation-relay.desktop ~/.config/autostart/`

**CLI alternative** (two terminals):

```bash
export YOUTUBE_TRANSCRIPT_RELAY_TOKEN='<the-token>'
.venv/bin/python scripts/transcript_relay.py --token "$YOUTUBE_TRANSCRIPT_RELAY_TOKEN"
# other terminal:
export DEPLOY_HOST=44.208.175.27 DEPLOY_KEY=~/.ssh/grok-small-ec2.pem
./scripts/transcript_relay_tunnel.sh
```

**4. Test from EC2:**

```bash
curl -sS -H "Authorization: Bearer <token>" -H 'Content-Type: application/json' \
  -d '{"url_or_id":"https://www.youtube.com/watch?v=cGsk3fYoag8"}' \
  http://127.0.0.1:8791/v1/transcript | head -c 200
```

### Alternative: residential proxy

1. [Webshare](https://www.webshare.io/) **Residential** plan (not free Proxy Server).
2. On EC2 env: `WEBSHARE_PROXY_USERNAME` / `WEBSHARE_PROXY_PASSWORD`
3. Restart `ai-conversation`.

Generic: `YOUTUBE_PROXY_URL=http://user:pass@host:port`

Without relay or proxy, Grok/chat still work; only YouTube **transcript** fails with an IP-block error.

## Smoke checks

```bash
# Unauthenticated API
curl -s -o /dev /dev/null -w "%{http_code}\n" http://$DEPLOY_HOST/api/v1/admin/catalog
# expect 401

# Login page
curl -s -o /dev/null -w "%{http_code}\n" http://$DEPLOY_HOST/login
# expect 200

# Health (public)
curl -s http://$DEPLOY_HOST/health
```

Then open `http://$DEPLOY_HOST/login` in a browser (on VPN / allowed IP), sign in as `hub`, send a chat, play TTS if configured.
