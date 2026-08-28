# Thor Public Access Model

> Phase 3 — Make the public exposure strategy explicit.
> Date: 2026-07-03 (design baseline)
> Status: **Implemented** — `siri.choukalos.com` (skill-runner chat) and
> `llm.choukalos.com` (LiteLLM public key) are live via Caddy + Cloudflare
> Tunnel; no admin endpoints public. July text kept as historical context.

---

## Principle

Minimize the public attack surface. Every public endpoint has a stated purpose, a defined access control layer, and a reason for existing.

```
Public access = Cloudflare Tunnel → Caddy → auth → backend
```

Two layers of defense:
1. **Cloudflare Tunnel** — no open ports, Cloudflare handles TLS and IP obfuscation
2. **Caddy** — route matching + API key enforcement before the request reaches a backend

---

## Access Tiers

### Tier 0 — LAN Only (Never Public)

These systems must never be exposed beyond the home network.

| System | Port | Reason |
|---|---|---|
| Matrix vLLM | Various | Raw model inference |
| Matrix Ollama | Various | Raw model inference |
| Qdrant | `6333` | Vector database with full read/write |
| Redis | `6379` | In-memory data store |
| MySQL | `3306` | Database |
| Docker API | Various | Container management |
| Raw MCP servers | TBD | Unauthenticated tool access |
| Grafana admin | `3000` (Matrix/Lego) | Monitoring dashboard |
| Victoria Metrics | `8428` | Metrics backend |
| Homebridge admin | `8581` | Smart home admin |

Access method: LAN only via `192.168.4.x` addresses or internal Docker network.

---

### Tier 1 — Remote Private (Authenticated, Not Public)

These systems are LAN-only now but could be exposed remotely with strong auth in the future. Requires manual approval.

| System | Current | Future Path (if approved) |
|---|---|---|
| Open WebUI | LAN `:3000` | Cloudflare Access / VPN / Tailscale |
| Portal (if moved to Thor) | LAN | Cloudflare Access / VPN |
| Grafana admin | LAN (Lego) | Cloudflare Access |
| Plausible admin | LAN only (blocked) | Cloudflare Access (if needed) |
| n8n | LAN (not running) | Cloudflare Access (if re-enabled) |

**Current decision:** No tier-1 systems are exposed. When Chuck wants remote access to any of these, it goes through a manual gate.

---

### Tier 2 — Public Narrow API (API Key Auth)

Narrow public endpoints protected by API keys at the Caddy layer + backend auth.

#### `siri.choukalos.com` — Skill Facade

| Route | Auth | Backend | Purpose |
|---|---|---|---|
| `GET /health` | None | `ai-harness:8090` | Health check |
| `POST /siri/*` | `X-API-Key: $SIRI_API_KEY` | `ai-harness:8090` | Ask, skill launch |
| `GET /media/files/*` | None | `ai-harness:8090` | Artifact retrieval |
| *everything else* | — | `404` | Blocked |

**Rules:**
- Only these three path patterns are proxied. Everything else returns 404.
- `/siri/*` requires a valid `X-API-Key` header matching `$SIRI_API_KEY`.
- `/media/files/*` is public because artifacts may need to be retrieved by iOS Shortcuts without auth headers. This is acceptable because artifact filenames are opaque IDs.
- Does **not** expose: raw LiteLLM, raw MCP servers, admin tools, broad research without skill controls, code tools, raw filesystem.

#### `llm.choukalos.com` — LiteLLM Remote Access

| Route | Auth | Backend | Purpose |
|---|---|---|---|
| `/*` | `X-API-Key: $LITELLM_PUBLIC_API_KEY` | `litellm-proxy:4000` | OpenAI-compatible API |
| *no key* | — | `401` | Rejected |

**Rules:**
- **Every request** requires `X-API-Key` matching `$LITELLM_PUBLIC_API_KEY`. No exception.
- Behind that, LiteLLM enforces per-user model alias allowlists.
- **No additional Cloudflare Access layer** — scoped LiteLLM keys provide sufficient control.
- **No LiteLLM admin routes** — only OpenAI-compatible inference endpoints.
- Prefer LAN endpoint (`192.168.4.54:4000`) when at home.
- Monitor usage. Rate-limit where practical. Rotate keys if leaked.

---

### Tier 3 — Public Apps (App-Level Auth or No Auth)

Deliberately public web applications. Not AI platform tools — they share infrastructure but are independent.

#### Hugo Portal (blog)

| Route | Auth | Backend | Purpose |
|---|---|---|---|
| `choukalos.com` | None | `portal:8080` (Hugo static site + `/files/` drop zone + `/status/`) | Family blog / public face |
| `choukalos.com/media/files/*` | None | `skill-runner:8091` | Same-origin generated artifacts (charts, demos, video) |

Standard public static site. No AI capabilities, no secrets in the serving container. (Ghost removed 2026-08-28 after the Hugo cutover — `blog-todo.md` B7.)

#### Invest Hub

| Route | Auth | Backend | Purpose |
|---|---|---|---|
| `invest.choukalos.com` (UI) | App-level | `invest-hub-client:80` | Investment tracker UI |
| `invest.choukalos.com/api/*` | App-level | `invest-hub-server:4000` | Investment API |
| `api.choukalos.com` | App-level | `invest-hub-server:4000` | Investment API (alt domain) |

