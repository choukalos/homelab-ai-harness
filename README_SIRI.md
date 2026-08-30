# 🗣️ Siri Shortcut — AI Harness API Reference

> **How to call your Siri-enabled AI harness from an iOS Shortcuts "Get WF Content" action.**

---

## Quick Start

### Base URLs

| Environment | Base URL |
|---|---|
| **Public** (from Siri on iOS) | `https://siri.choukalos.com` |
| **Local** (testing from homelab) | `http://thor.local:8090` |

### Authentication

Every request needs **one** of these headers:

| Header | Value |
|---|---|
| `X-API-Key` | your `CHUCK_LLM_KEY` (see `.env`) |

### Request Format (JSON body)

```json
{
  "text": "Your voice command here",
  "session_id": "optional-uuid-or-string",
  "mode": "voice",
  "intent": "chat",
  "return_media": true,
  "model": null
}
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `text` | `string` | ✅ Yes | — | The user's voice prompt / command |
| `session_id` | `string \| null` | ❌ No | `null` | Track multi-turn conversations |
| `mode` | `string` | ❌ No | `"voice"` | `"voice"` or `"display"` |
| `intent` | `string` | ❌ No | `"chat"` | Force an intent override (see intents below) |
| `return_media` | `bool` | ❌ No | `true` | Include media URLs in the response |
| `model` | `string \| null` | ❌ No | `null` | Override the LLM model to use |

### Response Format (JSON body)

```json
{
  "speak": "Short answer for Siri to read aloud (≤ 700 chars)",
  "display": "Full answer for display in the Shortcuts app",
  "session_id": "optional-uuid-or-string",
  "links": [
    { "title": "Link title", "url": "https://..." }
  ],
  "media": [
    { "type": "image", "url": "https://..." }
  ],
  "data": {
    /* extra structured data from the handler */
  }
}
```

| Field | Type | Description |
|---|---|---|
| `speak` | `string` | Short voice-friendly summary Siri reads aloud |
| `display` | `string` | Full markdown-rich display answer |
| `session_id` | `string \| null` | Echoed back for conversation continuity |
| `links` | `dict[]` | Clickable links with `title` + `url` |
| `media` | `dict[]` | Media attachments (`type` + `url`) |
| `data` | `dict` | Extra structured data (task IDs, scores, etc.) |

---

## Health Check

```
GET  /health
```

No auth required. Returns `{"status": "ok"}`.

---

## Siri Route

```
POST /siri/chat
```

**This is the single route Siri calls.** The harness auto-detects the intent from your `text` and dispatches to the right backend.

You can also force an intent with `"intent": "research"` (see table below).

---

## Intent Detection — What Siri Can Do

The harness auto-detects intent from keywords in your `text`. Here's every supported action:

---

### 🧠 General Chat

| Trigger | Examples |
|---|---|
| **Default** (no keywords matched) | `"What services run in my AI harness?"`, `"Tell me a joke"`, `"What's the weather?"` |

**Async:** ❌ No — instant response.

**Input:** `"text": "What services run in my AI harness?"`

**Output:**
```json
{
  "speak": "You have the AI harness running with web search, family knowledge base, media generation...",
  "display": "Full detailed answer...",
  "session_id": null
}
```

---

### 🔍 Research Brief

| Trigger | Examples |
|---|---|
| `research` or `research brief` | `"research best local embedding models"`, `"research brief on LangChain alternatives"` |

**Async:** ❌ No — runs synchronously (~10-30 sec) but Siri won't wait forever. Use for quick topics.

**Input:** `"text": "research best local embedding models"`

**Output:**
```json
{
  "speak": "The top local embedding models are BGE, Nomic, and E5...",
  "display": "Full research brief with summaries...",
  "session_id": null,
  "links": [
    { "title": "BGE Embeddings", "url": "https://..." },
    { "title": "Nomic Embed", "url": "https://..." }
  ],
  "data": { "brief": "...", "sources": [...] }
}
```

---

### 🕵️ Deep Research (Long-Running)

| Trigger | Examples |
|---|---|
| `deep research` | `"deep research autonomous vehicle safety regulations 2025"` |

**Async:** ⚠️ Partially — this fires a workflow with MySQL checkpointing. The `/siri/chat` call itself blocks for up to ~180 seconds waiting for the workflow result.

**Input:** `"text": "deep research autonomous vehicle safety"`

**Output:**
```json
{
  "speak": "Deep research found that autonomous vehicle regulations vary significantly across regions...",
  "display": "Full research report...",
  "session_id": null,
  "links": [
    { "title": "NHTSA Guidelines", "url": "https://..." },
    { "title": "EU AI Act", "url": "https://..." }
  ],
  "data": { "answer": "...", "sources": [...] }
}
```

---

### 🎨 Image Generation (ComfyUI)

| Trigger | Examples |
|---|---|
| `generate image`, `make an image`, `draw` | `"generate image of a futuristic server room"`, `"draw a cute robot cat"` |

**Async:** ⚠️ Semi — blocks while ComfyUI generates the image (typically 30-60 sec).

**Input:** `"text": "generate image of a futuristic server room"`

**Output:**
```json
{
  "speak": "I generated the image.",
  "display": "Image generated.",
  "session_id": null,
  "media": [
    { "type": "image", "url": "https://siri.choukalos.com/media/files/images/..." }
  ],
  "data": { "files": [...] }
}
```

---

### 📄 One-Page HTML Demo (Instant)

| Trigger | Examples |
|---|---|
| `html demo`, `one page demo`, `prototype` | `"Create a one page HTML demo of my family wiki"` |

**Async:** ❌ No — instant LLM-generated HTML (no research pipeline).

**Input:** `"text": "Create a one page HTML demo of my family wiki with ascii art"`

**Output:**
```json
{
  "speak": "I created the one page demo.",
  "display": "Demo created: https://siri.choukalos.com/...",
  "session_id": null,
  "links": [
    { "title": "Open HTML demo", "url": "https://siri.choukalos.com/..." }
  ],
  "data": { ... }
}
```

---

### 🚀 Full Demo Pipeline (Async — Celery)

| Trigger | Examples |
|---|---|
| `create a demo`, `create demo`, `build a demo`, `build demo`, `generate a demo`, `make a demo` | `"build a demo for a pet adoption app"`, `"create a demo of a smart home dashboard"` |

**Async:** ✅ YES — this fires a Celery background task (2-5 minutes).

**How the async flow works:**

1. **Siri Shortcut calls** `POST /siri/chat` → returns immediately with a task ID
2. **Celery worker** researches, designs, and builds the demo in the background
3. **You follow up** by asking Siri `"list my demos"` to see if it's done

**Input:** `"text": "build a demo for a pet adoption app"`

**Output (Step 1 — Dispatch):**
```json
{
  "speak": "I've started building your demo. It will take a couple minutes. Ask me to list your demos when it's done.",
  "display": "Demo build started!\nTitle: Build a Demo For A Pet Adoption App\nTask ID: abc-123-xyz\n\nThe pipeline will research, design, and build your demo.\nTypical completion time: 2-5 minutes.\nFollow up with: 'list my demos'",
  "session_id": null,
  "data": {
    "title": "Build a Demo For A Pet Adoption App",
    "task_id": "abc-123-xyz"
  }
}
```

**⚠️ Key for Siri Shortcuts:** Store the `data.task_id` in your shortcut variable to track progress.

---

### 📊 List Demos

| Trigger | Examples |
|---|---|
| `list demo`, `show demo`, `my demos`, `demo list`, `demos we` | `"list my demos"`, `"what demos do I have?"` |

**Async:** ❌ No — instant filesystem scan.

**Input:** `"text": "list my demos"`

**Output:**
```json
{
  "speak": "I found 3 demos. Pet Adoption App, Smart Home Dashboard, Family Wiki",
  "display": "I have 3 demo(s):\n- Pet Adoption App: https://siri.choukalos.com/...\n- Smart Home Dashboard: https://siri.choukalos.com/...\n- Family Wiki: https://siri.choukalos.com/...",
  "session_id": null,
  "links": [
    { "title": "Pet Adoption App", "url": "https://..." },
    ...
  ]
}
```

---

### 🔎 Find Demo

| Trigger | Examples |
|---|---|
| `find demo`, `demo about`, `demo for`, `search demo` | `"find demo about pets"`, `"demo for smart home"` |

**Async:** ❌ No — instant.

**Output:** Same format as List Demos, filtered by keywords.

---

### 📈 Demo Quality

| Trigger | Examples |
|---|---|
| `how well does`, `demo quality`, `demo score`, `demo rating` | `"how well does the pet adoption demo work?"`, `"demo score for smart home"` |

**Async:** ❌ No — instant (reads `metadata.json`).

**Output:**
```json
{
  "speak": "Quality report: Pet Adoption App: score 8 out of 10 complexity 6",
  "display": "Demo quality report (1 matching):\n\n### Pet Adoption App\n- **Quality Score**: 8/10\n- **Mocked features** (2): ...\n- **Verified interactions** (5): ...\n- **Issues**: None",
  "session_id": null
}
```

---

### 🧩 Demo Complexity

| Trigger | Examples |
|---|---|
| `how complex is`, `demo complexity`, `research insights`, `mvp features` | `"how complex is the pet adoption demo?"`, `"mvp features for smart home"` |

**Async:** ❌ No — instant.

**Output:**
```json
{
  "speak": "Complexity report: Pet Adoption App: complexity 6/10, effort: 2-3 days",
  "display": "Demo complexity report (1 matching):\n\n### Pet Adoption App\n- **Complexity Score**: 6/10\n- **Screens**: 4\n- **Interactive elements**: 8\n- **Estimated build effort**: 2-3 days\n- **MVP features** (3): login, pet browsing, favorites",
  "session_id": null
}
```

---

### 📽️ Create Presentation (Async — Celery)

| Trigger | Examples |
|---|---|
| `create a presentation`, `create presentation`, `build a presentation`, `make a presentation`, `generate a presentation` | `"create a presentation about our AI homelab"`, `"build a presentation on quarterly results"` |

**Async:** ✅ YES — fires a Celery background task (3-5 minutes).

**How the async flow works:**

1. **Siri Shortcut calls** `POST /siri/chat` → returns immediately (fire-and-forget)
2. **Celery worker** researches, designs, and builds the presentation
3. **You follow up** by asking Siri `"list my presentations"` to see if it's done

**Input:** `"text": "create a presentation about our AI homelab"`

**Output (Step 1 — Dispatch):**
```json
{
  "speak": "I've started creating your presentation. It will take a few minutes. Ask me to list your presentations when it's done.",
  "display": "Presentation generation started!\nTitle: Create A Presentation About Our AI Homelab\n\nThe pipeline will research, design, and build your presentation.\nTypical completion time: 3-5 minutes.\nFollow up with: 'list my presentations'",
  "session_id": null,
  "data": {
    "title": "Create A Presentation About Our AI Homelab"
  }
}
```

**⚠️ Note:** Unlike demos, the presentation dispatch is truly fire-and-forget (no task ID returned). Check back with "list my presentations".

---

### 📋 List Presentations

| Trigger | Examples |
|---|---|
| `list presentation`, `show presentation`, `my presentations`, `presentation list`, `presentations we` | `"list my presentations"`, `"show my presentations"` |

**Async:** ❌ No — instant (calls the presentation API).

**Output:**
```json
{
  "speak": "I found 2 presentations. AI Homelab v1, Quarterly Review v1",
  "display": "I have 2 presentation(s):\n- AI Homelab (v1): https://...\n- Quarterly Review (v1): https://...",
  "session_id": null,
  "links": [
    { "title": "AI Homelab", "url": "https://..." },
    ...
  ]
}
```

---

### 🔍 Find Presentation

| Trigger | Examples |
|---|---|
| `find presentation`, `presentation about`, `presentation for`, `search presentation` | `"find presentation about homelab"`, `"presentation for quarterly review"` |

**Async:** ❌ No — instant.

**Output:** Same format as List Presentations, filtered by keyword.

---

### ✏️ Update Presentation (Async — Celery)

| Trigger | Examples |
|---|---|
| `update a presentation`, `update presentation`, `change the presentation`, `revise the presentation`, `modify the presentation`, `improve the presentation`, `fix the presentation` | `"update the AI homelab presentation to be more casual"`, `"change the quarterly review to 12 slides"`, `"improve my presentation about AI"` |

**Async:** ✅ YES — fires a Celery background task (3-5 minutes).

**How it works:**

1. Siri parses the presentation title from your voice text (strips prefixes like "update the", "change my")
2. If you include instructions (e.g. "to be more casual", "to 12 slides"), the LLM parses them into structured update parameters
3. The harness searches for your presentation by title, then dispatches an async update to Presenton
4. **You follow up** by asking Siri `"list my presentations"` to see if the update is done

**Input:** `"text": "update the AI homelab to be more casual"`

**Output (Step 1 — Dispatch):**
```json
{
  "speak": "I've started updating your 'AI homelab' presentation. Changing: tone to casual. It will take a couple minutes. Ask me to list your presentations when it's done.",
  "display": "Presentation update started!\nTitle: AI homelab (v1 → v2)\nTask ID: abc-123-xyz\n\nChanges: tone to casual\n\nTypical completion time: 3-5 minutes.\nFollow up with: 'list my presentations'",
  "session_id": null,
  "data": {
    "presentation_id": "...",
    "title": "AI homelab",
    "task_id": "abc-123-xyz",
    "changes": { "tone": "casual" }
  }
}
```

**⚠️ Note:** If no update instructions are provided, Siri will ask what changes you'd like to make (e.g. "Make it more casual" or "Add more slides").

---

## 🔄 Async Flow Cheat Sheet

These intents return **immediately** while work happens in the background. You must follow up in a **second Siri call**:

| Intent | Initial Response | Follow Up With |
|---|---|---|
| **Create Demo** | `"I've started building your demo..."` + `task_id` in `data` | `"list my demos"` — check if it's ready |
| **Create Presentation** | `"I've started creating your presentation..."` (fire-and-forget) | `"list my presentations"` — check if it's ready |
| **Update Presentation** | `"I've started updating your presentation..."` + `task_id` in `data` | `"list my presentations"` — check if the update is done |
| **Deep Research** | ⚠️ Blocks for up to 180 sec (not truly async from Siri's view) | — |
| **Image Generation** | ⚠️ Blocks for 30-60 sec while ComfyUI renders | — |
| **Research Brief** | ⚠️ Blocks for 10-30 sec | — |

### Siri Shortcut Pattern for Async Tasks

```
┌─────────────────────────────────────────────┐
│ 1. Siri: "build a demo for my new app"      │
│    → POST /siri/chat with text               │
│    → Response says: "started, task_id=xyz"  │
│    → Store task_id in shortcut variable       │
└──────────────────┬──────────────────────────┘
                   │
                   │  Wait 2-5 minutes...
                   │
