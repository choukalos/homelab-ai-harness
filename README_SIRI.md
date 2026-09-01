# 🗣️ Siri / "Peanut" — AI Harness API Reference

> How the iOS Shortcuts "Peanut" shortcut talks to the homelab AI harness.
>
> **For the human-facing guide** (building the shortcut, adding family members,
> CarPlay link retrieval) see **[PEANUT_SHORTCUT.md](./PEANUT_SHORTCUT.md)**.
> This file is the machine-facing API reference.

---

## Quick Start

### Base URLs

| Environment | Base URL |
|---|---|
| **Public** (from Siri on iOS) | `https://siri.choukalos.com` |
| **Local** (testing from homelab) | `http://thor.local:8091` (a.k.a. `http://192.168.4.54:8091`) |

Public path: Cloudflare Tunnel → Caddy (`siri.choukalos.com`) → `skill-runner:8091`
(FastAPI, container `skill-runner`). Caddy strips the `/siri` prefix before
proxying, so the public `/siri/...` path maps to the runner's root routes.

### Authentication

Every request except `GET /health` needs **one** of the allowed family keys
in the `X-API-Key` header. Caddy enforces this at the edge (401 otherwise);
the runner re-checks against `SKILL_RUNNER_API_KEY` (defense in depth).

| Key (`.env`) | User | Notes |
|---|---|---|
| `LITELLM_KEY_CHUCK` | chuck | unlimited budget |
| `LITELLM_KEY_DYLAN` | dylan | unlimited budget |
| `LITELLM_KEY_<NAME>` | family members | added per the onboarding guide in PEANUT_SHORTCUT.md |

**Budgets:** no family key carries a budget cap — the models are local, so
budgets would only block legitimate use. Spend is still tracked per key in
LiteLLM (`./homelab.sh key list`) for the family ROI calculation.

**Memory identity:** each key maps to a per-person memory identity via
`MEMORY_USER_KEYS` in `.env` (e.g. `chuck=LITELLM_KEY_CHUCK,dylan=LITELLM_KEY_DYLAN`).
Unmapped keys resolve to `unknown` (no memory retrieval/writeback).

---

## Endpoints

### Health

```
GET /health            (public: /siri/health)
```
No auth. Returns `{"status": "ok", "port": 8091, "jobs_total": N}`.

### Chat Gateway (the single route Siri calls)

```
POST /api/chat         (public: /siri/api/chat)
```

**Request body** (JSON):

```json
{
  "text": "Your voice command here",
  "intent": "chat",
  "model": null,
  "memory": null
}
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `text` | `string` | ✅ | — | The voice prompt / question |
| `intent` | `string` | ❌ | auto-detected | Force an intent override (see table below) |
| `model` | `string` | ❌ | `$SKILL_RUNNER_DEFAULT_MODEL` (currently `matrix-coder`) | LiteLLM model alias override |
| `memory` | `dict` | ❌ | `null` | `{"enabled": false}` disables memory retrieval/writeback for this request |

**Response body** (JSON):

```json
{
  "speak": "Short voice-friendly answer (≤ ~250 chars, sentence-truncated)",
  "display": "Full answer (markdown ok)",
  "job_id": "abc123def456 or null",
  "links": ["https://...", "https://..."],
  "media": "https://siri.choukalos.com/media/files/... or null",
  "data": { "model_alias": "matrix-coder", "intent": "chat", "...": "..." }
}
```

| Field | Description |
|---|---|
| `speak` | What Siri reads aloud. Short, conversational, truncated at sentence boundaries (~250 chars) |
| `display` | Full answer for the Shortcuts "Show Result" card |
| `job_id` | Present when the request dispatched an **async job** — poll `GET /skills/jobs/{job_id}` |
| `links` | List of public URL strings (research sources, demo URLs, etc.) |
| `media` | Public URL of a generated image (or `null`) |
| `data` | Extra structured data (model alias, skill, intent, task ids, errors) |

### Async Job Polling

```
GET /skills/jobs/{job_id}     (public: /siri/skills/jobs/{job_id})
GET /skills/jobs/{job_id}/artifact
```

Job response: `{job_id, skill, status, created_at, completed_at, summary,
artifact_path, requester, channel, params, model_alias, error}`.

`status` ∈ `pending | running | completed | failed | awaiting_approval |
cancelled | interrupted`. For `siri-chat` jobs, `summary` is the answer text.

### Media Files

```
GET /media/files/{filepath}   (public: /siri/media/files/{filepath})
```
No auth. Serves generated images/demos from the media library.
`PUBLIC_MEDIA_BASE = https://siri.choukalos.com/media/files`.

