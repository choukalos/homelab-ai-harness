# Morning brief — 2026-10-21 (memory write path, built overnight)

You asked (before bed): build items **#1 (pi `memory_remember` tool)** and
**#3 (household write path)**, and write the rest up in `memory_todo.md`.
Both are done, deployed, and verified live. Details below.

## What's new

### 1. pi can now WRITE to memory (the cross-machine gap, closed)
- New MCP tool **`memory_remember(text, importance?, household?)`** on
  `mcp_memory` (port 8005) → new skill-runner endpoint
  **`POST /api/memory/remember`**.
- Same identity threading as before: your pi on the Mac forwards your
  LiteLLM key → writes land under **your** scope. Dylan's key → his scope.
  Cross-user isolation is enforced server-side (tested: dylan cannot see
  or write your private facts, and vice versa).
- **No config change needed on the Mac** — same server, one more tool. pi
  picks it up on its next MCP connection (the tool description tells the
  model when to use it: durable personal info, health/medical, projects,
  "remember this").
- Extraction quality: the default mem0 prompt stored **0** facts from a
  3-sentence medical update in testing; the new dedicated remember prompt
  stored **3** (condition / doctor+clinic / appointment date). "Under-"
  extraction is the failure mode that matters for explicit remembers, so
  the prompt is assertive ("do not drop facts because they seem minor").

### 2. Household scope is real (family-shared memory)
- `memory_remember(..., household=true)` writes to the shared family
  bucket (which every user's reads already merge). Verified: a household
  fact written by chuck was searchable by **both** chuck and dylan
  (score 0.83 each).
- Rule of thumb: family matters (wife's medical status, kids, shared
  projects) → `household=true`; personal stuff → private (default).
- Provenance: household facts carry `written_by=<who wrote it>` metadata.

### 3. `memory_todo.md` (repo root) — the rest, so you don't forget
- **Research-outcome capture**: pi research-note convention (no code —
  just a skill/instruction now that remember exists) + optional
  `kb_medical` KB domain for reference-grade medical material (KB supports
  correct/forget; mem0 is add-only).
- **Dylan onboarding**: his pi/MCP config with his own key (the
  Authorization header matters — without it the server falls back to
  YOUR key), sweep GitHub identity mapping, first-use ritual.
- **Retrieval quality**: recency weighting for volatile topics (medical!),
  multi-query retrieval, provenance in answers, weekly review digest,
  importance-as-ranker.

## Verified (live, then cleaned up)
- Endpoint matrix: chuck private ✓, chuck household ✓, dylan private ✓,
  bad key → 403 ✓, empty text → 400 ✓.
- Isolation matrix: household visible to both users ✓; private facts
  invisible across users (both directions) ✓.
- MCP tool: registered + round-trip (remember → search back, 0.82) ✓.
- Both images rebuilt + recreated (`skill-runner:local`,
  `ai-mcp-mcp_memory`); health green; 0 401s.
- All 8 test facts admin-deleted; store = your 9 legitimate facts
  (4 old + 5 from yesterday's fixed sweep), dylan 0, household 0.

## Try it in the morning
1. On the Mac, ask pi: *"remember that my wife's next appointment is …"*
   — it should call `memory_remember` and confirm.
2. Ask it from the Mac: *"what do you know about my son?"* — it should
   `memory_search` and find it.
3. Family-shared test: have pi store something with `household=true`, then
   search for it later with Dylan's key.

## Notes
- Committed + pushed (see git log, `main`).
- State doc updated: `docs/memory/IMPLEMENTATION_STATE.md` (phase log,
  2026-10-21 3rd entry).
- One known nuance: extraction is LLM-based — occasionally `stored: 0`
  even for decent input (model variance). If it happens, rephrase or
  retry; the response says `stored: N` so you can see it.