┌──────────────────▼──────────────────────────┐
│ 2. Siri: "list my demos"                    │
│    → POST /siri/chat with text               │
│    → Response lists all demos with URLs     │
│    → Your new demo should appear!           │
└─────────────────────────────────────────────┘
```

---

## 🧪 Testing

### Smoke Test Script

```bash
# Run from homelab:
./ai-harness/tests/siri-smoke-test.sh
```

This tests health (local + public), Siri chat (local + public), and auth rejection.

### Manual cURL

```bash
# Quick chat test
curl -X POST https://siri.choukalos.com/siri/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: LITELLM_KEY_CHUCK (see .env)" \
  -d '{"text":"What services run in my AI harness?"}'

# Research
curl -X POST https://siri.choukalos.com/siri/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: LITELLM_KEY_CHUCK (see .env)" \
  -d '{"text":"research best local embedding models"}'

# Image (will take 30-60 sec)
curl -X POST https://siri.choukalos.com/siri/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: LITELLM_KEY_CHUCK (see .env)" \
  -d '{"text":"generate image of a futuristic server room"}'

# Demo (async — returns immediately)
curl -X POST https://siri.choukalos.com/siri/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: LITELLM_KEY_CHUCK (see .env)" \
  -d '{"text":"build a demo for a pet adoption app"}'