### Presentations

```
GET /presentations/*          (public: /siri/presentations/*)
```
Proxies to Presenton (view/edit presentations built by the harness).

---

## Intent Detection

The harness auto-detects the intent from keywords in `text` (order matters —
first match wins). Override with the `intent` field.

### Sync intents (full answer in the first response)

| Intent | Voice triggers | Notes |
|---|---|---|
| `chat` (default) | anything else | Direct model chat, **no tools**, memory on. Fast |
| `media-generate` | "generate image", "create image", "make image", "draw image", "render image" | Blocks 30–90s (GPU pipeline). Returns `media` = public image URL |
| `remember` | "remember …", "please note …", "keep in mind …" | Stores a durable memory for the caller's identity |
| `forget` | "forget …" | Targeted memory delete |

### Async intents (response returns `job_id` immediately)

| Intent | Voice triggers | Typical time |
|---|---|---|
| `siri-chat` | "siri chat …", "siri ask …" | 10–60s. Chat **with MCP tools**: family KB (`kb_search`), web search, homelab status |
| `research-brief` | "research brief …" | 10–60s |
| `deep-research` | "deep research …" | minutes (workflow w/ MySQL checkpointing) |
| `create-demo` | "create demo …", "new demo …" | 2–5 min (Celery) |
| `build-presentation` | "present …", "slide …", "deck …" | 3–5 min (Celery) |
| `update-presentation` | "update … presentation/deck/slides …" | 3–5 min (Celery) |
| `list-demos` | "list demo(s)", "list my demos" | seconds |
| `find-demos` | "find demo …", "browse demos", "search demo …" | seconds |
| `list-presentations` | "list presentation(s)", "list my deck" | seconds |
| `list-images` | "list image(s)", "show my images", "what images …" | seconds |
| `investment-brief` | "investment brief", "stock brief", "market brief" | 30–60s |
| `morning-brief` | "morning brief", "daily brief", "daily summary" | 30–60s |
| `business-analyst` | "analyze …", "how many …", "top … by …", "show me … data" | ~300s (NL→SQL over family MySQL; Markdown report + Grafana suggestions) |
| `content-writer` | "write …", "draft …", "create a … post/script" | ~480s (social/blog/video content pack) |
| `marketing-strategy` | "go-to-market", "GTM", "launch plan", "market strategy" | ~300s (GTM launch plan) |

**Async pattern for shortcuts:** POST → get `job_id` → loop
(`Wait 5s` → `GET /siri/skills/jobs/{job_id}`) until `status == completed`
or `failed` → read `summary` (and `data`/artifact for links/media).

---

## Testing

### Smoke test

```bash
# Health (public + local)
curl -s https://siri.choukalos.com/siri/health
curl -s http://thor.local:8091/health

# Quick chat (sync)
curl -s -X POST https://siri.choukalos.com/siri/api/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $LITELLM_KEY_CHUCK" \
  -d '{"text":"What services run in my AI harness?"}'

# KB-enabled chat (async — poll the job_id it returns)
curl -s -X POST https://siri.choukalos.com/siri/api/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $LITELLM_KEY_CHUCK" \
  -d '{"text":"what do we know about X", "intent":"siri-chat"}'
# then:
curl -s https://siri.choukalos.com/siri/skills/jobs/<job_id> \
  -H "X-API-Key: $LITELLM_KEY_CHUCK"

# Image (sync, 30–90s)
curl -s -X POST https://siri.choukalos.com/siri/api/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $LITELLM_KEY_CHUCK" \
  -d '{"text":"generate image of a futuristic server room"}'
```