Two domains, same app. Client and server are separate containers. App-level auth handles login.

#### Plausible Analytics

| Route | Auth | Backend | Purpose |
|---|---|---|---|
| `plausible.choukalos.com/js/*` | None | `plausible:8000` | Analytics script delivery |
| `plausible.choukalos.com/api/event` | None | `plausible:8000` | Event tracking |
| *everything else* | — | `404` | Admin UI blocked |

Only two narrow paths are proxied. The Plausible admin login and dashboard are **blocked from the internet** (returns 404). Chuck accesses them via LAN.

---

## Current Public Routes (As-Of Audit)

Verified against `caddy/Caddyfile`:

| Host | Paths Proxied | Auth | Backend |
|---|---|---|---|
| `choukalos.com` | All | None | `portal:8080` (`/media/files/*` → `skill-runner:8091`) |
| `www.choukalos.com` | Redirect to `choukalos.com` | — | — |
| `invest.choukalos.com` | `/api/*` + rest | App-level (downstream) | `invest-hub-server:4000` / `invest-hub-client:80` |
| `api.choukalos.com` | All | App-level (downstream) | `invest-hub-server:4000` |
| `siri.choukalos.com` | `/health`, `/siri/*`, `/media/files/*` | `X-API-Key` on `/siri/*` | `ai-harness:8090` |
| `llm.choukalos.com` | All paths | `X-API-Key` (all requests) | `litellm-proxy:4000` |
| `plausible.choukalos.com` | `/js/*`, `/api/event` only | None | `plausible:8000` |

All other host/path combinations return `404`.

---

## Key Strategy

### LiteLLM Keys

| Key | Used By | Model Scope | Auth Layer |
|---|---|---|---|
| `chuck` | CLI, Open WebUI admin, llm.choukalos.com | All aliases | Caddy API key + LiteLLM per-key allowlist |
| `son` | Open WebUI, llm.choukalos.com | Allowed aliases only | Caddy API key + LiteLLM per-key allowlist |
| `openwebui` | Open WebUI backend | Chat + embeddings | Internal (LAN only, no public route) |
| `siri` | Siri skill facade via `$SIRI_API_KEY` | Scoped chat models | Caddy API key (`$SIRI_API_KEY`) |
| `automation` | n8n (when re-enabled) | Scoped per workflow | Internal (LAN only) |
| `experiment` | Testing / development | Any (dev use) | Internal |

Each key has:
- Its own model alias allowlist (defined in Phase 4)
- Optional budget/cost tracking
- Per-key logging for audit
- Revocation path (delete key from LiteLLM config)

### Caddy API Keys

| Env Var | Used By | Rotation Policy |
|---|---|---|
| `$SIRI_API_KEY` | `siri.choukalos.com` `/siri/*` | Rotate annually or if compromised |
| `$LITELLM_PUBLIC_API_KEY` | `llm.choukalos.com` (all paths) | Rotate annually or if compromised |

These are Caddy-level keys — they gate the reverse proxy. Behind them, the backends may enforce their own additional auth (e.g., LiteLLM per-user keys).

---

## Monitoring Expectations

### What to Watch

| Signal | Where | Alert Threshold |
|---|---|---|
| Rate of 401 responses on `llm.choukalos.com` | Caddy logs / LiteLLM logs | Spike = brute force or leaked key |
| Token usage per LiteLLM key | LiteLLM logs | Unexpected spike on `siri` or `automation` |
| Request volume on `siri.choukalos.com` | Caddy logs | Spike = abuse or misconfiguration |
| Latency on public routes | Victoria Metrics → Grafana | Sustained degradation |
| New paths hitting Caddy with unknown hosts | Caddy logs | Potential reconnaissance |

### Logging

- Caddy logs all requests (host, path, status, remote IP via Cloudflare)
- LiteLLM logs all model calls per key
- AI Harness logs skill launches and job status
- All logs flow into Victoria Metrics / Grafana for dashboards

### Rate Limiting

Future work (Phase 4+):
- Add LiteLLM per-key RPM/token limits
- Add Caddy rate limiting on `/siri/*` and `llm.choukalos.com`

---

## Rules for Adding New Public Endpoints

Any new public endpoint requires:

1. **Manual gate** — Chuck approves the Caddy route change
2. **Explicit purpose** — documented what it does and who uses it
3. **Auth layer** — API key, app-level auth, or justified open access
4. **Narrow path** — proxy only what is needed, not the whole backend
5. **Logging** — ensure requests are captured by Caddy + backend logs
6. **Rollback plan** — how to revert the Caddy route

---

## Manual Task

```text
MANUAL TASK FOR CHUCK:
Reason:
Changing public access can expose private services or interrupt existing public apps.
Command:
TBD after Qwen drafts Caddy/Cloudflare changes.
Expected impact:
Could affect the blog portal, Invest Hub, Siri, or LiteLLM access.
Rollback:
Restore previous Caddyfile and Cloudflare Tunnel config.
Validation:
Confirm the blog portal, Invest Hub, Siri, and LiteLLM still work and no admin endpoints are exposed.
```