# Force intent override
curl -X POST https://siri.choukalos.com/siri/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: LITELLM_KEY_CHUCK (see .env)" \
  -d '{"text":"something ambiguous", "intent":"research"}'

# Update a presentation (async)
curl -X POST https://siri.choukalos.com/siri/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: LITELLM_KEY_CHUCK (see .env)" \
  -d '{"text":"update the AI homelab to be more casual"}'
```

---

## 🔐 Siri Shortcut Configuration

### Getting WF Content (HTTPS Request)

| Setting | Value |
|---|---|
| **Method** | `POST` |
| **URL** | `https://siri.choukalos.com/siri/chat` |
| **Header** | `X-API-Key: <LITELLM_KEY_CHUCK (see .env)>` |
| **Body** | `{"text": "<user input variable>"}` |
| **Content-Type** | `application/json` |

### Parsing the Response

After the "Get WF Content" action, use **"Get Dictionary Value"** to extract:

| Key | Use |
|---|---|
| `speak` | Feed to **"Speak Text"** action for Siri to read |
| `display` | Show in a **"Text"** action or display card |
| `media.0.url` | Show generated images in **"Show Web Page"** |
| `links.0.url` | Open in Safari with **"Open URLs"** |
| `data.task_id` | Store for async tracking |

---

## Architecture

