# Homelab Long-Term Memory — Implementation Plan

> Source: `homelab_AI_Long_Term_Memory_Final_Recommendation.pdf` (Aug 24, 2026)
> This file is the executable version of that PDF for **this** homelab. Phase 0
> (inventory) was completed live on 2026-08-24 and is recorded in Appendix A.
> Working-state file for the implementing model: `docs/memory/IMPLEMENTATION_STATE.md`
> (create in Phase 0; keep < ~5K tokens; update at the end of every phase).

---

## 0. Decisions (answered by Chuck, 2026-08-25)

1. **v1 user scope** — **chuck only.** Phase 3 builds the key→user mapping so
   adding `son` later is a one-line change (new key + map entry), but v1
   creates/tests only `chuck` (+ `household` scope + `service` for jobs).
2. **Channel scope** — **skill-runner channels only** (Siri, `/api/chat`, CLI,
   scheduler jobs). Open WebUI is being deprecated → OWUI memory is **out of
   scope entirely**. This confirms the in-process (zero new container) choice.
3. **Backup** — **git for config/code (existing workflow) + `.env` copied to a
   separate backup dir + a small Qdrant snapshot of the memory collection.**
   Rationale: git already tracks compose/Caddyfile/LiteLLM config/skills/MCP
   code (`.env` is gitignored, `data/` untracked). Git cannot cover Qdrant's
   *data* (the actual memories) or `.env` secrets — so the only new backup
   machinery is: (a) copy `.env` to `/home/chuck/data/backups/`, (b) Qdrant
   snapshot API call + copy for `mem0_memories`. No full pg_dumpall/cron
   infrastructure in v1; run the snapshot at each phase gate (cheap, ~10s).
4. **Extraction LLM** — **`matrix-coder`** (qwen38-27b via vLLM). No A/B test
   against gemma4-moe; Phase 1 runs a single structured-output sanity probe.
5. **Qdrant host port** — **leave `0.0.0.0:6333` as-is** for v1. Family KB is
   the future user; note it in Phase 9 hardening, don't change it now.

---

## 1. PDF vs. reality — comprehension check

### 1.1 What the PDF got right (verified live 2026-08-24)

| PDF assumption | Verified |
|---|---|
| Docker-first, LiteLLM-based AI lab on Thor (192.168.4.54) | ✅ All AI services in Docker on `ai-net` |
| Local Qwen 3.8 27B, ~128K context | ✅ `matrix-coder` = `openai/qwen38-27b` via vLLM at `matrix:8000` |
| nomic-embed-text behind LiteLLM | ✅ alias `embeddings` = `ollama/nomic-embed-text` via `matrix:11434`; **live test returned 768-dim vector** |
| Family knowledge base with vector storage | ✅ Qdrant (`qdrant/qdrant:latest`, data `/home/chuck/data/qdrant`), collection `family_kb` (18 points) |
| Siri/shortcut entry points | ✅ `siri.choukalos.com` → Caddy (`X-API-Key: $SIRI_API_KEY`) → `skill-runner:8091` |
| Skills / agent runner | ✅ `skill-runner` (FastAPI, port 8091): unified `/api/chat` gateway, 13 skills, scheduler, MCP dispatch |
| MCP layer present | ✅ 8 MCP servers on `ai-net` (`mcp_search`, `mcp_knowledge`, `mcp_crawl`, `mcp_filesystem`, `mcp_filesystem_readonly`, `mcp_mysql`, `mcp_homelab_status`, `mcp_media`), all registered in LiteLLM config |
| Reverse proxy + tunnel | ✅ Caddy + Cloudflare tunnel (`edge-net`) |
| Postgres present | ✅ `litellm-db` (postgres:16-alpine) — but it is LiteLLM's metadata DB, not an app DB (see D1) |
| Goal: stable per-person identity, household scope, no secrets in memory, graceful degradation, MCP optional | ✅ Adopted as-is (Section 7 non-negotiables) |

### 1.2 Deltas — where the PDF's assumptions don't match this homelab

**D1 — Vector storage is Qdrant, not Postgres+pgvector.**
There is no "app Postgres" to extend: `litellm-db` is LiteLLM's metadata DB and
`plausible-db` belongs to Plausible. The actual vector store is **Qdrant**.
Per the PDF's own decision tree (inspect the KB's vector store first; if Mem0
supports it, use a separate collection there), the correct choice is:
**reuse Qdrant with a dedicated memory collection. No pgvector work, no new Postgres.**

**D2 — No per-user LiteLLM keys exist.**
LiteLLM DB has a single `default_user_id`, no teams, and 4 unnamed verification
tokens (master/public/service). Per-key hardening is explicitly "Deferred
Indefinitely" in `TODO.md`. The PDF's "existing separate LiteLLM keys" is a plan,
not a fact. Identity mapping is greenfield — but note `skill-runner` already
accepts a **comma-separated list** of `SIRI_API_KEY`s, which is the natural hook
for a key→user map (see Phase 3).

