# Skill: presentation_update

Update an existing presentation by title using natural-language instructions, dispatched asynchronously via Presenton.

## Overview

The `presentation_update` skill lets users modify existing presentations through simple natural-language requests. It:

1. **Finds the presentation** — Searches Presenton's presentation list to locate the target by title (fuzzy match).
2. **Parses instructions** — Uses an LLM (via LiteLLM) to convert natural-language update instructions into structured update parameters (e.g., tone changes, slide count, template).
3. **Dispatches async update** — Submits the update to Presenton's async generation API, creating a new version linked to the original via `parent_id`.

This skill is designed for voice-first interfaces (Siri, CLI) where users say things like:

- *"Update the Q4 review to be more casual"*
- *"Change the AI homelab presentation to 12 slides with a dark template"*
- *"Make my marketing deck more concise"*

## Workflow

```
User: "Update the Q4 review to be more casual"
  │
  ├─► 1. Extract presentation title: "Q4 review"
  │
  ├─► 2. Search Presenton for matching presentation
  │      GET /api/v1/ppt/presentations → find best match
  │
  ├─► 3. LLM parses instructions via UPDATE_INSTRUCTION_PROMPT
  │      "more casual" → {"tone": "casual"}
  │
  ├─► 4. Dispatch async update to Presenton
  │      POST /api/v1/ppt/presentation/generate/async
  │      with parent_id, updated params
  │
  └─► 5. Return task_id + summary
         (user can poll for completion)
```

## Presenton Integration

### Internal Communication

The skill communicates with Presenton over the internal Docker network:

- **Docker network endpoint:** `http://presenton:80` (default)
- **Configurable via env:** `PRESENTON_URL` environment variable
- **Authentication:** none — Presenton runs passwordless (`DISABLE_AUTH=true`); any Basic header the skill sends is ignored server-side.

### API Endpoints Used

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v1/ppt/presentations` | GET | List all presentations (find by title) |
| `/api/v1/ppt/presentation/{id}` | GET | Get presentation details |
| `/api/v1/ppt/presentation/generate/async` | POST | Submit async generation with `parent_id` for update |
| `/api/v1/ppt/presentation/status/{task_id}` | GET | Poll async task status |

## Skill Manifest

See [skill.yml](skill.yml) for the full manifest.

| Field | Value |
|---|---|
| **Name** | `presentation_update` |
| **Version** | `1.0` |
| **Model alias** | `local/qwen-coder` |
| **Max runtime** | 300 seconds (5 minutes) |
| **Approval gates** | None |
| **Channels** | CLI, Pi, n8n, Siri |
| **Tools** | Presenton API, model chat |

## Inputs

| Parameter | Type | Required | Description |
|---|---|---|---|
| `presentation_title` | string | Yes | Title (or partial title) of the presentation to update |
| `instructions` | string | Yes | Natural-language update instructions |

## Outputs

| Field | Description |
|---|---|
| `summary` | Human-readable summary of the update result |
| `presentation_id` | Presenton's internal presentation ID of the found presentation |
| `task_id` | Presenton async task ID (for polling) |
| `found_title` | Title of the matched presentation |
| `found_version` | Current version number |
| `update_params` | Structured parameters parsed from instructions |
| `error` | Error message (if any) |
| `model_alias` | Model used for instruction parsing |

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `PRESENTON_URL` | `http://presenton:80` | Presenton base URL |
| `PRESENTON_AUTH_USERNAME` | `presenton` | Presenton HTTP Basic auth username |
| `PRESENTON_AUTH_PASSWORD` | *(unset)* | Presenton HTTP Basic auth password — **unused**: Presenton runs passwordless (`DISABLE_AUTH=true`); the header is ignored server-side |
| `LITELLM_BASE_URL` | `http://localhost:4000` | LiteLLM endpoint |
| `LITELLM_API_KEY` | *(empty)* | LiteLLM API key |
| `PRESENTATION_UPDATE_MODEL_ALIAS` | `local/qwen-coder` | Model alias for instruction parsing |
| `PRESENTATION_UPDATE_MAX_RUNTIME` | `300` | Total skill max runtime in seconds |

## Instruction Parsing

The skill uses an LLM to parse natural-language instructions into structured parameters. The prompt pattern (derived from the old harness's `UPDATE_INSTRUCTION_PROMPT`) accepts:

- **tone** — `"default"`, `"casual"`, `"professional"`, `"funny"`, `"educational"`, `"sales_pitch"`
- **template** — `"general"`, `"academic"`, `"dark"`, `"creative"`
- **n_slides** — integer (3-50)
- **verbosity** — `"concise"`, `"standard"`, `"text-heavy"`
- **language** — any language string
- **export_as** — `"pptx"` or `"pdf"`
- **instructions** — free-form text for complex/ambiguous changes

Examples:
- `"more casual"` → `{"tone": "casual"}`
- `"12 slides"` → `{"n_slides": 12}`
- `"dark template"` → `{"template": "dark"}`
- `"less text per slide"` → `{"verbosity": "concise"}`
- `"add a slide about budget"` → `{"instructions": "add a slide about budget"}`

## Error Handling

- **No matching presentation**: Returns error with available presentation suggestions.
- **Ambiguous instructions**: Returns prompt asking the user to clarify.
- **Presenton API failure**: Returns error with details.
- **LLM parsing failure**: Falls back to putting raw instructions in the `instructions` field.

## File Structure

```
skills/presentation_update/
├── README.md       ← This file
├── skill.yml       ← Skill manifest
└── skill.py        ← Implementation
```

## Testing

Run a dry run (no actual API calls):

```bash
cd skills/presentation_update
python skill.py --title "Q4 Review" --instructions "make it more casual" --dry-run
```

## Versioning

Updates create new versions of the presentation. The `parent_id` links the new version to the original. Presenton auto-increments the version number.

## Security

- **No public Presenton exposure** — Presenton is only reachable on the LAN.
- **Skill-mediated access** — All Presenton interaction goes through the skill runner.
- **Timeout enforcement** — Hard timeout prevents runaway processes.
- **No sensitive data** — The skill itself doesn't introduce sensitive data.

## References

- [Thor Skill Architecture](../../docs/thor_skill_architecture.md) — Skill manifest format and API
- [Presentation Build Skill](../presentation_build/README.md) — Sister skill for creating new presentations
- [Presenton (GitHub)](https://github.com/presenton/presenton) — Presenton project