### Key management

```bash
./homelab.sh key list                 # all keys: user, models, spend, budget
./homelab.sh key info <user>          # full details
./homelab.sh key add <user> [--rpm N] # create a key (no budget by default)
./homelab.sh key update <user> --rpm N
./homelab.sh key delete <user>
```

---

## Architecture

```
┌──────────┐    HTTPS     ┌────────┐    HTTP (strip /siri)   ┌────────────────┐
│ iOS      │ ───────────► │ Caddy  │ ───────────────────────► │ skill-runner   │
│ Shortcuts│ siri.choukalos.com   │ X-API-Key allowlist      │ :8091 (FastAPI)│
└──────────┘              └────────┘                         └───────┬────────┘
                                                                     │
        ┌────────────────────────────────────────────────────────────┤
        │                                                            │
┌───────▼───────┐   ┌────────────────┐   ┌──────────────┐   ┌────────▼──────┐
│ LiteLLM proxy │   │ MCP servers    │   │ MySQL / Redis│   │ Media library │
│ :4000 (LLM +  │   │ (knowledge KB, │   │ (job index,  │   │ /media/files/ │
│  virtual keys)│   │  search, media,│   │  mem0 cache) │   │ (public URLs) │
└───────────────┘   │  homelab, …)  │   └──────────────┘   └───────────────┘
                    └────────────────┘
        GPU host (matrix:8188 ComfyUI, media pipeline) · Mac Studio (LM Studio)
```

- **Models:** `matrix-coder` (vLLM on matrix, default), `studio-gemma4-26b`
  (LM Studio on Mac Studio), `embeddings` / `homelab-embedding-v1` (nomic).
  Default chat model: `SKILL_RUNNER_DEFAULT_MODEL` env var (`.env`).
- **Memory:** in-process mem0 in skill-runner, Qdrant collection
  `mem0_memories`, per-user identities from `MEMORY_USER_KEYS`.
- **Spend tracking:** every key's spend is recorded in LiteLLM (local models
  cost ~$0; tracked for ROI).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| **401 Unauthorized** (Caddy) | `X-API-Key` missing or not in the Caddy allowlist (`caddy/Caddyfile`, `@siri` handler). New family members need the key added there + to `SKILL_RUNNER_API_KEY` |
| **403 Invalid API key** (runner) | Key passes Caddy but isn't in `SKILL_RUNNER_API_KEY` (compose.skill-runner.yml) — recreate the container |
| **400 Invalid model name** | `model` override (or `SKILL_RUNNER_DEFAULT_MODEL`) doesn't match a name in `litellm/config.yml` — check `GET /v1/models` on the proxy |
| **Memory 401s in skill-runner logs** | `MEMORY_LITELLM_KEY` in `.env` is stale — regenerate via `POST /key/generate` (models: matrix-coder, homelab-embedding-v1, embeddings), update `.env`, restart skill-runner |
| **Siri says "couldn't complete"** | Shortcut timeout — long intents (deep research, demos) return a `job_id` immediately; poll instead of waiting |
| **Image never appears** | Check the GPU media pipeline (matrix host) and that `media` in the response is a public URL |
| **Job stuck `running`** | `docker logs skill-runner | tail -50`; check the skill's MCP deps (mcp_knowledge, mcp_media, …) are up |

---

## Change Log

- **2026-08-30:** Rewritten to match the running harness. Route is
  `/siri/api/chat` (not `/siri/chat`); runner port is 8091 (not 8090);
  request/response schemas updated (`job_id`, `links: [str]`, `media: str`);
  intent list regenerated from `_detect_intent()`; default model is now
  `matrix-coder` via `SKILL_RUNNER_DEFAULT_MODEL`; family budgets removed
  (local models — spend tracked for ROI only); new: `remember`/`forget`,
  `list-images`, `investment-brief`, `morning-brief` intents.
  Shortcut + family-onboarding guide moved to PEANUT_SHORTCUT.md.