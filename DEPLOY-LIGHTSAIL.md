# Deploy AI Conversation Hub on Amazon Lightsail

Cost-efficient production host for the family hub (portal + apps later).

## Live instance

| Item | Value |
|------|--------|
| Instance name | `ai-hub` |
| Bundle | `micro_3_0` — **$7/mo**, 1 GB RAM, 2 vCPU, 40 GB SSD, 2 TB xfer |
| Blueprint | Amazon Linux 2023 |
| Region / AZ | `us-east-1a` |
| Static IP | **`54.175.0.107`** (Lightsail name `ai-hub-ip`) |
| SSH key | `~/.ssh/lightsail-ai-hub.pem` (Lightsail key pair `ai-hub-ls`) |
| SSH user | `ec2-user` |
| Code | `/opt/ai-conversation` |
| Data | `/var/lib/ai-conversation/data` |
| Env | `/etc/ai-conversation/env` |
| App shell (domain) | https://porterfamily.us/chat/ |
| Portal home | https://porterfamily.us/ |
| Portal admin / login | https://porterfamily.us/admin/ |
| Family portal repo | https://github.com/jporter19/porter-family-portal |
| Auth | portal-sdk verifier + this app’s `/api/v1/auth/me` — see [docs/PORTAL_SSO.md](docs/PORTAL_SSO.md). Hub package `/opt/portal-sdk`. |

Compared to the old EC2 `t3.micro` + Elastic IP (~$12/mo), this plan bundles compute + static IPv4 for a fixed **~$7/mo**.

## Architecture

```
Browser → Cloudflare DNS → Lightsail static IP
         → nginx :80/:443 → 127.0.0.1:8000 uvicorn
Data: /var/lib/ai-conversation/data
```

## DNS cutover (required for the domain)

In **Cloudflare** DNS for `porterfamily.us`:

| Type | Name | Content | Proxy |
|------|------|---------|--------|
| A | `@` | `54.175.0.107` | Optional; if **Proxied** (orange), SSL mode **Full (strict)** after cert |
| A | `www` | `54.175.0.107` | Same as apex |

Remove or update the old EC2 Elastic IP (`44.208.175.27`).

Check:

```bash
curl -sS "https://cloudflare-dns.com/dns-query?name=www.porterfamily.us&type=A" \
  -H 'accept: application/dns-json'
```

## HTTPS (after DNS points here)

```bash
# From laptop (repo root)
export DEPLOY_HOST=54.175.0.107
export DEPLOY_KEY=$HOME/.ssh/lightsail-ai-hub.pem
export DOMAIN=www.porterfamily.us   # or porterfamily.us
export EIP=54.175.0.107
./scripts/enable_https.sh
```

If only `www` has an A record, set `DOMAIN=www.porterfamily.us`. Certbot is installed on the instance.

Then set Cloudflare SSL/TLS to **Full (strict)** if using the orange cloud.

## Deploy code updates

```bash
./scripts/deploy_lightsail.sh
# Nginx (chat namespace, no catch-all) lives in porter-family-portal:
#   cd ../porter-family-portal && ./scripts/apply_nginx.sh
```

## Bootstrap (rebuild packages / unit)

```bash
./scripts/bootstrap_lightsail.sh
```

Then re-copy secrets if needed (see migration below).

## Migrate data from old EC2

Already done once during cutover. To repeat:

```bash
EC2_KEY=$HOME/.ssh/grok-small-ec2.pem
LS_KEY=$HOME/.ssh/lightsail-ai-hub.pem
EC2=44.208.175.27
LS=54.175.0.107
TMP=$(mktemp -d)

scp -i "$EC2_KEY" -o IdentitiesOnly=yes -r ec2-user@$EC2:/var/lib/ai-conversation/data "$TMP/data"
ssh -i "$EC2_KEY" -o IdentitiesOnly=yes ec2-user@$EC2 'sudo cat /etc/ai-conversation/env' > "$TMP/env"

rsync -az -e "ssh -i $LS_KEY -o IdentitiesOnly=yes" "$TMP/data/" "ec2-user@$LS:/var/lib/ai-conversation/data/"
scp -i "$LS_KEY" -o IdentitiesOnly=yes "$TMP/env" "ec2-user@$LS:/tmp/env"
ssh -i "$LS_KEY" -o IdentitiesOnly=yes ec2-user@$LS \
  'sudo install -m 600 -o root -g ec2-user /tmp/env /etc/ai-conversation/env && rm /tmp/env && sudo systemctl restart ai-conversation'
rm -rf "$TMP"
```

## Retire old EC2 (after DNS + HTTPS verified)

Do **not** delete until you have logged in on the domain and smoke-tested chat.

```bash
# Stop billing for the instance (keeps disk until terminated)
aws ec2 stop-instances --instance-ids i-00b126d39195d971e

# Later: release Elastic IP 44.208.175.27 if unused
# aws ec2 release-address --allocation-id eipalloc-09ce25485736f1c65

# Later: terminate instance when sure
# aws ec2 terminate-instances --instance-ids i-00b126d39195d971e
```

## Firewall (Lightsail networking)

Open on instance `ai-hub`:

- TCP 22 (SSH)
- TCP 80 (HTTP / ACME)
- TCP 443 (HTTPS)

```bash
aws lightsail get-instance-port-states --instance-name ai-hub --region us-east-1
```

## Cost checklist

- Prefer this single Lightsail instance for all web apps (path-based nginx later)
- Do not add ALB, NAT, or a second always-on host without need
- Optional: AWS Budget alarm at $15

## SSH

```bash
ssh -i ~/.ssh/lightsail-ai-hub.pem ec2-user@54.175.0.107
```

## YouTube transcripts (home-PC relay)

YouTube blocks most cloud IPs. Fetch transcripts on your **home PC** and reverse-tunnel to Lightsail.

```
Browser → Lightsail hub → http://127.0.0.1:8791 (on Lightsail)
                              ↑ SSH -R tunnel
                         home PC :8791 transcript_relay.py
                              ↓
                         YouTube (home IP)
```

**1. Shared token** (same on home + Lightsail):

```bash
openssl rand -hex 24
```

**2. On Lightsail** (`/etc/ai-conversation/env`):

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
./scripts/install_relay_desktop.sh
.venv/bin/python scripts/transcript_relay_app.py
```

In the window:

1. Open the **Lightsail** tab (default)
2. Host `54.175.0.107`, key `~/.ssh/lightsail-ai-hub.pem`, user `ec2-user`
3. Paste the **shared token**
4. **Save settings** → **Start both**
5. Status should show online (green tray icon)

The **EC2** tab is available if you still run a second hub; settings are saved per tab.

**CLI alternative:**

```bash
export YOUTUBE_TRANSCRIPT_RELAY_TOKEN='<the-token>'
.venv/bin/python scripts/transcript_relay.py --token "$YOUTUBE_TRANSCRIPT_RELAY_TOKEN"
# other terminal (Lightsail defaults):
./scripts/transcript_relay_tunnel.sh
# or: DEPLOY_TARGET=ec2 ./scripts/transcript_relay_tunnel.sh
```

**4. Test from Lightsail:**

```bash
curl -sS -H "Authorization: Bearer <token>" -H 'Content-Type: application/json' \
  -d '{"url_or_id":"https://www.youtube.com/watch?v=cGsk3fYoag8"}' \
  http://127.0.0.1:8791/v1/transcript | head -c 200
```
