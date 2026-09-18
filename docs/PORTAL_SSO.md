# Porter Family Portal SSO

AI Conversation is a **relying party**. It has **no login of its own**.

Whoever is signed into the family portal (`portal_session` cookie) is the
current AI user. This app only verifies that cookie and scopes chat data by
portal `user_id`. It does **not** own passwords, user CRUD, or grants.

| UI | Behavior |
|----|----------|
| Open `/chat/` with portal cookie + grant | Chat as that portal user |
| Open `/chat/` without portal session | Redirect to `/admin/login?next=/chat/` |
| **Exit** | Return to portal home `/` (stay signed into portal) |
| Portal avatar **Sign out** | Portal logout only (on portal home, not AI) |

Cookie crypto is `portal_sdk.session`. Issuer remains portal-admin. Contract: `/home/john/code/portal-sdk/README.md`. This app still owns `/api/v1/auth/me`, hub admin, and `users/{uid}/` data.

## Product rules

| Concern | Owner |
|---------|--------|
| Users, passwords, grants | portal-admin |
| Login UI | `/admin/login` |
| Session cookie issuance | portal-admin |
| Cookie verify | `portal_sdk.session` (this app imports it) |
| Grant enforce, `/api/v1/auth/me`, hub | AI Conversation |
| Local conversations / media / contexts / prefs | AI Conversation (`data/users/{uid}/`) |
| Shared provider keys / catalog | AI Conversation (app grant `admin`) |

## Environment

| Variable | Required | Description |
|----------|----------|-------------|
| `PORTAL_SESSION_SECRET` | yes* | Same secret as portal-admin |
| `PORTAL_LOGIN_URL` | no | Default `/admin/login` |
| `PORTAL_SESSION_COOKIE` | no | Default `portal_session` |
| `PORTAL_COOKIE_DOMAIN` | **yes in prod** | `.porterfamily.us` so apex + `www` share the session |
| `APP_ID` | no | Default `ai-conversation` |
| `APP_HOME_PATH` | no | Default `/chat/` — public shell on family domain |
| `PORTAL_LEGACY_OWNER_USER_ID` | no | Portal `user_id` that inherits pre-SSO flat data |
| `AUTH_DISABLED` | localhost only | Fake local admin (`dev-local`). Ignored on `porterfamily.us`. |

\* Required when `AUTH_DISABLED` is not set. Hosted chrome: `/portal-assets/sdk/portal-app.js`. Do not copy `session.py` / `auth.js`.

## URL layout (production)

| Path | Service |
|------|---------|
| `/` | Family portal (apps home) |
| `/admin/*`, `/api/portal/*` | portal-admin |
| `/chat/` | AI Conversation shell + static (nginx rewrites to AI `/`) |
| `/api/v1/*` | AI Conversation product API (keep `/api/v1/auth/me`) |
| `/login` | nginx 302 → `/admin/login?next=/chat/` |
| `/health` | AI Conversation |

Never treat apex `/` as the AI home. Unauthenticated browser hits redirect to:

```
/admin/login?next=%2Fchat%2F
```

## Cookie contract

- **Name:** `portal_session`
- **Value:** `base64url(json).base64url(hmac_sha256)`
- **Payload:** `uid`, `uname`, `admin`, `grants[{id,role}]`, `mrp`, `iat`, `exp`
- Grant wire key is `id`; AI also accepts `app_id`. Roles: `user` | `admin`.
- `admin: true` = **portal** administrator (portal UI), not automatically a product
  requirement for AI app admin (middleware still allows portal admins into AI as
  app admin if no explicit grant—prefer granting `ai-conversation` explicitly).
- **Domain:** production must set `PORTAL_COOKIE_DOMAIN=.porterfamily.us` on
  **both** portal-admin and AI Conversation so `www` and apex share one session.
- App card `entry_url` should be **relative** (`/chat/`), not a hard-coded host,
  so open-from-portal stays on the same hostname the user already uses.

### Brave (and Chromium) notes

Brave defaults are stricter than Firefox:

| Setting | Effect on this family site |
|---------|----------------------------|
| Shields → **Block cross-site cookies** (default) | Fine if cookie is first-party with `Domain=.porterfamily.us` |
| Shields → **Block all cookies** | Breaks SSO completely — allow cookies for `porterfamily.us` |
| `www` vs apex without cookie Domain | Host-only cookie set on one host is **not** sent to the other → AI asks for portal login again |
| **Adblock lists match `/admin/` in API URLs** | Brave (EasyList-style filters) often **blocks** network requests whose path contains `admin`. The hub API is therefore **`/api/v1/hub/*`**, not `/api/v1/admin/*`. Portal login stays at `/admin/login` (portal-admin). |
| Aggressive fingerprinting / strict site isolation | Rarely breaks `localStorage`/modules; try Shields down for the site if UI scripts fail |

