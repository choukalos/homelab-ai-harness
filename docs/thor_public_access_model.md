# Thor Public Access Model

> Phase 3 — Make the public exposure strategy explicit.
> Date: 2026-07-03 (design baseline)
> Status: **Implemented + hardened** — `siri.choukalos.com` (skill-runner chat)
> and `llm.choukalos.com` (LiteLLM) are live via Caddy + Cloudflare Tunnel;
> no admin endpoints public. July text kept as historical context.
> **Security plan (2026-09-06 audit):** [`../security_todo.md`](../security_todo.md)
> — Phases 0–2 applied 2026-11-15: Caddy key gate on `llm.choukalos.com`
> (family LiteLLM keys only), per-key MCP scoping (default-deny +
> `family-mcp-full` access group), key hygiene (spend tracking on, orphan key
> blocked, dead `LITELLM_PUBLIC_API_KEY` removed). This doc re-synced
> 2026-11-15 (was stale per finding F10).

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
| ~~Open WebUI~~ | **REMOVED 2026-11-15** (unused; container + data gone) | — |
| Portal (if moved to Thor) | LAN | Cloudflare Access / VPN |
| Grafana admin | LAN (Lego) | Cloudflare Access |
| Plausible admin | LAN only (blocked) | Cloudflare Access (if needed) |
| n8n | LAN (not running) | Cloudflare Access (if re-enabled) |

**Current decision:** No tier-1 systems are exposed. When Chuck wants remote access to any of these, it goes through a manual gate.

> **Remote access note (2026-11-06):** the Tailscale subnet-router plan
> (former `tailscale/` directory) was dropped — remote access to the LAN
> (incl. SSH to thor/matrix and the NASes) now goes through the **router's
> OpenVPN server** instead. No host-side changes on thor; the OpenVPN
> client lands on the LAN itself.

---

### Tier 2 — Public Narrow API (API Key Auth)

Narrow public endpoints protected by API keys at the Caddy layer + backend auth.

#### `siri.choukalos.com` — Skill Facade

| Route | Auth | Backend | Purpose |
|---|---|---|---|
| `GET /health` | None | `skill-runner:8091` | Health check |
| `POST /siri/*` | `X-Api-Key: $LITELLM_KEY_CHUCK` or `$LITELLM_KEY_DYLAN` | `skill-runner:8091` | Ask, skill launch |
| `GET /media/files/*` | None | `mcp_filebridge:8000` (P12-A, 2026-11-26) | Artifact retrieval (policy-gated: allowlisted subdirs only) |
| `GET/POST /media/pipeline/*` | per Tier 3 table below | `mcp_filebridge:8000` (relay → matrix `:8189`) | Signed-URL media retrieval |
| *everything else* | — | `404` | Blocked |

**Rules:**
- Only these path patterns are proxied. Everything else returns 404.
- `/siri/*` requires `X-Api-Key` matching Chuck's or Dylan's LiteLLM key
  (Caddy expression gate, verified 2026-11-15). `$SIRI_API_KEY` is **not** a
  Caddy-layer key — it's an app-level credential used by `cli/run-skill.sh`
  (legacy mode) and `cli/verify_attribution.sh` (T7) when calling
  skill-runner directly.
- `/media/files/*` is public because artifacts may need to be retrieved by iOS Shortcuts without auth headers. **Policy (P12-A, 2026-11-26, supersedes the stale "opaque filenames" rationale):** served by `mcp_filebridge` with a **per-subdir allowlist (default-deny)** — only `generated/`, `images/`, `demos/`, `presentations/` under `/home/chuck/data/media` are publicly served; every other top-level subdir (`siri_outputs`, `research_reports`, `investment_briefs`, `homelab_reports`, `code_reviews`, `public`, …) returns **404** (not 403 — no subdir enumeration). This resolves finding **12.4**: `siri_outputs/*` (human-readable enumerable personal Q&A) is no longer public (D13: siri-only — siri keeps its own access path: skill API artifact endpoint + LAN). `public/` is served only via its canonical path `choukalos.com/files/` (portal).
- Does **not** expose: raw LiteLLM, raw MCP servers, admin tools, broad research without skill controls, code tools, raw filesystem.

