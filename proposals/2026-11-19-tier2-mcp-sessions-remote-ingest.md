# `mcp_sessions` — remote session ingest + owner-scoped read-back (Phase 1)

- slug: tier2-mcp-sessions-remote-ingest
- date: 2026-11-19
- status: open
- tier: 2
- target user: chuck
- source: workspace/ideas/2026-11-16-mcp-sessions-ingest.md (full design; open question 1 resolved by this review)

## What
Phase 1 of the `mcp_sessions` proposal (thin MCP client over skill-runner scoped endpoints, following the `mcp_memory` pattern exactly):

1. **skill-runner: new route `GET /api/sessions/{session_id}`** — `X-Api-Key` auth, **owner-only** (IdentityResolver user must match the stored `user_id`), optional `line_start`/`line_end` query params; streams the `.jsonl` (or part files concatenated in part order) from `SESSIONS_ROOT`. Read-only; 0600 files never leave the volume. (Verified 2026-11-19: no transcript-body read route exists today — only `POST /api/sessions/ingest` + admin metadata-only `GET /api/sessions/{user_id}/ingests`.) Tests: auth, owner mismatch → 403/404, line-range slicing, part concatenation, admin key rejected.
2. **New MCP server `mcp/servers/sessions/`** (FastMCP, SSE, port 8000, `ai-net`) — the 13th server; identity threading copied from `mcp/servers/memory/server.py` (forwarded `Authorization` → `X-API-Key`; fallback `SESSIONS_USER_KEY` env for direct pi connections; the server **never** accepts a client-supplied `user_id`):
   - `sessions_ingest(transcript, session_id, host, started_at?, ended_at?)` — server-side split on line boundaries into ≤2 MiB parts reusing the existing `session_id.partN` convention and route (runner ingest path unchanged); hard cap 20 MiB → explicit error; rate limit ~30 ingests/user/hour (tunable env). Returns `{status: stored|duplicate, session_id, parts: [{part, sha256_prefix, bytes, line_range}], total_bytes}`.
   - `sessions_list(since?, limit?≤500)` — existing list route (metadata only, caller's ingests).
   - `sessions_get(session_id, line_start?, line_end?)` — body or line slice + citation header `{citation, session_id, part, line_range, sha256_prefix, bytes}`.
3. **Citation contract** (the jsonl analogue of the KB's `page_range`): `session:{user_id}/{session_id}#L{start}-L{end}` (single part) / `session:{user_id}/{session_id}#p{N}L{start}-L{end}` (multi-part). Per-part sha256 rows in `session_ingests` make citations verifiable. No new table in Phase 1.
4. **Compose + registration**: `mcp-sessions` service in `compose/compose.mcp.yml` (`ai-net`, env `SKILL_RUNNER_URL=http://skill-runner:8091`, `SESSIONS_USER_KEY`, caps); LiteLLM registration (`transport: sse`, `sub=mcp-sessions`); add to the `family-mcp-full` access group (Phase 2 default-deny is live — a new server is invisible to family keys until granted).
5. **`session-sync` skill remote mode**: if `mcp_sessions` tools are available (call routes through the LiteLLM proxy), call `sessions_ingest` with the verbatim transcript — no base64, no curl, no manual splitting, no 2 MiB bookkeeping. Keep the LAN curl path as fallback. Privacy notice unchanged (user-initiated only, private, no household flag).
6. **Docs**: `docs/thor_mcp_architecture.md` current-state line (13 servers, tool count), `mcp/README.md` table row.
7. **E2E verification from the Mac (the exact failure case)**: remote pi session calls `sessions_ingest` with a real transcript → `stored`; re-call → `duplicate`; `sessions_get` returns the cited line range; `harness_reflection` next weekly run sees it. Then sync the stranded 2026-11-16 transcript (`2026-11-16T21-16-06-464Z…`, 585 KB, on the Mac) as the first production use.

## Why (evidence)
- The 2026-11-16 failure is **still live** (verified 2026-11-19): a remote pi session cannot ingest its transcript — only `llm.choukalos.com` is reachable remotely, no MCP tool reaches `POST /api/sessions/ingest`, `mcp_filesystem` is confined to `/home/chuck/workspace`, and `session-sync` is still LAN-curl-only. The reflection pipeline (weekly cron, the harness-improvement loop) is starved of remote sessions.
- The 2 MiB cap is a transport limit, not a storage limit — and the split is client-side, so the agent does byte-accounting by hand.
- No read-back of ingested transcripts via any tool → nothing downstream can cite a stored session.

## Risk + rollback
Low. No new public surface (LiteLLM-only per the MCP rule); owner-only read-back (same posture as `memory_search`); admin key rejected (existing behavior); 20 MiB hard cap + per-user rate limit. Rollback = remove the service + LiteLLM registration + access-group grant.

## Files touched
- `skills/runner/main.py` (new route + tests), `skills/runner/sessions.py`
- `mcp/servers/sessions/` (new: `server.py`, `README.md`, tests)
- `compose/compose.mcp.yml`, `litellm/config.yml`
- `agents-skills/session-sync/SKILL.md`
- `docs/thor_mcp_architecture.md`, `mcp/README.md`

**Phase 2 (later, not in this proposal):** `sessions_search` (keyword, then per-user Qdrant collection `sessions_{user_id}` — never the family KB), `sessions_delete`, `session_parts` table if citation bookkeeping needs persistence, NAS reference-only server.

---
_Drafted 2026-11-19 (pi, thor) from the workspace/ideas review. Review with `cli/proposals.sh`; applying is a human decision._
