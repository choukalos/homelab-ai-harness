# Skill: presentation_build

Generate slide deck presentations from a topic or existing content using Presenton.

## Overview

The `presentation_build` skill orchestrates a multi-step pipeline:

1. **Content preparation** — If a `content_source` (file path or raw text) is provided, its content is used as context. Otherwise, the skill works from the topic alone.
2. **Outline generation** — The LLM (via LiteLLM) generates a structured markdown outline with the requested number of slides, style-appropriate tone, and concise bullet points.
3. **Presenton generation** — The outline is submitted to Presenton's async generation API. The skill polls until Presenton completes the slide deck.
4. **Artifact download** — The exported presentation file (`.pptx`) is downloaded from Presenton and saved as an artifact.

## Presenton Integration (Phase 11)

### Architecture

```
┌─────────────┐     ┌────────────┐     ┌────────────┐     ┌───────────────┐
│  Skill       │     │  Presenton │     │  Artifact   │     │  User         │
│  Runner      │────▶│  Container │────▶│  Storage    │────▶│  (LAN / Siri) │
│  :8091       │     │  :80       │     │  /data/     │     │               │
│              │     │            │     │  media/     │     │               │
│  (public     │     │  (LAN-ONLY │     │  presentati │     │  LAN: direct  │
│   via skill  │     │  no public │     │  ons/       │     │  file access  │
│   API)       │     │   routing) │     │             │     │  Siri: /media │
└─────────────┘     └────────────┘     └─────────────┘     └───────────────┘
```

### LAN-Only Constraint

**Presenton UI is LAN-only.** The Presenton web interface (port 5000 on the host) is intentionally NOT exposed through Caddy or Cloudflare Tunnel. There is no public URL for Presenton.

The `presentation_build` skill is the **only remote access path** to Presenton. Users can trigger presentations through:

- **Skill Runner API** (`POST /skills/presentation_build`) — available on LAN
- **Siri path** — via the skill runner's Siri channel adapter
- **CLI** — direct invocation on the homelab

Remote users cannot access Presenton directly. They must go through the skill runner, which handles all Presenton interaction internally.

### Internal Communication

The skill communicates with Presenton over the internal Docker network:

- **Docker network endpoint:** `http://presenton:80` (default)
- **Host endpoint:** `http://192.168.4.54:5000` (for host-based testing)
- **Configurable via env:** `PRESENTON_URL` environment variable
- **Authentication:** HTTP Basic Auth (username/password from `PRESENTON_AUTH_USERNAME`/`PRESENTON_AUTH_PASSWORD` env vars)

The skill uses Presenton's async API to avoid holding open long-lived HTTP connections:
1. `POST /api/v1/ppt/presentation/generate/async` — submit generation job
2. `GET /api/v1/ppt/presentation/status/{task_id}` — poll for completion
3. `GET {export_path}` — download the generated file

## Skill Manifest

See [skill.yml](skill.yml) for the full manifest.

| Field | Value |
|---|---|
| **Name** | `presentation_build` |
| **Version** | `1.0` |
| **Model alias** | `local/qwen-coder` |
| **Max runtime** | 300 seconds (5 minutes) |
| **Approval gates** | None (generative, no sensitive data unless provided) |
| **Channels** | CLI, Siri, n8n |
| **Artifact path** | `/home/chuck/data/media/presentations/` |
| **Tools** | Presenton API, model chat, optional `mcp_knowledge` |

## Inputs

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `topic` | string | Yes | — | The presentation topic or title |
| `slide_count` | integer | Yes | 8 | Number of slides (1-50) |
| `style` | string | No | `modern` | Presentation style: `modern`, `minimal`, `bold`, `elegant`, `academic`, `creative`, `dark` |
| `content_source` | string | No | — | Path to an existing artifact file, or raw text to use as content context |

## Outputs