**D3 — No backup mechanism exists.**
`docs/thor_integration_readiness.md`: "Backup exists — ⚠️ NOT DONE. Chuck must
execute a real backup before further changes." The PDF's "reuse existing backup
jobs" (Phase 8) must become **create** the backup mechanism. This is a Phase 1
prerequisite, not a Phase 8 item.

**D4 — Family is larger than chuck + son.**
`docs/thor_channels_architecture.md` lists Chuck, wife, daughter, son as users
(OWUI, portal, llm.choukalos.com). v1 is scoped to **chuck only** (decision
§0.1), but the identity design must be extensible — no hardcoded user logic.

**D5 — Open WebUI does NOT go through the normalized gateway.**
OWUI calls LiteLLM directly with the master key; its MCP tool registration is
still a pending user action (`TODO.md` "Frontier Integration Plan"). So the PDF's
Decision 1 ("is there ONE normalized gateway all entry points use?") is YES for
Siri/CLI/jobs (skill-runner) but NO for OWUI. Consequence: v1 memory covers
skill-runner channels; OWUI is out of scope (decision §0.2).

**D6 — Knowledge-base quirks (context, not blockers).**
- `mcp_knowledge` allowlists `family_curated`/`homelab_curated`/`coding_curated`,
  but the only real Qdrant collection is `family_kb` → `kb_search` currently finds
  nothing. Separate workstream.
- `kb_search` does exact-match `scroll`, not vector search. Separate workstream.
- `family_kb` is **384-dim** while the current LiteLLM `embeddings` alias returns
  **768-dim** → the KB was embedded by the decommissioned legacy harness. Never
  mix collections; the memory collection uses 768 (verified live).
- `family_kb_ingest` skill still POSTs to the decommissioned harness's
  `/knowledge/ingest` — currently broken. Separate workstream.

**D7 — Embedding alias is `embeddings`, not `homelab-embedding-v1`.**
Keep `embeddings` for the KB path; add a versioned alias `homelab-embedding-v1`
(maps to the same nomic backend) for memory so future re-embedding migrations can
cut over cleanly (PDF §4).

**D8 — LiteLLM image is unpinned** (`ghcr.io/berriai/litellm:main-latest`).
Phase 9 hardening should pin it (config header mentions 1.92.0 as the tested line).

**D9 — Qdrant port 6333 published on 0.0.0.0** — decision §0.5: leave as-is for v1; revisit with the family KB work.

**D10 — Scheduler/jobs have no identity.** `dispatch_job()` hardcodes
`requester="siri"`. PDF Phase 3 requires a service identity so jobs don't pollute
personal memory.

---

## 2. Resolved architecture (Phase 0 delta design)

Per the PDF's deployment decision tree, applied to the verified inventory:

- **Memory engine:** Mem0 OSS as a **Python library in-process inside
  `skill-runner`** → **zero new containers** (PDF "best case" path). The
  skill-runner is the normalized gateway for all v1 channels (D5).
- **Storage:** existing **Qdrant**, new dedicated collection **`mem0_memories`**
  (768-dim, Cosine — dimension confirmed live; never hardcode, re-verify in Phase 1).
  No pgvector, no new Postgres, no new vector DB (D1).
- **Embeddings:** LiteLLM only. New logical alias **`homelab-embedding-v1`**
  → `ollama/nomic-embed-text` (same backend as `embeddings`). Mem0's
  OpenAI-compatible embedder points at `http://litellm-proxy:4000/v1`.
- **Extraction LLM:** via LiteLLM, **`matrix-coder`** (qwen38-27b; decision
  §0.4 — single structured-output sanity probe in Phase 1, no A/B test).
- **Identity:** key→user map inside skill-runner (no LiteLLM core changes, per
  PDF §3). Stable user_ids: `chuck` (v1), `son` (later — one-line change); scope
  `household`; service id `service` for scheduler jobs. No raw keys in
  config/logs/memory (D2, D4, D10).
- **MCP memory tools:** deferred to Phase 6 (PDF: MCP is an enhancement, not a
  dependency).
- **OWUI:** out of scope (decision §0.2 — being deprecated). OWUI's built-in
  chat history/chroma store is unrelated to this work.

### Target request flow (v1)

```
iOS Shortcut / CLI / OWUI-harness / scheduler
        |  X-API-Key (siri.choukalos.com via Caddy, or :8091 on ai-net)
        v
skill-runner (FastAPI :8091)
  ├─ identity resolver: X-API-Key -> user_id (chuck|son|service)
  ├─ run_id = uuid4
  ├─ MEMORY middleware: Mem0.search (user + household), top_k=6, budget 500-1500 tok
  ├─ prompt build: system policy + <long_term_memory> block + task
  ├─ execute: /api/chat intent dispatch -> LiteLLM (matrix-coder / matrix-gemma4-moe)
  │           + MCP tools (existing 8 servers) + skills
  └─ post-turn: sanitize -> Mem0.learn (writeback, non-fatal)
        |
        v
Qdrant collection `mem0_memories` (768-dim)  +  LiteLLM (embeddings + chat)
```