#### `llm.choukalos.com` — LiteLLM Remote Access

| Route | Auth | Backend | Purpose |
|---|---|---|---|
| `/*` | `X-Api-Key: $LITELLM_KEY_CHUCK` or `$LITELLM_KEY_DYLAN`, **or** `Authorization: Bearer <either key>` | `litellm-proxy:4000` | OpenAI-compatible API + MCP |
| *other/missing key* | — | `401` (Caddy) | Rejected |

**Rules (key gate applied 2026-11-15, security_todo Phase 1):**
- **Every request** must carry Chuck's or Dylan's LiteLLM key (Caddy
  `@llmNoAuth` expression → 401 before the request reaches LiteLLM). Even if
  LiteLLM auth were misconfigured, the public route only ever carries the two
  family keys.
- Behind that, LiteLLM enforces per-key model scope + MCP access groups
  (both family keys: all models + all 14 MCP servers via the
  `family-mcp-full` access group — security_todo Phase 2).
- **No additional Cloudflare Access layer** — scoped LiteLLM keys provide sufficient control.
- **No LiteLLM admin routes** — only OpenAI-compatible inference + MCP endpoints.
- Prefer LAN endpoint (`192.168.4.54:4000`) when at home.
- Monitor usage. Rate-limit where practical. Rotate keys if leaked (see Key Strategy).

---

### Tier 3 — Public Apps (App-Level Auth or No Auth)

Deliberately public web applications. Not AI platform tools — they share infrastructure but are independent.

#### Hugo Portal (blog)

| Route | Auth | Backend | Purpose |
|---|---|---|---|
| `choukalos.com` | None | `portal:8080` (Hugo static site + `/files/` drop zone + `/status/`) | Family blog / public face |
| `choukalos.com/media/files/*` | None | `skill-runner:8091` | Same-origin generated artifacts (charts, demos, video) |
| `choukalos.com/files/briefs/latest.md` | None | portal static (→ `/home/chuck/data/media/public/briefs/latest.md`) | Weekday morning brief — overwritten each weekday 09:00 CT (single-file retention, `weekday-morning-brief` schedule) |

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

#### Media Pipeline Signed URLs (2026-09-07)

| Route | Auth | Backend | Purpose |
|---|---|---|---|
| `siri.choukalos.com/media/pipeline/dl/<token>` | None (the signed token IS the credential) | `mcp_filebridge:8000` (transparent relay → matrix `192.168.4.55:8189`; P12-A 2026-11-26) | Off-LAN retrieval of media-pipeline results (Range supported, never buffered) |
| `siri.choukalos.com/media/pipeline/upload` | `X-Api-Key` (chuck/dylan LiteLLM key) | `mcp_filebridge:8000` (relay → matrix) | Push a local file to `media_jobs/uploads/` (500MB cap at the relay **and** matrix; X-Api-Key stripped on the upstream leg) |
| *everything else under `/media/pipeline/*`* | — | `404` | Rest of the pipeline API stays LAN-only (incl. `/dl_token` minting) |

**Rules:**
- **P12-A cutover (2026-11-26, SEC-12):** both routes now go through
  `mcp_filebridge` (the homelab's single public file edge) instead of
  matrix `192.168.4.55:8189` directly. Token validation stays on matrix
  (transparent relay — no secret sprawl); the bridge's env carries **no
  secrets** (work-area path + pipeline URL only). **Kill switch:** stopping
  `mcp_filebridge` kills the public file routes (502); matrix is untouched.
  Post-cutover, matrix 8189 is no longer an internet origin — LAN-only
  bind/ufw is a manual follow-up (`docs/thor_manual_tasks.md`). Rollback:
  one-line Caddy revert per route (back to `192.168.4.55:8189`) + graceful
  `caddy reload`.
- Option C of `media_pipeline_gaps.md` Part 2: served under the existing
  `siri.choukalos.com` tunnel hostname — no new Cloudflare DNS record.
- Tokens are minted **LAN-only** by the pipeline's `/dl_token` (TTL 1–168h,
  default 24h) via the `mcp_media.media_pull` tool; the token embeds the
  absolute file path and is signed — a token is a short-lived capability,
  not a filesystem listing.
