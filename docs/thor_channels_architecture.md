# Thor Channel Architecture

> Phase 2 — Document all user-facing channels. None of them owns the platform.
> Date: 2026-07-03 (design baseline)
> Status: **Mostly current** — Siri via `siri.choukalos.com` (Caddy) and n8n/
> CLI are live; Open WebUI removal is **on hold** (owner decision 2026-08-29,
> not scheduled).

---

## Principle

```text
Capabilities live in the platform.
Channels expose capabilities.
No single channel owns the platform.
```

Thor owns the platform layer: LiteLLM, MCP servers, skill runner, knowledge stores, workflow services, model aliases, access policies, and observability.

Channels are thin adapters on top. They connect users to capabilities but do not duplicate or own them.

---

## Channel Inventory

| # | Channel | Users | Access Path | Status |
|---|---|---|---|---|
| 1 | Homepage / Family Portal | Chuck, wife, daughter, son | LAN or `choukalos.com` | LAN preferred; blog is public |
| 2 | Open WebUI | Chuck, wife, daughter, son | LAN `:3000` | LAN only |
| 3 | Siri / iOS Shortcuts | Chuck | `siri.choukalos.com` | Public, API key |
| 4 | `llm.choukalos.com` | Chuck, son | `llm.choukalos.com` | Public, API key |
| 5 | PI.dev | Chuck | LAN / local | LAN only |
| 6 | Claude Code | Chuck, son | LAN / local | LAN or external |
| 7 | IDE Tools | Chuck, son | LAN / local | LAN only |
| 8 | CLI | Chuck | LAN / local | LAN only |
| 9 | n8n / Scheduled Automation | System | LAN | LAN only (not running) |
| 10 | Public Apps | Visitors | `*.choukalos.com` | Public |

---

## 1. Homepage / Family Portal

**Purpose:** Family landing page. Service discovery, status tiles, links to household services, friendly entry point for non-technical users.

**Users:** Chuck, wife, daughter, son

**Access path:** `choukalos.com` → Cloudflare Tunnel → Caddy → `portal:8080` (Hugo portal container; `/media/files/*` → `skill-runner:8091`)

**Public/LAN:** Public via Cloudflare (blog content). LAN-only features TBD.

| Allowed | Disallowed |
|---|---|
| Blog reading | AI model access |
| Service links | Skill launch |
| Status summary | Admin UI |
| Family KB read (future) | Raw filesystem |

**Tool bundle:** `{ blog-read, service-links, status-summary }`

**Key decision:** The portal is a separate project tracked in `portal_todo.md` / `blog-todo.md`. Thor exposes capabilities that the portal can link to or summarize, but Thor does not own the portal UI project. Served by the Hugo portal container (`compose/compose.portal.yml`, git-sync + static server) since the 2026-08-28 cutover (Ghost removed).

---

## 2. Open WebUI

**Purpose:** Primary human-facing chat interface. Multi-model conversations, file upload, image generation, family KB assistant, web search.

**Users:** Chuck, wife, daughter, son

**Access path:** LAN `192.168.4.54:3000` → `open-webui:8080` → `litellm-proxy:4000` + `ai-harness:8090`

**Public/LAN:** LAN only. Not exposed in Caddy.

| Allowed | Disallowed |
|---|---|
| Chat (all LiteLLM models) | Raw LiteLLM admin |
| Image generation (via ComfyUI) | Skill launch (future: yes) |
| File upload | MCP server config |
| Family KB read (via Harness) | Raw filesystem outside workspace |
| Web search (via SearXNG) | Model key management |

**Tool bundle:** `{ chat-all, image-gen, file-upload, kb-read, web-search }`

---

## 3. Siri / iOS Shortcuts

**Purpose:** Narrow public skill facade for mobile. Short actions, skill launch, skill status, artifact retrieval, short KB lookups.

**Users:** Chuck

**Access path:** `siri.choukalos.com` → Cloudflare Tunnel → Caddy (`X-API-Key: $SIRI_API_KEY`) → `ai-harness:8090`

**Public/LAN:** Public, API key auth at Caddy layer.

| Allowed | Disallowed |
|---|---|
| `POST /siri/ask` | Raw LiteLLM |
| `POST /siri/skills/{name}` | Raw MCP servers |
| `GET /siri/skills/jobs/{id}` | Admin tools |
| `GET /siri/skills/jobs/{id}/artifact` | Broad research without skill controls |
| `GET /siri/status` | Code tools |
| `GET /health` | Raw filesystem |

