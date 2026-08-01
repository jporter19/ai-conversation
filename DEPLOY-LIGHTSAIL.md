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
| App URL (by IP) | http://54.175.0.107/login |
| Domain (after DNS) | https://www.porterfamily.us |

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
# equivalent:
# DEPLOY_HOST=54.175.0.107 DEPLOY_KEY=$HOME/.ssh/lightsail-ai-hub.pem ./scripts/deploy_ec2.sh
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