- The Cloudflare cache rule for `/media/pipeline/dl/*` is **in place**
  (manual dashboard task, done 2026-09-07 — `docs/thor_manual_tasks.md`
  Phase 15). Observed: `cf-cache-status: DYNAMIC` (edge does not cache —
  bypass); downloads are served from origin.
- Off-LAN acceptance (device outside the LAN) is the remaining manual step
  for Chuck.

---

## Current Public Routes (As-Of Audit)

Verified against `caddy/Caddyfile`:

| Host | Paths Proxied | Auth | Backend |
|---|---|---|---|
| `choukalos.com` | All | None | `portal:8080` (`/media/files/*` → `mcp_filebridge:8000`, P12-A) |
| `www.choukalos.com` | Redirect to `choukalos.com` | — | — |
| `invest.choukalos.com` | `/api/*` + rest | App-level (downstream) | `invest-hub-server:4000` / `invest-hub-client:80` |
| `api.choukalos.com` | All | App-level (downstream) | `invest-hub-server:4000` |
| `siri.choukalos.com` | `/health`, `/siri/*`, `/media/files/*`, `/media/pipeline/*` | `X-Api-Key` (chuck/dylan LiteLLM key) on `/siri/*` and `/media/pipeline/upload`; `/media/pipeline/dl/<token>` public (token is the credential) | `skill-runner:8091` (`/siri/*`, `/api/*`, `/health`); `mcp_filebridge:8000` (`/media/files/*` policy-gated, `/media/pipeline/dl|upload` relay → matrix `192.168.4.55:8189`) — P12-A 2026-11-26 |
| `llm.choukalos.com` | All paths | `X-Api-Key` or `Bearer` (chuck/dylan LiteLLM key; Caddy 401s everything else — gate live 2026-11-15) | `litellm-proxy:4000` |
| `plausible.choukalos.com` | `/js/*`, `/api/event` only | None | `plausible:8000` |

All other host/path combinations return `404`.

---

## Key Strategy

### LiteLLM Keys (live inventory, 2026-11-28)

| Key | User | Model Scope | MCP Scope | Used By |
|---|---|---|---|---|
| `chuck` | chuck | all models | all 15 servers (`family-mcp-full` group) | public (llm + siri routes), CLI, pi sessions |
| `dylan` | dylan | all models | all 15 servers (`family-mcp-full` group) | public (llm + siri routes), Dylan's devices |
| `product` / `analyst` / `strategist` / `marketing` | same | work-type model(s) + `matrix-coder` (pipeline) | **none** | kanban agent sessions (Phase 13.5, 2026-11-27) |
| `internal-service` | internal-service | all 6 model aliases | **none** | **the 7 internal LLM consumers** (presenton, data-hub, mcp_knowledge, mcp_mysql, mcp_vision, mcp_kanban service profile, skill-runner) — Phase 8, 2026-11-28 |
| *(no alias, `memory-service`)* | — | `matrix-coder`, `homelab-embedding-v1` only | **none** (default-deny) | skill-runner mem0 embed/extract (`MEMORY_LITELLM_KEY`) |
| master (`sk-cb1678…`) | proxy admin | everything | everything (`admin_view_unscoped` — admin keys without explicit `object_permission` resolve the whole MCP registry) | **admin-only since Phase 8 (2026-11-28)** — litellm-proxy container + `./homelab.sh key ...` ops (was: 7 internal consumers, finding F6) |
| *(no alias, `sk-...sOsg`)* | default_user_id | all models | none | **BLOCKED 2026-11-15** — orphaned dashboard test key (F5); already expired 2026-10-05; delete after observation window |

**MCP scoping (security_todo Phase 2, 2026-11-15):** `allow_all_keys` is off on
all 14 MCP servers (default-deny). The `family-mcp-full` access group
(`07c1acf8-ffb6-4dbc-918d-9c7199f76fa1`) grants both public keys all 14
servers (Chuck's decision: Dylan and Chuck get all MCP tools incl. skill
runner; `mcp_sessions` added to the group 2026-11-21; `mcp_kanban` added
2026-11-21). The memory-service key has no MCP grant. The master key still sees
all servers via the admin path — intentional, it never crosses the public
path (Caddy gate) and, after Phases 4/5, the LAN edge.