After changing `PORTAL_COOKIE_DOMAIN`, users must **sign out once and sign in again** so the browser stores a cookie with the new Domain attribute.

## Browser storage (same origin as `/admin`)

`/`, `/admin`, and `/chat/` share one `localStorage` on `porterfamily.us`.
Live chat must **never** use a global key.

| Key | Owner |
|-----|--------|
| `ai-hub:{uid}:chat` | In-progress messages as `{ user_id, messages }` |
| `ai-hub:{uid}:ai` / `:model` / `:theme` / `:context` | That user's picks |
| `portal_uid` | Hint written by portal login; cookie `/me` is source of truth |

On **portal login**, the login page deletes the unscoped live-chat key and every
`ai-hub:{otherUid}:chat` entry so a stale `/chat/` client cannot paint the
previous user's message blocks. Logout deletes all live-chat keys.

On load, AI Conversation:

1. Clears `#chat-history` before identity is fetched.
2. Reads portal identity from `/api/v1/auth/me`.
3. Always starts at the welcome screen. The live transcript is **in-memory
   only** for this page — it is not restored from `localStorage`, so a later
   login cannot paint another user's message blocks. Use **Store conversation**
   to save to your account (server, per uid).
4. Deletes leftover live-chat keys (unscoped and other users).
5. Reloads the page if identity changes while the tab is cached (bfcache).

A mismatched `user_id` in a live-chat payload is ignored (empty welcome). Another user's namespaced keys are left in place so they can sign back in.

## Data layout

```
$AI_HUB_DATA_DIR/
  providers.json          # shared catalog (app admin)
  secrets.json            # shared API keys (app admin)
  users/
    {user_id}/            # portal uid (stable)
      profile.json
      preferences.json    # theme, default model, tts voice
      contexts.json
      conversations/
        {conv_id}.json
      media/
        {media_id}.mp3
```

## Roles inside AI Conversation

| Grant for `ai-conversation` | Meaning |
|-----------------------------|---------|
| `user` | Chat, own data, own prefs. No provider-key admin. |
| `admin` | Above + Admin Tools (providers, secrets, shared catalog). |
| (none) | 403 / redirect. No local profile created. |
| Portal `admin: true` | May use AI as app admin if no explicit grant (implied). |

## Access control (middleware)

1. Public: `/health`, static assets (`/css`, `/js` on the app; `/chat/css` in nginx), `/api/v1/auth/*`. `/login` is a FastAPI helper; production nginx 302s it.
2. Valid cookie + grant for `APP_ID` (or portal admin implied).
3. Upsert `profile.json` + ensure dirs (lazy account on first granted visit).
4. `/api/v1/hub/*` requires app role `admin`, except personal open paths:
   - `/api/v1/hub/catalog`
   - `/api/v1/hub/preferences`
   - `/api/v1/hub/tts/*`

## Legacy migration

Pre-SSO flat files:

- `conversations/*.json`
- `media/*`
- `contexts.json`
- `preferences.json`

On first request by the user matching `PORTAL_LEGACY_OWNER_USER_ID`, those files
are **moved** into `users/{user_id}/…` and marker
`users/{user_id}/.legacy_migrated` is written.

**Mapping:** set `PORTAL_LEGACY_OWNER_USER_ID` to the bootstrap portal admin
`user_id`. Record that id in ops notes after cutover.

Manual migrate:

```bash
export PORTAL_LEGACY_OWNER_USER_ID=<uid>
export AI_HUB_DATA_DIR=/var/lib/ai-conversation/data
.venv/bin/python scripts/migrate_legacy_to_user.py
# optional: MIGRATE_FORCE=1 to re-run after removing marker
```

## Smoke tests

1. User A with grant → `/chat/` → conversations list only A’s data. Live draft is not shown to B on the same browser.
2. User B with grant → disjoint list; cannot open A’s conversation id (404).
3. User without grant → 403 on API / redirect on HTML.
4. No cookie → redirect to `PORTAL_LOGIN_URL?next=…` (prefer `/chat/`).
5. Non-admin grant → Admin Tools hidden; `/api/v1/hub/providers` → 403.
6. Catalog still loads for non-admin granted users.

```bash
.venv/bin/python -m pytest tests/test_portal_sso.py -q
```

## What this app must not do

- Local multi-user password database as source of truth
- Shared single hub account for the whole family
- Global conversation list without `user_id`
- Password login form for portal credentials
- AWS billing UI or portal user CRUD
- Assuming nginx maps AI to apex `/`