| Field | Description |
|---|---|
| `summary` | Human-readable summary of the generation result |
| `presentation_id` | Presenton's internal presentation ID |
| `title` | The presentation title/topic |
| `slide_count` | Number of slides generated |
| `style` | Style used |
| `outline` | The markdown outline sent to Presenton |
| `artifact_path` | Path to the saved `.pptx` file |
| `edit_url` | Internal Presenton UI URL (LAN-only) |
| `model_alias` | Model used for outline generation |

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PRESENTON_URL` | `http://presenton:80` | Presenton base URL |
| `PRESENTON_AUTH_USERNAME` | `presenton` | Presenton HTTP Basic auth username |
| `PRESENTON_AUTH_PASSWORD` | `changeme123` | Presenton HTTP Basic auth password |
| `PRESENTON_GENERATION_TIMEOUT` | `240` | Timeout (seconds) for Presenton generation polling |
| `PRESENTATION_BUILD_MAX_RUNTIME` | `300` | Total skill max runtime in seconds |
| `PRESENTATION_BUILD_ARTIFACT_DIR` | `/home/chuck/data/media/presentations` | Artifact output directory |
| `LITELLM_BASE_URL` | `http://localhost:4000` | LiteLLM endpoint |
| `LITELLM_API_KEY` | *(empty)* | LiteLLM API key |
| `PRESENTATION_BUILD_MODEL_ALIAS` | `local/qwen-coder` | Model alias for outline generation |

## Workflow Details

### Phase 1: Content & Outline Generation
- If `content_source` is a file path, the file is read and its content becomes the context.
- If `content_source` is raw text, it is used directly as context.
- The LLM generates a markdown outline with the requested number of slides.
- Style is mapped to Presenton-compatible template and tone settings.

### Phase 2: Presenton Submission
- The outline is sent to Presenton's `/api/v1/ppt/presentation/generate/async` endpoint.
- Returns a `task_id` for polling.

### Phase 3: Polling
- The skill polls `/api/v1/ppt/presentation/status/{task_id}` every 5 seconds.
- Waits up to `PRESENTON_GENERATION_TIMEOUT` seconds (default 240s).
- On `completed`, extracts `presentation_id`, `path`, and `edit_path`.

### Phase 4: Download
- Downloads the exported file from Presenton using the `path` field.
- HTTP Basic auth is used for all Presenton requests.

### Phase 5: Artifact Save
- Saves the `.pptx` file to the artifact directory.
- Filename: `presentation_{timestamp}_{slug}.pptx`.

## Security

- **No public Presenton exposure** — Presenton is only reachable on the LAN.
- **Skill-mediated access** — All Presenton interaction goes through the skill runner.
- **Artifact isolation** — Generated files use opaque timestamps and slugs.
- **No sensitive data** — The skill itself doesn't introduce sensitive data unless `content_source` contains it.
- **Timeout enforcement** — Hard timeout prevents runaway processes.

## Remote Access via Siri

Users with Siri/iOS Shortcuts can request presentations through the skill runner's Siri channel. The skill runner translates the Siri request into skill parameters and returns the artifact link. The user never interacts with Presenton directly.

Example Siri flow:
1. User says: "Create a presentation about Q3 results"
2. Siri shortcut → Skill Runner → `presentation_build` skill
3. Skill generates outline, submits to Presenton, downloads artifact
4. Response includes short summary + artifact download link

## File Structure

```
skills/presentation_build/
├── README.md       ← This file
├── skill.yml       ← Skill manifest
└── skill.py        ← Implementation
```

## Testing

Run a dry run (no actual API calls):

```bash
cd skills/presentation_build
python skill.py --topic "AI in Healthcare" --slide-count 8 --dry-run
```

Run with custom endpoints (for local testing):

```bash
python skill.py \
    --topic "Q3 Review" \
    --slide-count 10 \
    --style bold \
    --base-url http://localhost:4000 \
    --api-key "your-key" \
    --presenton-url http://localhost:5000
```

## Rollback

On failure, the skill:
- Does not partially write artifacts (files are written atomically).
- Returns an error summary with details.
- The artifact directory is never modified on failure.

To clean up a failed presentation:
1. Delete the artifact file if it was partially written (edge case).
2. Presenton's internal database retains the presentation — clean via Presenton UI or the cleanup script in `ai-harness/tests/cleanup_presentations.sh`.

## References

- [Thor Skill Architecture](../../docs/thor_skill_architecture.md) — Skill manifest format and API
- [Thor AI Harness Rebuild Strategy](../../docs/thor_ai_harness_rebuild.md) — Presenton integration notes
- [Thor Artifact Strategy](../../docs/thor_artifact_strategy.md) — Artifact storage conventions
- [Presenton (GitHub)](https://github.com/presenton/presenton) — Presenton project
