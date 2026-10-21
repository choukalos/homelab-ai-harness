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

**Done 2026-10-21 (retrieval-quality phases):** 3a–3e all CODE DONE,
deployed (skill-runner:local rebuilt + recreated), and live A/B verified —
`MEMORY_MULTIQUERY=true` now on in `.env`. See IMPLEMENTATION_STATE.md
phase log (5th–8th entries). Cold-start degradation now flagged in the
search response (`degraded`/`degraded_reason`/`retry`) so clients can
retry once instead of concluding "no memories".

**Done 2026-10-21 (1b + 2b):** `kb_medical` KB domain verified live
(created on the fly, searched, two-step forget, test fact cleaned up);
Dylan's GitHub identity wired into the recent_activity sweep.

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
  ✅ DONE + VERIFIED 2026-10-21 — `kb_medical` collection exists (created
  on the fly via `kb_add_fact(kb="medical", description=...)` with a
  persistent manifest description). Live-verified end-to-end in
  `mcp_knowledge`: add → search (score 0.88) → two-step `kb_forget`
  (candidates → confirmed delete) → clean. Convention lives in
  `agents-skills/memory-conventions/SKILL.md`: medical reference-grade
  material (diagnosis, symptoms, treatment, vet, next appointment) →
  `kb_medical` (evolving, correctable via kb_correct/kb_forget);
  conversational durable facts → `mcp_memory`. Both stores searchable
  from pi (mcp_knowledge + mcp_memory).

## 2. Dylan onboarding (trivial once he's ready)

- **2a. His pi/MCP config.** `mcp_memory` is LAN-published on
  `thor:8005` (SSE). His pi config should connect with HIS key:
  `Authorization: Bearer <LITELLM_KEY_DYLAN>` (from `.env`, don't commit).
  Without a forwarded Authorization, the server falls back to
  `MEMORY_USER_KEY` (chuck's key) — so the header matters. Same key works
  for the Siri chat surface (`/api/chat`) — his identity is already mapped
  (`MEMORY_USER_KEYS=dylan=LITELLM_KEY_DYLAN`).
- **2b. Sweep GitHub identity (if he has GitHub).** ✅ DONE 2026-10-21 —
  `GITHUB_USERS` in `skills/recent_activity/skill.py` now maps
  `"dylan": os.environ.get("GITHUB_USER_DYLAN", "")`; `GITHUB_USER_DYLAN=`
  added to `.env` (empty — his repo activity is skipped until his login
  is set; the sweep already skips empty logins).
- **2c. First-use ritual.** First thing he says: "remember this: ..." —
  his memory starts accumulating immediately (private scope; household
  facts from chuck are already visible to him).

## 3. Retrieval quality (medium — do when it feels needed)

**DEPLOYED + LIVE A/B VERIFIED 2026-10-21** (skill-runner:local rebuilt
+ recreated; `MEMORY_MULTIQUERY=true` in `.env`; see phase log 5th–8th
entries). Cold-start degradation now flagged in the search response
(`degraded`/`degraded_reason`/`retry` — retry once when true).

- **3a. Recency weighting for volatile topics.** ✅ DONE + DEPLOYED 2026-10-21 —
  `rank_score = raw × recency × importance` in `search_memory`; recency
  `1 + (max−1)·0.5^(age/halflife)` on `updated_at`/`created_at`
  (`MEMORY_RECENCY_BOOST_MAX=1.2`, `MEMORY_RECENCY_HALF_LIFE_DAYS=30`).
  Threshold gate stays on the RAW score. Live A/B: fresh fact raw=0.545
  ranks just under stale raw=0.619 (boost closing the gap).
- **3b. Multi-query retrieval.** ✅ DONE + DEPLOYED + ON 2026-10-21 (Phase 2) —
  heuristic subqueries (quoted phrases + capitalized entities, no LLM)
  searched in parallel with the original, merged with reciprocal rank
  fusion (`MEMORY_MULTIQUERY=true`; `MEMORY_MULTIQUERY_MAX=3`).
  Per-query raw-score gating preserved. Live A/B: subquery derived,
  RRF scores present, no ranking regression vs off.
- **3c. Provenance in answers.** ✅ DONE + DEPLOYED 2026-10-21 — context block
  bullets carry `[YYYY-MM-DD · source]` + preamble instructs date citation;
  `/api/memory/search` already returned dates (MCP/pi surfaces covered).
  Live A/B: `[2026-10-21 · scheduled]` bullets confirmed in the block.
- **3d. Weekly memory review digest (trust + pruning).** ✅ DONE + DEPLOYED
  2026-10-21 (Phase 3) — new `memory_review` skill: identity-safe per-user
  digest of new/updated private + household memories (ID + date + source
  + importance) with a correction/deletion footer; private artifact;
  scheduled Sun 18:00 CT (`weekly-memory-review`); pi wrapper
  `agents-skills/memory-review`. Live run: 5/9 facts in the 7d window
  (4 stale correctly excluded), artifact on disk.
- **3e. `importance` as a ranker.** ✅ DONE + DEPLOYED 2026-10-21 — flat
  `MEMORY_IMPORTANCE_BOOST=1.15` for `importance=high` in `rank_score`
  (same change as 3a).

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