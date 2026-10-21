# Memory TODO — remaining improvements (2026-10-21)

Context: Phase 12 (pi write path + household scope) is DONE — `memory_remember`
MCP tool + `POST /api/memory/remember` endpoint + household bucket writes.
These are the remaining items from the 2026-10-21 memory-improvement plan
(see `docs/memory/IMPLEMENTATION_STATE.md`, phase log 2026-10-21 entries).

**Done 2026-10-21 (post-Phase 12):** 1a + 4 — `agents-skills/memory-conventions/
SKILL.md` (pi-native instruction skill: memory_search/remember conventions,
research-note convention, medical KB split). Distributed via the existing
`agents-skills/` path — `git pull` + pi restart/`/reload` on each client,
no install step.

## 1. Research-outcome capture (from pi sessions)

When research is done IN PI (e.g. wife's medical condition), the outcome
lives only in the session — nothing lands in memory. Two parts:

- **1a. Research-note convention (no code needed).** ✅ DONE 2026-10-21 —
  lives in `agents-skills/memory-conventions/SKILL.md` (research-note
  section; structured note at `importance='high'`, `household=true` for
  family-relevant research). Note: the skill was distributed via the repo's
  `agents-skills/` dir (already in pi's settings) instead of a per-machine
  `~/.pi/agent/skills/` copy — version-controlled, one source of truth.
- **1b. `kb_medical` KB domain for reference-grade material (small).**
  mem0 is add-only (changes become new supersede statements); the KB
  (`mcp_knowledge`) supports `kb_correct`/`kb_forget` — better for
  evolving reference material like a medical condition (diagnosis,
  symptoms, treatment, vet, next appointment). Create a `kb_medical`
  collection (kb_add_fact creates collections on the fly — just use
  `kb="medical"`), and a pi convention: medical reference → KB,
  conversational facts → memory. Both stores are already searchable from
  pi (mcp_knowledge + mcp_memory).

## 2. Dylan onboarding (trivial once he's ready)

- **2a. His pi/MCP config.** `mcp_memory` is LAN-published on
  `thor:8005` (SSE). His pi config should connect with HIS key:
  `Authorization: Bearer <LITELLM_KEY_DYLAN>` (from `.env`, don't commit).
  Without a forwarded Authorization, the server falls back to
  `MEMORY_USER_KEY` (chuck's key) — so the header matters. Same key works
  for the Siri chat surface (`/api/chat`) — his identity is already mapped
  (`MEMORY_USER_KEYS=dylan=LITELLM_KEY_DYLAN`).
- **2b. Sweep GitHub identity (if he has GitHub).** The sweep only scans
  users in `GITHUB_USERS` (`skills/recent_activity/skill.py`, line ~51):
  add `"dylan": os.environ.get("GITHUB_USER_DYLAN", "")` (and set
  `GITHUB_USER_DYLAN` in `.env`) so his repo activity feeds his sweep.
- **2c. First-use ritual.** First thing he says: "remember this: ..." —
  his memory starts accumulating immediately (private scope; household
  facts from chuck are already visible to him).

## 3. Retrieval quality (medium — do when it feels needed)

- **3a. Recency weighting for volatile topics.** A 3-month-old medical
  fact ranks the same as last week's. Option: in `/api/memory/search`,
  boost hits by recency of `updated_at`/`created_at` (e.g. score × 1.0–1.2
  decay), or a `recent_first=true` mode. Timestamps are now carried
  through `_normalize_hit` (2026-10-21 fix) so this is straightforward.
- **3b. Multi-query retrieval.** Chat retrieval does a single query;
  deriving 2–3 subqueries (question + named entities) would catch facts
  phrased differently.
- **3c. Provenance in answers.** Surface `source` + `created_at` in
  retrieved facts ("per your chat on 2026-09-02…") so the user can trust
  and correct.
- **3d. Weekly memory review digest (trust + pruning).** A scheduled skill
  ("here's what I've stored about you this week — correct or delete
  anything wrong") using `list_memories` + admin delete. Good for
  catching extraction errors before they compound.
- **3e. `importance` as a ranker.** Currently provenance-only; weight
  `importance=high` hits in search (e.g. ×1.15). Small change in the
  search endpoint.

## 4. Optional: pi memory-conventions skill — ✅ DONE 2026-10-21

Built as `agents-skills/memory-conventions/SKILL.md` (repo, not Mac-local):
when to call `memory_search` (start of conversations about known topics),
when to call `memory_remember` (durable personal info / "remember this"),
the research-note convention (1a), the medical KB convention (1b), the
memory/KB store split, and provenance in cited answers. The MCP tool
descriptions already carry the core guidance — the skill adds the
research/KB conventions. Distribution: `git pull` + pi restart (or
`/reload`) on each client; Dylan's machine gets it via the same clone
(part of 2a).

## Housekeeping

- `.env` is gitignored — never commit it.
- `memory/` package is BAKED into the `skill-runner:local` image
  (`COPY memory/`): interface changes need `docker build -t
  skill-runner:local skills/runner` + recreate. `mcp_memory` is baked too
  (`docker compose -f compose.mcp.yml build mcp_memory`).
- Compose commands from `compose/` always use `--env-file ../.env`.
- Test pollution: after any live test of remember/search, admin-delete the
  test facts (`GET /api/memory/users/{user}` + `DELETE
  /api/memory/{id}` with `MEMORY_ADMIN_API_KEY`).