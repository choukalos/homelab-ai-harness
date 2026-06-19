# Presentation Module

> AI-powered presentation generation using [Presenton](https://github.com/presenton/presenton).
> Integrated into ai-harness for use by Siri, OpenWebUI, and direct API.

## Overview

This module wraps the Presenton API to generate PowerPoint/PDF presentations
from topics, outlines, or research content. Generated files are saved to
`/data/media/presentations/` with companion `metadata.json` files for tracking
and versioning.

## Endpoints

```
POST /presentation/generate          — One-shot presentation generation (sync)
POST /presentation/generate/async    — Async generation via Celery (Siri)
POST /presentation/outline           — Collaborative outline generation
PATCH /presentation/{id}             — Regenerate with changes (new version)
GET  /presentation/list              — List all presentations
GET  /presentation/{id}              — Get presentation details by ID
GET  /presentation/search?title=     — Find presentations by title
GET  /presentation/tasks/{task_id}   — Check async task status
DELETE /presentation/{id}            — Delete a presentation
GET  /presentation/download/{fn}     — Download a presentation file
```

All endpoints require `HARNESS_API_KEY` or `SIRI_API_KEY` via `Authorization: Bearer <key>`
or `X-Api-Key: <key>` header.

## Usage Examples

### Generate a presentation (one-shot)

```bash
curl -X POST http://thor.local:8090/presentation/generate \
  -H "Authorization: Bearer $HARNESS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Q4 Review",
    "content": "Quarterly business review covering revenue, growth, and outlook",
    "n_slides": 10,
    "template": "general",
    "tone": "professional",
    "export_as": "pptx"
  }'
```

### With a pre-built outline

```bash
curl -X POST http://thor.local:8090/presentation/generate \
  -H "Authorization: Bearer $HARNESS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "AI Strategy",
    "outline": "# AI Strategy\n\n## 1. Current State\n- Where we are today\n- Key metrics\n\n## 2. Roadmap\n- Q1 goals\n- Q2 goals",
    "n_slides": 8,
    "tone": "professional"
  }'
```

### Regenerate a presentation (new version)

```bash
curl -X PATCH http://thor.local:8090/presentation/{presentation_id} \
  -H "Authorization: Bearer $HARNESS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "n_slides": 12,
    "tone": "casual",
    "template": "creative"
  }'
```

This creates a new version (v2, v3, ...) linked to the original via `parent_id`.
Only the fields you send are changed; everything else is inherited from the parent.

### List all presentations

```bash
curl http://thor.local:8090/presentation/list \
  -H "Authorization: Bearer $HARNESS_API_KEY"
```

### Download a file

```bash
curl -O http://thor.local:8090/presentation/download/q4-review-v1.pptx \
  -H "Authorization: Bearer $HARNESS_API_KEY"
```

## Configuration

Set these environment variables (already configured in compose files):

| Variable | Value | Description |
|---|---|---|
| `PRESENTON_BASE_URL` | `http://presenton:80` | Presenton container URL |
| `PRESENTON_AUTH_USERNAME` | `presenton` | Presenton auth username |
| `PRESENTON_AUTH_PASSWORD` | `changeme123` | Presenton auth password |

## Storage

Generated files and metadata are stored in:

```
/data/media/presentations/
  ├── q4-review-v1.pptx
  ├── q4-review-v1.metadata.json
  ├── ai-strategy-v1.pptx
  ├── ai-strategy-v1.metadata.json
  └── ...
```

Each presentation gets a `{slug}-v{N}.{ext}` file alongside a `{slug}-v{N}.metadata.json`
with full metadata including Presenton ID, version, parent ID, creation date, etc.

## Versioning

When you generate a presentation with the same title multiple times, the version
auto-increments (v1, v2, v3, ...). You can also specify an explicit `version` or
`parent_id` to link versions explicitly.

## Network Exposure

Presenton is accessible **only on the internal home lab network** at `http://thor.local:5000`.
Download URLs use internal hostnames (`thor.local`) — they only work from within the
home lab network. All user-facing access flows through the ai-harness API which handles
authentication.

## Session Progress

| Session | Status | Description |
|---|---|---|
| 0 | ✅ Done | Presenton Docker infrastructure |
| 1 | ✅ Done | Harness module skeleton (schemas, service, router, prompts) |
| 2 | ✅ Done | Outline generation + research integration |
| 3 | ✅ Done | Celery tasks + Siri integration |
| 4 | ✅ Done | Versioning + persistence refinements |
| 5 | ⏳ Pending | OpenWebUI integration + testing |

See [plan.md](./plan.md) for the full implementation plan.

## See also

- [plan.md](./plan.md) — Session-by-session implementation plan
- [Presenton GitHub](https://github.com/presenton/presenton) — Upstream project