---

## 3. Phased implementation

> Method (from PDF §9/§11): one phase at a time; start each phase from
> `docs/memory/IMPLEMENTATION_STATE.md` + only the files that phase touches;
> end each phase with tests + delta summary + updated state file. Stop a phase if
> a required assumption is disproved — fix the delta design, don't force it.
> All `MEMORY_*` env vars go in `homelab/.env` (gitignored); no secrets in Git.

### 3.0 Operational constraint — container lifecycle is MANUAL (read first)

**Why:** the implementing model's own session runs through
`skill-runner` → `litellm-proxy`, and skill-runner holds a persistent pooled
HTTP client to litellm (`LiteLLMClient`, `main.py` ~391). Recreating or
restarting either container breaks the session. All container lifecycle
operations are therefore **manual steps performed by Chuck between model
turns** — the implementing model never runs them.

**Model rules**
1. **Never** run container lifecycle commands against running containers:
   no `docker (compose) up|down|restart|recreate|rm`, no `docker pull`,
   no `./homelab.sh up|down|restart|rebuild|pull` for any stack.
2. **Allowed docker usage (read-only / throwaway only):**
   - `docker ps`, `docker inspect`, `docker logs --tail N <ctr>`
   - `docker exec <ctr> <read-only cmd>` (e.g. `pg_isready`)
   - `docker run --rm` **throwaway** containers (Phase 1 restore test, Mem0
     round-trip): no published ports, or only non-clashing ports (e.g. 16333);
     never 4000/8091/6333/3000.
3. **Manual-step protocol** (every phase that touches a container):
   a. Model prepares all file changes → `git commit`.
   b. Model runs `scripts/backup-memory.sh`.
   c. Model **stops** and prints the manual-step block (command, expected
      duration, post-checks, rollback) and waits for Chuck.
   d. Chuck runs the command **while the model is idle** (after the model's
      turn ends; no request in flight).
   e. Model verifies with the read-only post-checks below, records the result
      in the state file, and continues.

**Manual steps (exact commands, verified against `homelab.sh`)**

| Step | Trigger | Command | What restarts |
|---|---|---|---|
| **A** | `litellm/config.yml` changed (Ph 1, 6, 9) | `docker restart litellm-proxy` | litellm-proxy only |
| **B** | skill-runner code/env/image changed (Ph 2–5, 7, 8, 9) | `./homelab.sh rebuild skill-only` | skill-runner only — **litellm stays up** (separate compose project; see `homelab.sh` notes) |
| **C** | new MCP server container (Ph 6) | `./homelab.sh up mcp-only` | MCP stack only |
| **D** | image pinning litellm/qdrant (Ph 9) | `./homelab.sh rebuild ai-only` | all ai-core (litellm, qdrant, owui, redis, searxng, crawl4ai, family-wiki, presenton) |

**Post-checks after any manual step (model runs these — read-only):**

```
curl -s http://localhost:4000/health/liveliness   # litellm: {"status":"alive"}
curl -s http://192.168.4.54:8091/health           # skill-runner (port bound to THOR_IP, NOT localhost)
docker ps                                          # all expected containers up, no restart loops
docker logs --tail 50 litellm-proxy                # no startup errors (after A/D)
docker logs --tail 50 skill-runner                 # no startup errors (after B)
```

**Known caveat after manual step A:** skill-runner's pooled HTTP client may
hold a stale keep-alive socket to the restarted litellm, so the model's first
LLM turn after the restart can fail once. If it does, re-send the prompt —
the second attempt uses a fresh connection.

**Rollback (only if a post-check fails — model prepares, Chuck runs):**
- litellm config: `git checkout <last-good-commit> -- litellm/config.yml` →
  manual step A.
- skill-runner: `git checkout <last-good-commit>` → manual step B.
- If a restart leaves a service unhealthy, **stop and report** — do not chain
  further lifecycle commands to "fix" it.

### Phase 0 — Inventory & delta design ✅ (done 2026-08-24)

- [x] Inventory performed (Appendix A): containers, networks, LiteLLM aliases,
      embedding dimension (768), Qdrant collections, key inventory, auth paths,
      KB architecture, backup status.
- [x] Delta design: §1.2 + §2 above.
- [x] **Created `docs/memory/IMPLEMENTATION_STATE.md`** (2026-08-25), seeded with
      §1.2, §2, and the Appendix A facts (no secret values).
- [x] Decisions Q1–Q5 answered by Chuck (see §0).

**Gate to Phase 1:** decisions in §0 locked; state file exists.

### Phase 1 — Backup + storage & LiteLLM proof (no request-path changes)