```
┌──────────┐     HTTPS      ┌──────────┐     HTTP      ┌────────────┐
│  iOS /    │  ──────────►  │  Caddy   │  ──────────►  │  AI Harness│
│  Siri     │  siri.choukalos.com     │  (reverse     │  :8090     │
│  Shortcut │                 proxy +  │               │  (FastAPI) │
└──────────┘                 auth)     │               └─────┬──────┘
                                       └──────────┐         │
                                                   │         │
                    ┌────────────┐    ┌────────────┴────┐   │
                    │   ComfyUI  │    │   Celery Worker  │   │
                    │  (images)  │    │  (demos +       │   │
                    │ :8188      │    │   presentations) │   │
                    └────────────┘    └─────────────────┘   │
                                                            │
                    ┌────────────┐    ┌──────────────────┐  │
                    │   LiteLLM  │    │   MySQL / Redis  │  │
                    │  (LLM API) │    │  (checkpoint +   │  │
                    │ :4000      │    │   cache)         │  │
                    └────────────┘    └──────────────────┘  │
                                                            │
                    ┌────────────┐    ┌──────────────────┐  │
                    │   SearXNG  │    │    Presenton     │  │
                    │  (search)  │    │  (presentations) │  │
                    │ :8080      │    │ :80              │  │
                    └────────────┘    └──────────────────┘  │
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| **401 Unauthorized** | Check your `X-API-Key` header matches `LITELLM_KEY_CHUCK` in `.env` |
| **Caddy blocks the request** | Ensure `X-API-Key` is sent; Caddy validates before proxying |
| **Siri says "I couldn't complete your request"** | The shortcut's HTTPS request may be timing out — increase timeout or use async patterns |
| **Deep research hangs** | The 180-second timeout may not be enough; consider using a simpler `research` intent |
| **Image never appears** | Check ComfyUI is running on matrix.local:8188 |
| **Demo never completes** | Check Celery worker is running; check logs in the harness container |
