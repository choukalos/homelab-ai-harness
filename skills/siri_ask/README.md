# Skill: siri_ask

Quick Q&A for Siri/iOS Shortcuts. Returns concise answers suitable for voice delivery or small screens.

## Purpose

Provide short, safe, fast answers to user questions through Siri or iOS Shortcuts. This skill is designed for:
- Quick factual questions
- Safe status lookups (read-only)
- Brief conversational follow-ups

It is **NOT** designed for:
- Deep research or multi-source fact-checking
- Administrative or write operations
- Long-running tasks

## Inputs

| Parameter | Type | Required | Description |
|---|---|---|---|
| `query` | string | Yes | The question or request to answer. |
| `context` | string | No | Optional previous conversation context for continuity. |

## Outputs

A short text answer (max ~500 tokens), optimized for spoken playback. Optionally, a log artifact is written to `/home/chuck/data/media/siri_outputs/`.

Response structure:
```json
{
  "answer": "Short response text...",
  "artifact_path": "/home/chuck/data/media/siri_outputs/siri_output_2026-07-03T14-22-00_weather.txt",
  "model_alias": "local/qwen-coder"
}
```

## Constraints

- **Max runtime:** 30 seconds (hard timeout enforced via signal).
- **Max output:** 500 tokens (truncated if exceeded).
- **No MCP tools:** Model chat only. No web search, no filesystem access, no database writes.
- **No admin writes:** Read-only by design.
- **Stateless:** No rollback needed.
- **No sensitive data:** Never exposes credentials, internal IPs, or private paths.

## Model

- **Model alias:** `local/qwen-coder` (Qwen 3.6 27B)
- **Temperature:** 0.3 (deterministic, concise)
- **System prompt:** Optimized for short, direct answers suitable for voice delivery.

## Channels

- **Siri** (primary entry point via iOS Shortcuts)
- Can also be triggered via the skill runner API: `POST /skills/siri_ask`

## Runtime Configuration

Environment variables (optional):

| Variable | Default | Description |
|---|---|---|
| `SIRI_ASK_MAX_RUNTIME` | `30` | Max runtime in seconds. |
| `SIRI_ASK_MAX_TOKENS` | `500` | Max output tokens. |
| `SIRI_ASK_MODEL_ALIAS` | `local/qwen-coder` | Model alias to use. |
| `ARTIFACT_DIR` | `/home/chuck/data/media/siri_outputs` | Directory for log artifacts. |
| `LITELLM_BASE_URL` | `http://localhost:4000` | LiteLLM endpoint URL. |
| `LITELLM_API_KEY` | `""` | LiteLLM API key (if required). |

## Artifact Logging

Each interaction is optionally logged as a `.txt` file:
```
siri_output_{timestamp}_{slug}.txt
```

Files are stored in `/home/chuck/data/media/siri_outputs/` and contain:
- The original query
- Any context provided
- Model alias used
- Timestamp
- The response text

## Usage via Skill Runner

```bash
curl -X POST http://localhost:8091/skills/siri_ask \
  -H "Content-Type: application/json" \
  -d '{
    "params": {
      "query": "What is the current status of the homelab?",
      "context": "User asked about server health earlier"
    },
    "requester": "chuck",
    "channel": "siri"
  }'
```

## Standalone Testing

```bash
cd skills/siri_ask
python skill.py --query "What's the weather?"
python skill.py --query "Status check" --dry-run
python skill.py --query "Latest news" --base-url http://localhost:4000 --api-key "sk-test"
```

## Rollback

None needed — the skill is stateless. Artifacts are optional log files that do not affect system state.

## See Also

- [Skill Architecture](../../docs/thor_skill_architecture.md) — Full skill design
- [Model Alias Registry](../../docs/thor_model_alias_registry.md) — Model alias definitions
- [Artifact Strategy](../../docs/thor_artifact_strategy.md) — Artifact storage rules
- [Skill Runner](../runner/) — Runner API and implementation