1. **Lightweight backup** (per decision §0.3) — prerequisite for everything:
   - Create `/home/chuck/data/backups/` (outside git, outside the repo).
   - `scripts/backup-memory.sh`: (a) copy `homelab/.env` →
     `/home/chuck/data/backups/env-YYYYmmdd-HHMM.env` (chmod 600), (b) Qdrant
     snapshot of `mem0_memories` via
     `curl -X POST http://localhost:6333/collections/mem0_memories/snapshots`
     then copy the snapshot file into `/home/chuck/data/backups/`, (c) `git
     commit`/verify the working tree is clean (config/code backup = git).
   - Run it **before any storage change** and at every phase gate. No cron in
     v1 (manual, ~10s). Test a restore with a **throwaway** Qdrant container on
     a non-clashing port (allowed per §3.0 — no running service touched):
     `docker run --rm -d --name qdrant-restore-test -p 16333:6333 qdrant/qdrant:latest`,
     restore the snapshot via `http://localhost:16333`, search the
     `memory_test` facts, then `docker rm -f qdrant-restore-test`.
2. **Embedding proof** (already partially done — re-verify in the implementing
   phase):
   a. Add the `homelab-embedding-v1` alias to `litellm/config.yml` (→
      `ollama/nomic-embed-text`, same backend as `embeddings`); commit; run
      `scripts/backup-memory.sh`.
   b. **MANUAL STEP A (Chuck):** `docker restart litellm-proxy` (see §3.0).
   c. Then call `POST http://litellm-proxy:4000/v1/embeddings` with model
      `embeddings` and with `homelab-embedding-v1`; record HTTP status,
      resolved alias, **vector length** (expected 768), latency. Do NOT record
      the vector itself.
3. **Extraction LLM probe:** single structured-output sanity test through
   LiteLLM with `matrix-coder` (decision §0.4): give a 3-turn sample
   conversation, ask for JSON durable-facts; confirm reliable structured output.
   Set `MEMORY_EXTRACTION_MODEL=matrix-coder`.
4. **Qdrant memory collection:** create `mem0_memories` (768-dim, Cosine) via
   Qdrant API; prove create/search/delete with a disposable `memory_test` user.
   Run the Mem0 round-trip in a **throwaway container** (allowed per §3.0 — no
   running service touched, no port clash):
   `docker run --rm --network ai-net -v /tmp/memtest:/work python:3.12-slim \
    bash -c "pip install -q mem0ai && python /work/roundtrip.py"`
   (script uses `http://qdrant:6333` + `http://litellm-proxy:4000`).
   Verify `family_kb` is untouched.
5. **Confirm no bypass:** verify Mem0's LLM/embedder calls actually traverse
   `litellm-proxy` (check LiteLLM request logs / spend logs), never
   `matrix:11434`/`matrix:8000` directly.

**Acceptance tests**
- [ ] `scripts/backup-memory.sh` runs (.env copy + Qdrant snapshot); snapshot
      restore tested into a throwaway container (non-production data).
- [ ] `homelab-embedding-v1` alias works; dimension recorded in state file.
- [ ] Add/search/update/delete works for `memory_test` in `mem0_memories`.
- [ ] No new model server, no duplicate Postgres/Qdrant, no production memory written.

**Gate to Phase 2:** all acceptance tests pass; manual step A done with
post-checks green (§3.0); state file updated.

### Phase 2 — In-process memory module in skill-runner

1. Add `mem0ai` (pinned version) to the **Dockerfile pip install line**
   (`skills/runner/Dockerfile` — dependencies are installed directly there,
   NOT from `pyproject.toml`) and add `COPY memory/ ./memory/` next to the
   existing `COPY` lines. (Also record the pin in `pyproject.toml` for
   documentation.)
