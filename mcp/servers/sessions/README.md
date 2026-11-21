# mcp_sessions — session transcript ingest + owner-scoped read-back

Phase 1 of the `mcp_sessions` proposal
(`proposals/2026-11-19-tier2-mcp-sessions-remote-ingest.md`, applied
2026-11-21). Thin MCP client over skill-runner's scoped session endpoints —
the 13th MCP server (SSE, port 8000, `ai-net`).

## Why

A remote pi session (e.g. on the Mac, where only `llm.choukalos.com` is
reachable) could not ingest its transcript: the `session-sync` skill was
LAN-curl-only, and the 2 MiB transport cap forced the agent to do manual
byte-accounting and splitting. This server makes ingest a single tool call
with the verbatim transcript (server-side split), and adds owner-scoped
read-back so downstream work can cite a stored session.

## Tools

| Tool | Route | Notes |
|---|---|---|
| `sessions_ingest(transcript, session_id, host, started_at?, ended_at?)` | `POST /api/sessions/ingest` | Server-side split on line boundaries into ≤2 MiB parts (`session_id.partN` convention); 20 MiB hard cap → explicit error; rate limit ~30 calls/user/hour (`SESSIONS_RATE_LIMIT`); idempotent (`duplicate`) |
| `sessions_list(since?, limit?≤500)` | `GET /api/sessions/ingests` | Metadata only, caller's ingests, newest first |
| `sessions_get(session_id, line_start?, line_end?)` | `GET /api/sessions/{session_id}` | Owner-only read-back (or 1-based inclusive line slice of the concatenated part stream) + citation header |

**Citation contract** (the jsonl analogue of the KB's `page_range`):
`session:{user_id}/{session_id}#L{start}-L{end}` (single file) /
`session:{user_id}/{session_id}#p{N}L{start}-L{end}` (split — `N` is the
part holding the first returned line; line numbers are over the
concatenated stream). `sha256_prefix` (first 16 hex chars of that part
file's sha256) makes citations verifiable against the `session_ingests`
index row.

## Identity

Same pattern as `mcp_memory`: the caller's LiteLLM key (forwarded via the
`Authorization` header when the call routes through LiteLLM — the
`mcp_servers` entry sets `extra_headers: [Authorization]`) is passed to
skill-runner as `X-API-Key`. When absent (pi connecting directly), the
configured `SESSIONS_USER_KEY` is used — a SINGLE key in skill-runner's
`SKILL_RUNNER_API_KEY` allow-list (exact-match semantics). The server
**never** accepts a client-supplied `user_id`; cross-user isolation is
enforced server-side by skill-runner's IdentityResolver (owner-only
read-back, admin key rejected on both routes).

## Env

| Var | Default | Purpose |
|---|---|---|
| `SKILL_RUNNER_URL` | `http://skill-runner:8091` | backend base URL |
| `SESSIONS_USER_KEY` | — | fallback identity (direct pi connections) |
| `SESSIONS_TIMEOUT_S` | `30` | default HTTP timeout |
| `SESSIONS_INGEST_TIMEOUT_S` | `120` | ingest POST timeout (2 MiB parts) |
| `SESSIONS_RATE_LIMIT` | `30` | max ingest calls per caller key per rolling hour |

## Tests

`tests/test_splitter.py` — pure unit tests of the split logic (no
mcp/httpx needed): `python3 tests/test_splitter.py`.