**Master-key note (F6) — RESOLVED 2026-11-28 (Phase 8):** the 7 internal
consumers now use the dedicated `internal-service` key
(`LITELLM_KEY_INTERNAL` in `.env`); the master key is admin-only. The old
`.env` var `LITELLM_API_KEY` (== master) was removed; containers' env var
`LITELLM_API_KEY` is now compose-set from `${LITELLM_KEY_INTERNAL}` (the
litellm-proxy container excepted — its own `LITELLM_API_KEY` is the master
key by design). `key-sync-check` enforces the new semantics.

### App-Level (Non-Caddy) Keys

| Env Var | Used By | Rotation Policy |
|---|---|---|
| `$SIRI_API_KEY` | `cli/run-skill.sh` (legacy mode), `cli/verify_attribution.sh` (T7) — app-level calls to skill-runner, **not** a Caddy gate | Rotate annually or if compromised |

(`$HARNESS_API_KEY` — formerly open-webui → skill-runner harness — was removed
from `.env` 2026-11-15 with the open-webui service; its only consumer was gone.)

### GitHub Tokens

| Env Var | Used By | Rotation |
|---|---|---|
| `$GITHUB_ACCESS_TOKEN` | 3 self-hosted Actions runners (invest-hub, data-hub, report-hub — via `ACCESS_TOKEN`) + `mcp_kanban` deploy stage (via `KANBAN_GITHUB_TOKEN`, **same token** as of 2026-11-21) | **`scripts/rotate-github-tokens.sh`** (added 2026-11-21): mint the replacement PAT in the GitHub UI first (classic, `repo` scope, 120–365 d expiry, note "homelab GITHUB_ACCESS_TOKEN rotated <date>"), then run the script (`--dry-run` first; `--new-token-file` for non-interactive) — it verifies the new token, backs up `.env`, swaps the value(s), recreates the direct consumers (compose-source discovery), waits for healthy, re-verifies via `key-sync-check.sh`. The old PAT must be revoked manually afterwards (GitHub removed the PAT create/revoke API endpoints — `POST /user/tokens` 404, verified 2026-11-21 — so both mint and revoke are UI-only: https://github.com/settings/tokens). |
| `$GITHUB_RUNNER_TOKEN` | **none — REVOKED + removed from `.env` 2026-11-21** (fine-grained PAT, leftover from the original invest-hub runner setup; runners use `$GITHUB_ACCESS_TOKEN`) | Done. |

Runner registrations survive rotation (persistent `/runner/data` volumes +
`DISABLE_AUTOMATIC_DEREGISTRATION` — only the API token changes). Containers
that carry the whole `.env` (caddy, cloudflared, skill-runner, …) hold the
old value until their next recreate; `key-sync-check.sh` tracks them.

### Caddy Gate Keys

| Env Var | Gates | Rotation Policy |
|---|---|---|
| `$LITELLM_KEY_CHUCK` | `llm.choukalos.com` (all paths; X-Api-Key or Bearer) + `siri.choukalos.com` `/siri/*` (X-Api-Key) | Rotate with the LiteLLM key: re-mint in LiteLLM, update `.env`, **reload Caddy** (`docker exec caddy caddy reload --config /etc/caddy/Caddyfile`) — Caddy reads the env at load time, so a stale Caddy env 401s the new key |
| `$LITELLM_KEY_DYLAN` | same as above | same as above |

`$LITELLM_PUBLIC_API_KEY` was **removed 2026-11-15** (security_todo Phase 3,
finding F11) — it was dead: assigned to an unused variable in
`lib/litellm-keys.sh`, passed to the litellm-proxy env but never consumed,
and never used by Caddy. The July-era description of a
`$LITELLM_PUBLIC_API_KEY` Caddy gate in this doc never matched the live
Caddyfile (finding F10).

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