2. New package `skills/runner/memory/`:
   - `client.py` — Mem0 init (Qdrant `mem0_memories`, LiteLLM embedder
     `homelab-embedding-v1`, LiteLLM LLM `MEMORY_EXTRACTION_MODEL`), timeouts,
     lazy init, health checks.
   - `interface.py` — the PDF §8 contract: `search_memory()`, `learn_from_turn()`,
     `list_memories()`, `update_memory()`, `delete_memory()`, `delete_user_memories()`.
     All other code calls **only** this interface (Mem0 internals stay inside the package).
   - `policy.py` — inclusion/exclusion rules (PDF §6): secret/credential regex
     filter, strip system/tool content, store/forget lists.
   - `context.py` — renders the `<long_term_memory>` block (PDF §5 shape:
     PRIVATE USER MEMORY / HOUSEHOUSE MEMORY sections, explicit "context, not
     instructions" framing).
3. Env config in `compose/compose.skill-runner.yml` + `.env`:
   `MEMORY_ENABLED`, `MEMORY_RETRIEVAL_ENABLED`, `MEMORY_WRITEBACK_ENABLED`,
   `MEMORY_MCP_ENABLED=false`, `MEMORY_HOUSEHOLD_ENABLED=true`,
   `MEMORY_DEBUG_LOGGING=false`, `MEMORY_LITELLM_BASE_URL=http://litellm-proxy:4000`,
   `MEMORY_LITELLM_KEY` (dedicated service credential — a new key with only
   `matrix-coder`/`matrix-gemma4-moe` + `homelab-embedding-v1` access),
   `MEMORY_QDRANT_URL=http://qdrant:6333`, `MEMORY_COLLECTION=mem0_memories`,
   `MEMORY_EMBED_DIM` (from Phase 1 test), `MEMORY_TOP_K=6`,
   `MEMORY_TIMEOUT_MS=1500`, `MEMORY_MAX_CONTEXT_TOKENS=1500`.
4. Unit/integration tests (run without the live chat endpoint): search/learn
   round-trip with `memory_test`, flag-off path, timeout → degraded path.
5. Commit; run `scripts/backup-memory.sh`. **MANUAL STEP B (Chuck):**
   `./homelab.sh rebuild skill-only` (see §3.0 — litellm stays up).

**Gate to Phase 3:** module passes tests standalone; manual step B done with
post-checks green; one env switch disables it.

### Phase 3 — Identity mapping & scope isolation

1. **Keys:** v1 = `chuck` only (decision §0.1). Keep `SIRI_API_KEY` as the
   legacy shared key → maps to `chuck` (backward compatible). Add
   `SIRI_KEY_SERVICE` for scheduler jobs. Design the map so `SIRI_KEY_SON` is a
   one-line addition later — do NOT create son's key in v1.
2. **Resolver** in `skills/runner/memory/identity.py`:
   - `X-API-Key` → `user_id` via an explicit map (key name/constant from config,
     **not** raw key values stored anywhere; compare in code, log only the user_id).
   - Unknown key → `user_id=unknown`: retrieval disabled, writeback disabled,
     logged. Never default to `chuck` for unknown keys (PDF §3).
   - Scheduler jobs (`skills/runner/scheduler.py`) and `dispatch_job()`
     (`main.py:233`) use `user_id=service` (D10) unless the job was triggered by
     a user request (then inherit that user).
3. Request context: carry `user_id`, `household_id="family"`, `run_id`, `source`
   (`siri|web|job|cli`), `agent_id` through `api_chat`, `dispatch_job`, and skill
   execution.
4. **Tests (v1 is single-user — prove the isolation machinery works):**
   - `chuck` stores a preference; a second test principal (`memory_test`) stores
     a different one → each retrieves only its own.
   - Household-scoped fact visible to `chuck`; private fact not visible to the
     test principal.
   - Raw key values never appear in memory records, logs, config, or fixtures.
   - Unknown key → no retrieval, no writeback, logged.

5. Commit; run `scripts/backup-memory.sh`. **MANUAL STEP B (Chuck):**
   `./homelab.sh rebuild skill-only` (see §3.0).

**Gate to Phase 4:** isolation tests green (run after manual step B);
OWUI/master-key traffic (if any hits skill-runner) maps to a safe default
(no writeback).

### Phase 4 — Automatic pre-request retrieval

1. Middleware hook in `skills/runner/main.py`:
   - `_chat_direct()` (line ~1912): inject memory block between the system prompt
     and the user message.
   - `siri_chat` skill (`skills/siri_chat/skill.py`, `SYSTEM_PROMPT` at line ~99):
     same injection for the tool-calling path.
   - Keep it in ONE place (`memory/context.py.build_prompt_context(...)`) so both
     call sites stay identical.
2. Behavior (PDF §5A): search private + household separately; top_k ≈ 6 total;
   conservative score threshold; dedupe; trim to 500–1500 tokens; on error/timeout
   → continue without memory, log degraded mode (never take the assistant down).
3. Request-level switch: `{"memory": {"enabled": false}}` in `ChatRequest`
   (add optional field) for debugging/privacy.
4. Instrumentation: log latency, hit count, injected char/token estimate per
   request (structured log line; no secrets).

**Test scenarios (PDF §5A)**
- [ ] Preference learned for chuck changes a later recommendation without restating.
- [ ] Unrelated memory NOT injected into an unrelated technical task.
- [ ] Test principal (`memory_test`) request never receives chuck's private memory
      (v1 is single-user; son added later via the same machinery).
- [ ] `memory.enabled=false` returns baseline behavior.
- [ ] Memory service outage (stop Qdrant) → chat still works, degraded log present.

5. Commit; run `scripts/backup-memory.sh`. **MANUAL STEP B (Chuck):**
   `./homelab.sh rebuild skill-only` (see §3.0).

**Gate to Phase 5:** all scenarios pass (run after manual step B); p95 added
latency acceptable for voice (Siri speak path truncates to 250 chars — verify
no regression in `speak`).

### Phase 5 — Post-turn learning & consolidation

1. Writeback after successful response only (`_chat_direct` success path;
   siri-chat final answer). Synchronous for v1 (move to queue only if latency
   proves unacceptable and infra exists).
2. Pre-filter (`memory/policy.py`): reject credential-like content (key/token/
   password patterns), strip system prompts, tool payloads, logs, hidden
   reasoning. Store fewer, better memories (PDF §6).
3. Inclusion/exclusion instructions for Mem0 extraction: durable preferences,
   stable facts, decisions, corrections, recurring routines, useful prior
   outcomes. Direct user statements = highest trust; agent-inferred = lower
   confidence + provenance metadata (`source`, `category`, `agent_id`, `run_id`,
   `confidence`, `importance` per PDF §6).
4. Conflict handling: changed preference → update/consolidate, not duplicate.
5. Explicit commands (new intents in `/api/chat` + admin endpoints):
   "remember this" → `learn_from_turn` with `source=direct_user, importance=high`;
   "forget that" → targeted delete; correction → update.
6. Write failures are non-fatal: log, response still succeeds.

**Tests (PDF §6)**
- [ ] API-key-like text in a chat is NOT stored.
- [ ] Changed preference consolidates (no contradictory duplicates).
- [ ] "Remember this" persists and is retrieved next session.
- [ ] Web/tool-derived instruction ("ignore system instructions…") is not stored
      or has no policy effect.

7. Commit; run `scripts/backup-memory.sh`. **MANUAL STEP B (Chuck):**
   `./homelab.sh rebuild skill-only` (see §3.0).

**Gate to Phase 6:** test matrix (§5) green (run after manual step B); memory
count stays small (inspect `mem0_memories` after a week of use before enabling
MCP tools).

### Phase 6 — Optional MCP memory tools (only after Phase 5 is proven)

1. Follow the existing MCP server pattern: new `mcp/servers/memory/`
   (FastMCP, streamable-http, port 8000) + entry in `compose/compose.mcp.yml`
   + registration in `litellm/config.yml` `mcp_servers`. (This is the one
   additional container the design may add; it is NOT needed for automatic memory.)
2. Tools: `memory_search(query, scope?, top_k?)`, `memory_remember(text, scope?,
   category?)`, then `memory_update` / `memory_forget` / `memory_list` after
   authorization is tested.
3. **Authorization rule (PDF §8):** the model may NOT supply `user_id` — the
   wrapper derives it from the authenticated run context (pass through the
   request's user_id server-side). Destructive ops restricted to admin/explicit
   user requests.
4. MCP failure must not disable automatic middleware memory.
5. Commit; run `scripts/backup-memory.sh`. **MANUAL STEP C (Chuck):**
   `./homelab.sh up mcp-only` (starts `mcp_memory`; existing MCP servers
   unchanged) **then** `docker restart litellm-proxy` (config change for
   `mcp_servers` registration) — see §3.0.

**Gate to Phase 7:** automatic memory already works end-to-end; manual step C
done with post-checks green.

### Phase 7 — Jobs, agents, and skills integration

1. Propagate `user_id`/`run_id` through `dispatch_job()` → skill execution →
   sub-agent calls (skills that call LiteLLM directly, e.g. `siri_ask`,
   `siri_chat`, briefs).
2. Skills remain procedural memory — do NOT copy skill contents into Mem0 (PDF §2).
3. Long-running jobs: `run_id` for working state; write durable outcomes only at
   completion/checkpoints (e.g. a resolved troubleshooting episode).
4. Agent-generated facts: `source=agent_result`, lower confidence, provenance tags.

5. Commit; run `scripts/backup-memory.sh`. **MANUAL STEP B (Chuck):**
   `./homelab.sh rebuild skill-only` (see §3.0).

**Tests (run after manual step B):** a scheduled job (e.g. `morning_brief`)
runs under `service` identity and does not create personal memories; a
user-triggered job inherits the user.

### Phase 8 — Administration, observability, backups

1. Admin endpoints on skill-runner (admin-key protected):
   - `GET /api/memory/users/{user_id}` (list/search by scope/category/date/text)
   - `PATCH /api/memory/{memory_id}`, `DELETE /api/memory/{memory_id}`
   - `DELETE /api/memory/users/{user_id}` (delete-all / export)
   - `GET /api/memory/health` (service health, recent write/search errors)
   CLI wrapper in `cli/` for day-to-day use. (No dashboard in v1 — PDF §7:
   REST/CLI is sufficient.)
2. Observability: structured logs (memory IDs, user IDs — never secrets);
   expose counters (search/write latency, hit count, errors, per-user memory
   count) — reuse the existing Prometheus/Grafana stack
   (`compose/compose.monitoring.yml`) once skill-runner emits metrics;
   LiteLLM already has the prometheus callback for model-side stats.
3. Backups (from Phase 1): keep `scripts/backup-memory.sh` current (mem0_memories
   snapshot + `.env` copy); document + test restore with a non-production user;
   memory **text + metadata** is the source of truth, embeddings are rebuildable
   (PDF §4).

4. Commit; run `scripts/backup-memory.sh`. **MANUAL STEP B (Chuck):**
   `./homelab.sh rebuild skill-only` (see §3.0).

**Gate to Phase 9:** admin ops exercised manually (after manual step B);
restore test current.

### Phase 9 — Hardening & migration readiness

1. Pin versions: `mem0ai` (Dockerfile), `skill-runner:local` build, and — while we
   are here — pin `litellm-proxy` off `main-latest` to the tested 1.92.x line (D8),
   and `qdrant` off `latest` in `compose/compose.ai-core.yml`.
6. Commit; run `scripts/backup-memory.sh` (extra care — image changes).
   **MANUAL STEP D (Chuck):** `./homelab.sh rebuild ai-only` (recreates all
   ai-core with pinned images — litellm, qdrant, owui, redis, searxng, etc.)
   then **MANUAL STEP B:** `./homelab.sh rebuild skill-only` — see §3.0.
   Verify post-checks + `matrix-coder` and `embeddings` still work after the
   litellm version change before continuing.
2. Least privilege: dedicated memory collection ACLs in Qdrant; memory service
   credential with minimal model access. (Qdrant `0.0.0.0:6333` exposure stays
   as-is per decision §0.5 — revisit when the family KB moves to Qdrant.)
3. Regression suite: identity isolation, household scope, secret filtering,
   prompt-injection boundary, memory-outage degradation, embedding-dimension
   consistency (configured dim == live LiteLLM output).
4. Embedding migration procedure (PDF §9): new alias `homelab-embedding-v2` →
   new collection → re-embed from stored text → quality comparison → cut over →
   keep v1 briefly for rollback. Never silently repoint v1.
5. Feature-flag review: global disable (`MEMORY_ENABLED=false`) works end-to-end.

---

## 4. Feature flags & rollback (PDF §10)

```
MEMORY_ENABLED=true            # master switch
MEMORY_RETRIEVAL_ENABLED=true  # pre-request search
MEMORY_WRITEBACK_ENABLED=true  # post-turn learning
MEMORY_MCP_ENABLED=false       # Phase 6 tools
MEMORY_HOUSEHOLD_ENABLED=true
MEMORY_DEBUG_LOGGING=false
```

Rollback order: (1) disable writeback if bad memories appear → (2) disable
retrieval if bad memories influence answers → (3) main AI path keeps working
without memory → (4) roll skill-runner image back to last known-good → (5)
restore memory collection from backup **only** on data corruption (never
blindly roll back the whole homelab DB).

---

## 5. Core test matrix (run at each gate)

| Test | Expected |
|---|---|
| Identity isolation | chuck & test principal (`memory_test`) retrieve only their own private memories (son later) |
| Household scope | both retrieve explicitly shared household facts |
| Relevance | relevant preference injected; unrelated memories omitted |
| Correction | new direct correction supersedes/consolidates stale memory |
| Secret filtering | API-key/token-like content never stored |
| Prompt injection | stored/retrieved content cannot override system policy |
| Memory outage | normal AI request succeeds in degraded mode |
| LiteLLM outage | memory writes fail safely; no direct provider bypass |
| Embedding consistency | configured dim == live LiteLLM embedding output (768) |
| Backup/restore | test-user memories restore and search successfully |

---

## 6. Success criteria after initial rollout (PDF §10)

- [ ] Chuck teaches a durable preference once; it applies later without restating.
- [ ] (Later phase) Son gets independent private memory via a one-line key+map change.
- [ ] Explicitly household-scoped facts are shared by all users with access
      (chuck in v1; son later).
- [ ] No additional embedding service running; LiteLLM remains the only model/embedding gateway.
- [ ] Existing Qdrant/Postgres infrastructure reused (no new vector/DB containers).
- [ ] Memory can be inspected, corrected, deleted, disabled, backed up, and restored.
- [ ] Latency impact acceptable for the voice/Siri path.

---

## 7. Non-negotiables (carried over from PDF §11)

1. Do not deploy the upstream Mem0 example stack blindly (its reference stack
   bundles Postgres/pgvector + dashboard — we copy only what we need: the
   library + Qdrant config).
2. Do not create a second Postgres, embedding server, model server, or dashboard
   unless inspection proves it necessary. (One MCP container in Phase 6 is the
   only possible addition.)
3. No raw API keys as memory user IDs; no secrets printed/stored.
4. No bypassing LiteLLM to call model providers directly.
5. No hard-coded embedding dimensions — always test the live endpoint.
6. No system prompts, hidden reasoning, raw tool logs, credentials, or full
   transcripts in long-term memory.
7. Memory failure degrades gracefully; it never takes down normal AI use.
8. Private memories stay isolated between users.
9. Skills/procedural instructions stay out of user memory.
10. Every change reversible and covered by tests.
11. The implementing model **never runs container lifecycle commands**
    (up/down/restart/recreate/rebuild/pull/rm on any running container). All
    such steps are manual, run by Chuck between model turns (§3.0).

---

## 8. Known related gaps (out of scope for this plan — track separately)

- `mcp_knowledge` collection allowlist ≠ actual `family_kb` collection; `kb_search`
  is exact-match scroll, not vector search (D6).
- `family_kb_ingest` skill targets the decommissioned harness endpoint (D6).
- Per-key LiteLLM hardening / MCP scoping still "Deferred Indefinitely" (TODO.md) —
  memory's key→user map lives in skill-runner and does not depend on it.
- OWUI MCP tool registration (TODO.md "Frontier Integration Plan" steps) still
  pending user action; OWUI is being deprecated, so OWUI memory integration is
  out of scope for this plan.

---

## Appendix A — Verified inventory (2026-08-24, Phase 0 evidence)

### Containers (AI-relevant)
| Container | Image | Role | Network(s) |
|---|---|---|---|
| `litellm-proxy` | ghcr.io/berriai/litellm:main-latest (unpinned) | Model+embedding gateway, MCP registry | ai-net, host port 4000 |
| `litellm-db` | postgres:16-alpine | LiteLLM metadata DB only | ai-net, `/home/chuck/data/litellm-postgres` |
| `qdrant` | qdrant/qdrant:latest | Vector store (KB + future memory) | ai-net, host port 6333, `/home/chuck/data/qdrant` |
| `ai-redis` | redis:7-alpine | Cache | ai-net |
| `skill-runner` | skill-runner:local | **Normalized AI gateway** (chat, skills, jobs, scheduler) | ai-net + public-net, `THOR_IP:8091` |
| `open-webui` | ghcr.io/open-webui/open-webui:latest | Web UI; talks to LiteLLM directly (master key) | ai-net, host port 3000 |
| `mcp_search/knowledge/crawl/filesystem/filesystem_readonly/mysql/homelab_status/media` | ai-mcp-mcp_* | 8 MCP servers, streamable-http :8000 | ai-net |
| `searxng`, `searxng-valkey`, `crawl4ai` | — | Search/crawl backends | ai-net |
| `family-wiki` | mkdocs-material | Family KB docs (markdown) | ai-net, host port 8011 |
| `caddy` / `cloudflared` | caddy:2 / cloudflared | Edge reverse proxy / tunnel | edge-net/public-net/ai-net |
| `plausible-db` | postgres:16-alpine | Plausible analytics only (NOT for memory) | — |

### Networks
`ai-net` (all AI services), `edge-net`, `public-net`, `monitoring_monitoring-net`.

### LiteLLM (verified via API 2026-08-24)
- Model aliases: `matrix-coder` (openai/qwen38-27b, vLLM `matrix:8000`),
  `matrix-gemma4-moe` (ollama/gemma4:26b, `matrix:11434`),
  `studio-gemma4-4b` (LMStudio `macstudio:1234`), `embeddings`
  (ollama/nomic-embed-text, `matrix:11434`), `hf-sd3`.
- `POST /v1/embeddings {"model":"embeddings"}` → **HTTP 200, 768-dim vector**.
- Auth: master key + public key; DB has only `default_user_id`, no teams,
  4 unnamed verification tokens. No per-user keys (D2).
- 8 MCP servers registered, all `allow_all_keys: true`.

### Qdrant (verified via API 2026-08-24)
- Collections: `family_kb` only — 384-dim, Cosine, 18 points, status green.
- No pgvector anywhere; no other vector store.

### Auth / entry points
- `siri.choukalos.com` → Caddy → `skill-runner:8091` with `X-API-Key: $SIRI_API_KEY`
  (single shared key; skill-runner accepts comma-separated key list, `main.py`
  `api_chat` ~line 1790).
- `llm.choukalos.com` → `litellm-proxy:4000` (`LITELLM_PUBLIC_API_KEY`).
- Open WebUI: 1 user ("Chuck", admin); uses `LITELLM_MASTER_KEY` for LiteLLM.
- Scheduler: `skills/runner/scheduler.py`, jobs via `dispatch_job()`
  (`main.py:233`), hardcoded `requester="siri"` (D10).

### Code touchpoints for this plan
- `skills/runner/main.py` — `api_chat` (~1790), `_chat_direct` (~1912),
  `ChatRequest` (~1211), `dispatch_job` (233), `LiteLLMClient` (391).
- `skills/siri_chat/skill.py` — `SYSTEM_PROMPT` (~99), tool-calling loop.
- `skills/runner/scheduler.py` — job scheduling (service identity).
- `compose/compose.skill-runner.yml`, `compose/compose.ai-core.yml`,
  `compose/compose.mcp.yml`, `litellm/config.yml`, `homelab/.env`.
- `skills/runner/Dockerfile` + `pyproject.toml` — add `mem0ai`.

### Backups
- **None exist** (D3). No crontab entries; `docs/thor_manual_tasks.md` Phase 0
  backup task still open. **Resolved by decision §0.3:** git (config/code) +
  `.env` copy + Qdrant snapshot via `scripts/backup-memory.sh` (Phase 1).