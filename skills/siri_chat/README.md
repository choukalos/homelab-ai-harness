# Skill: siri_chat

Conversational chat with MCP tool access. Uses web search, family knowledge base, and homelab status tools to provide informed, accurate answers.

## Purpose

Provide a full-featured chat experience that goes beyond plain Q&A. The model can autonomously call tools to gather information before answering:

- **Web search** — look up current facts, news, or anything beyond training data
- **Knowledge base search** — find stored notes, memories, and reference material
- **Knowledge base ask** — semantic question answering against stored content
- **Docker/homelab status** — check service health and container status

This skill is designed for:
- Siri/iOS Shortcuts
- API consumers (chat gateway)
- CLI testing

## Inputs

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | Yes | — | The user's question or request. |
| `context` | string | No | — | Optional previous conversation context for continuity. |
| `model` | string | No | `matrix-coder` | Model alias to use. |

## Outputs

```json
{
  "answer": "The response text...",
  "sources": ["search_web: query=...", "kb_search: query=..."],
  "model_alias": "matrix-coder"
}
```

- **answer**: The final response, optimised for voice/mobile (concise, plain language).
- **sources**: List of tools/sources consulted during the conversation.
- **model_alias**: The model alias used for this request.

## Tool Calling

The skill uses LiteLLM's native function calling to let the model decide which tools to use. The process:

1. The model receives the conversation + available tools.
2. If it decides to call a tool, it sends a `tool_calls` response.
3. The skill executes each requested tool via `litellm_client.mcp_call()`.
4. Tool results are fed back and the model generates a follow-up response.
5. This repeats up to **3 rounds** (configurable via `SIRI_CHAT_MAX_TOOL_ROUNDS`).
6. After the final round, the model produces the answer.

### Available Tools

| Tool | MCP Server | Description |
|---|---|---|
| `search_web` | `mcp_search` | Web search via SearXNG |
| `kb_search` | `mcp_knowledge` | Semantic vector search across the family KB (kb_* collections); optional `kb` to restrict to one KB |
| `docker_status` | `mcp_homelab_status` | Check Docker container status |

## Constraints

- **Max runtime:** 120 seconds (hard timeout via signal).
- **Max tool rounds:** 3 (stops tool calling and forces a final answer).
- **Read-only:** No writes, no admin operations.
- **No sensitive data:** Never exposes credentials, internal IPs, or private paths.
- **Stateless:** No rollback needed.
- **Voice-optimised:** Responses kept under 300 words by default.

## Model

- **Default model:** `matrix-coder`
- **System prompt:** Optimised for concise, plain-language answers suitable for voice delivery.
- **Temperature:** 0.3 (set by LiteLLM proxy configuration).

## Channels

- **Siri** (via iOS Shortcuts calling the skill runner API)
- **CLI** (via `run-skill.sh`)
- **API** (direct calls to `/skills/siri_chat` on the skill runner)

## Runtime Configuration

Environment variables (optional):

| Variable | Default | Description |
|---|---|---|
| `SIRI_CHAT_MAX_RUNTIME` | `120` | Max runtime in seconds. |
| `SIRI_CHAT_MAX_TOOL_ROUNDS` | `3` | Max tool-calling rounds before forcing final answer. |
| `SIRI_CHAT_MODEL_ALIAS` | `matrix-coder` | Model alias to use. |
| `ARTIFACT_DIR` | `/home/chuck/data/media/siri_outputs` | Directory for log artifacts. |
| `LITELLM_BASE_URL` | `http://localhost:4000` | LiteLLM endpoint URL. |
| `LITELLM_API_KEY` | `""` | LiteLLM API key (if required). |
| `MCP_SERVER_SEARCH_URL` | `http://mcp_search:8000` | MCP search server URL. |
| `MCP_SERVER_KNOWLEDGE_URL` | `http://mcp_knowledge:8000` | MCP knowledge server URL. |
| `MCP_SERVER_HOMELAB_STATUS_URL` | `http://mcp_homelab_status:8000` | MCP homelab status server URL. |

## Usage via Skill Runner

```bash
curl -X POST http://localhost:8091/skills/siri_chat \
  -H "Content-Type: application/json" \
  -d '{
    "params": {
      "query": "What is the status of my homelab services?",
      "context": "User asked about server health earlier",
      "model": "matrix-coder"
    },
    "requester": "chuck",
    "channel": "siri"
  }'
```

## Standalone Testing

```bash
cd skills/siri_chat

# Dry run (no LiteLLM needed)
python skill.py --query "What's the weather?" --dry-run

# Full run with mock client
python skill.py --query "Status check"

# With context and specific model
python skill.py --query "Docker status" --context "User is Chuck" --model matrix-coder
```

## Rollback

None needed — the skill is stateless. It only reads from MCP servers and does not modify any persistent state.

## See Also

- [Skill Architecture](../../docs/thor_skill_architecture.md) — Full skill design
- [Model Alias Registry](../../docs/thor_model_alias_registry.md) — Model alias definitions
- [siri_ask](../siri_ask/) — Simpler chat skill (no tool access)
- [deep_research](../deep_research/) — Multi-source research with artifacts
- [Skill Runner](../runner/) — Runner API and implementation