**Tool bundle:** `{ siri-ask, skill-launch, skill-status, artifact-retrieve, status-query }`

---

## 4. `llm.choukalos.com`

**Purpose:** Public LiteLLM proxy for remote model access. OpenAI-compatible API. Intended for Chuck and son when off-LAN.

**Users:** Chuck, son

**Access path:** `llm.choukalos.com` → Cloudflare Tunnel → Caddy (`X-API-Key: $LITELLM_PUBLIC_API_KEY`) → `litellm-proxy:4000`

**Public/LAN:** Public, API key auth at Caddy layer. Prefer LAN when home.

| Allowed | Disallowed |
|---|---|
| Chat (scoped to per-key model aliases) | LiteLLM admin routes |
| Embeddings (if key allows) | MCP tool access |
| | Skill execution |
| | Raw filesystem |
| | Any key other than the one presented |

**Tool bundle:** `{ chat-scoped, embeddings-scoped }`

Each user gets a dedicated LiteLLM API key with a model alias allowlist. See Phase 3 for key strategy.

---

## 5. PI.dev

**Purpose:** Coding agent channel. Skill-aware development workflows. Power-user experimentation.

**Users:** Chuck

**Access path:** LAN/local → `litellm-proxy:4000` (for model access) + skill runner + MCP servers

**Public/LAN:** LAN only.

| Allowed | Disallowed |
|---|---|
| Chat (coding models) | Raw production config edits |
| MCP tools (search, filesystem, knowledge) | Admin operations without manual gate |
| Skill execution | Public endpoint exposure |
| Repo-level file access | Model key management |

**Tool bundle:** `{ chat-coding, mcp-search, mcp-filesystem, mcp-knowledge, skill-execute }`

PI.dev should consume shared LiteLLM aliases, MCP tools, and skills rather than building its own backend.

---

## 6. Claude Code

**Purpose:** Terminal-based coding agent. Repo-level coding assistance for Chuck and son.

**Users:** Chuck, son

**Access path:** LAN/local → external API or `litellm-proxy:4000` (if proxied)

**Public/LAN:** LAN or external (depends on configuration).

| Allowed | Disallowed |
|---|---|
| Chat (coding models) | Family KB (unless explicitly allowed) |
| Repo-level file access | Admin operations |
| Shell commands in workspace | Public endpoint exposure |
| | Model key management |

**Tool bundle:** `{ chat-coding, file-repo, shell-workspace }`

Should use the same scoped model aliases and approved tooling patterns as other coding channels.

---

## 7. IDE Tools

**Purpose:** Editor-integrated AI (Continue, Aider, OpenCode, etc.). Inline coding assistance.

**Users:** Chuck, son

**Access path:** LAN/local → `litellm-proxy:4000` (via LiteLLM aliases)

**Public/LAN:** LAN only.

| Allowed | Disallowed |
|---|---|
| Chat (coding models via aliases) | Raw Matrix ports |
| File read/write in workspace | Family KB (unless explicitly allowed) |
| | Admin operations |
| | Public endpoint exposure |

**Tool bundle:** `{ chat-coding, file-workspace }`

Rule: IDEs should use LiteLLM aliases, not Matrix ports directly.

---

## 8. CLI

**Purpose:** Admin and power-user operations. Manual triggers, debugging, one-off tasks.

**Users:** Chuck

**Access path:** LAN/local terminal → Docker, `ai-harness:8090`, `litellm-proxy:4000`, scripts

**Public/LAN:** LAN only.

| Allowed | Disallowed |
|---|---|
| Everything (admin) | Exposing new public endpoints |
| Chat, skills, MCP, research | Binding to production ports |
| Service inspection | Deleting data or containers |
| Config editing (manual gate) | Running migrations without approval |

**Tool bundle:** `{ all }`

CLI is Chuck's full-access channel. Even so, destructive actions follow the manual gate protocol.

---

## 9. n8n / Scheduled Automation

**Purpose:** Workflow automation. Scheduled tasks, recurring reports, webhook-driven pipelines.

**Users:** System (no direct human user)

**Access path:** LAN → `n8n` (not running; compose file exists at `compose.n8n.yml`) → `ai-harness:8090` or services directly

**Public/LAN:** LAN only. Currently not running.

| Allowed | Disallowed |
|---|---|
| Skill execution | Admin operations |
| Research workflows | Raw LiteLLM config edits |
| Status checks | Public endpoint exposure |
| Report generation | Model key management |
| KB ingestion (curated) | Unrestricted filesystem writes |

**Tool bundle:** `{ skill-execute, research, status-check, report-gen, kb-ingest-curated }`

When re-enabled, n8n will use a dedicated `automation` LiteLLM key.

---

## 10. Public Apps

**Purpose:** Intentionally public web applications. Not AI platform tools — independent apps that share the homelab infrastructure.

**Users:** Public / visitors

**Access path:** `*.choukalos.com` → Cloudflare Tunnel → Caddy → respective backend

**Public/LAN:** Public.

| App | Domain | Caddy Route | Backend | Auth |
|---|---|---|---|---|
| Hugo portal | `choukalos.com` | `host choukalos.com` | `portal:8080` (+ `/media/files/*` → `skill-runner:8091`) | None |
| Invest Hub (UI) | `invest.choukalos.com` | `host invest.choukalos.com` → client `/*` | `invest-hub-client:80` | App-level |
| Invest Hub (API) | `invest.choukalos.com/api/*` or `api.choukalos.com` | `host invest.choukalos.com` → server `/api/*` or `host api.choukalos.com` | `invest-hub-server:4000` | App-level |
| Plausible | `plausible.choukalos.com` | `/js/*` and `/api/event` only | `plausible:8000` | None (narrow) |

| Allowed | Disallowed |
|---|---|
| App-specific routes only | LiteLLM access |
| App-level auth (if any) | MCP tools |
| | Skills |
| | Admin |

**Tool bundle:** `{ app-specific }`

These apps are not part of the AI platform. They use Thor's networking and proxying but are otherwise independent.

---

## Capability Matrix

Which channels can access which platform capabilities:

| Capability | Portal | OWUI | Siri | llm.ch | PI | Claude | IDE | CLI | n8n | Public |
|---|---|---|---|---|---|---|---|---|---|---|
| Chat (general) | — | ✅ | ✅ | ✅ | — | — | — | ✅ | — | — |
| Chat (coding) | — | ✅ | — | ✅ | ✅ | ✅ | ✅ | ✅ | — | — |
| Image generation | — | ✅ | — | — | — | — | — | ✅ | — | — |
| Web search | — | ✅ | — | — | ✅ | — | — | ✅ | ✅ | — |
| Deep research | — | — | — | — | ✅ | — | — | ✅ | ✅ | — |
| KB read | — | ✅ | ✅ | — | ✅ | — | — | ✅ | — | — |
| KB write | — | — | — | — | — | — | — | ✅ | ✅* | — |
| Skill launch | — | — | ✅ | — | ✅ | — | — | ✅ | ✅ | — |
| Skill status/artifact | — | — | ✅ | — | — | — | — | ✅ | ✅ | — |
| MCP tools | — | — | — | — | ✅ | — | — | ✅ | ✅ | — |
| Embeddings | — | ✅ | — | ✅ | — | — | — | ✅ | ✅ | — |
| Admin/config | — | — | — | — | — | — | — | ✅ | — | — |

*KB write via n8n is curated-only — approved ingestion path only.

---

## Access Path Summary

```
LAN users (Chuck at home):
  → Open WebUI :3000 (LAN)
  → Caddy :80 (internal proxy to all services)
  → LiteLLM :4000 (LAN)
  → AI Harness :8090 (LAN, bound to THOR_IP)
  → CLI / scripts (local)

Remote users (Chuck/Son away):
  → Cloudflare Tunnel → Caddy :80
    → siri.choukalos.com    → ai-harness:8090   (X-API-Key)
    → llm.choukalos.com     → litellm:4000       (X-API-Key)
    → choukalos.com         → portal:8080        (public)
    → invest.choukalos.com  → invest-hub         (app auth)
    → api.choukalos.com     → invest-hub-server  (app auth)
    → plausible.choukalos.com → plausible        (narrow paths)

External services:
  → GitHub Runner (self-hosted, public-net, token auth)
```

---

## Key Decision

> The portal is a separate project tracked in `portal_todo.md`.
>
> Thor exposes capabilities that the portal can link to or summarize, but Thor does not own the portal UI project.
