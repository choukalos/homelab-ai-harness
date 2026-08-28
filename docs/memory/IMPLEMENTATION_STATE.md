# Long-Term Memory — Implementation State

> **Handoff file for the implementing model.** Start every phase by reading THIS
> file + `homelab/memory_todo.md` (full plan: phases, gates, tests, non-negotiables).
> Update this file at the end of every phase. Keep < ~5K tokens.
> **No secret values here — ever.** (Key names/paths yes; key contents no.)

## Status

- **Phase 0: COMPLETE** (2026-08-24 inventory; 2026-08-25 decisions locked).
- **Phase 1: COMPLETE** (2026-08-26; all gates green — see phase log).
- **Phase 2: COMPLETE** (gate MET 2026-08-27) — module + unit +
  integration tests green; admin-timeout budget fix verified live; extended
  live suite 28/28 in the rebuilt image (THIRD MANUAL STEP B, 2026-08-27).
- **Phase 3: COMPLETE** (gate MET 2026-08-27, commit `9ded3a1c`) — identity
  resolver (`memory/identity.py`, `MEMORY_USER_KEYS=chuck=SKILL_RUNNER_API_KEY,
  service=SIRI_KEY_SERVICE` — env var NAMES only), per-request contextvar,
  job identity (D10: scheduler/launch_skill/run-now → `service`), api_chat
  wiring. Unit tests green (identity 29/29). Live isolation checks green in
  the extended suite (chuck vs memory_test, household visibility, unknown
  principal, secret filter, direct Qdrant payload scan).
- **Phase 4: COMPLETE** (gate MET 2026-08-27, commits `1985641a` +
  `a350a899`) — automatic pre-request retrieval. ONE render path
  (`interface.render_context`) injected at both chat call sites
  (`_chat_direct` in main.py + `siri_chat` skill); `MEMORY_SCORE_THRESHOLD=0.5`
  relevance gate; `ChatRequest.memory={"enabled": false}` per-request switch
  (flows to `Job.memory_enabled` → skill); structured per-request
  instrumentation log (user_id/hits/chars/latency_ms, no secrets). Extended
  live suite **35/35 ALL PASS** (incl. 8 render_context checks). End-to-end
  verified: learned preference changed a live `/api/chat` answer; `memory.
  enabled=false` → zero retrieval (no embeddings/Qdrant); cold-start
  degradation → chat still answers. Unit tests 59/59.
- **Phase 5: GATE MET** (2026-08-27) — post-turn writeback into the chat
  loop, live-verified post-rebuild. Writeback after
  SUCCESSFUL responses only, at both call sites (`_chat_direct` success path
  + `siri_chat` final answer), synchronous for v1, non-fatal, budgeted
  (`MEMORY_WRITEBACK_TIMEOUT_MS`), gated by the request-level memory switch.
  Provenance metadata on every stored fact (`source`/`importance`/
  `confidence`/`agent`/`turn_id` — mem0 2.0.19 strips the identity keys
  `user_id`/`agent_id`/`run_id` from `add(metadata=...)`, so provenance uses
  the free-form keys `agent`/`turn_id`); built-in extraction instructions
  (inclusion/exclusion + prompt-injection exclusion + JSON-validity rule,
  PDF §6) via mem0 `custom_instructions` (env override
  `MEMORY_EXTRACTION_INSTRUCTIONS`). Explicit commands: `remember`/`forget`
  intents in `/api/chat` → `remember_direct` (source=direct_user,
  importance=high) / `forget_matching` (targeted delete). mem0 2.0.19 OSS is
  ADD-only (no in-place update): changed preferences are stored as a
  self-contained supersede statement; the context block carries both and
  sorts score-desc then recency-desc. Startup warmup thread (`interface.
  warmup()`) moves the one-time mem0 init out of the first turn's writeback
  budget. Unit tests 93/93; identity 29/29. **Live e2e (post-rebuild):**
  preference stated in chat → stored (`source=chat`) → follow-up used it;
  `remember` intent → stored verbatim in 4.1s (`infer=False`, no LLM,
  prefix stripped: "my favorite hiking trail is Eagle Creek.") →
  retrieved (hits=1, 218ms) → `forget` intent → deleted (0.44s);
  counts back to 0 / 18. Cold-start writeback ~6s warm (warmup thread);
  synchronous v1 latency acceptable so far (note for Phase 9).
- **Phase 7: GATE MET** (2026-08-27) — jobs/agents/skills identity
  propagation, live-verified post-rebuild. New
  `memory/jobctx.py` is the single propagation path: `dispatch_job()`
  resolves identity into the `Job` (user_id/run_id/memory_enabled);
  `_execute_skill` hands the `Job` to `skill.run(params, job)`; jobctx
  reads it back so ANY skill (conversational or long-running) retrieves
  + writes back with the correct identity, without re-implementing
  gating/non-fatality. Skills now using it: **siri_ask** (retrieval +
  writeback, source=chat), **morning_brief** (retrieval — personalizes
  the brief; a scheduled run under 'service' is a no-op, a user-triggered
  run inherits the user), **deep_research** (durable OUTCOME writeback at
  COMPLETION only, source=agent_result, confidence=normal, agent
  provenance tag, run_id correlation — long-running job rule). Skills
  remain procedural memory: `policy.sanitize_turn` drops system/tool
  content so skill prompts are never stored (unit-tested). Unit tests
  120/120 (+27); identity 29/29. Integration suite +5 live checks
  (scheduled/service writes nothing + no leak; user job inherits user +
  provenance). **Live e2e (post-rebuild):** user-triggered `morning_brief`
  via `/api/chat` (chuck's key) → job log `Identity: user_id=chuck`;
  `siri_ask` via `/skills/siri_ask` (no user context) → job log
  `Identity: user_id=service`, Qdrant counts stayed 0/0 (no leak, no
  service memory). Counts back to 0 / 18.
- **Phase 8: COMPLETE** (gate MET 2026-08-28 — post-rebuild e2e green,
  scrape wiring verified) — administration, observability,
  backups. (1) **Admin REST endpoints** on skill-runner, admin-key protected
  (`MEMORY_ADMIN_API_KEY`, distinct from user keys; unset → 503, bad key →
  403): `GET /api/memory/users/{user_id}` (list/search by scope/query/limit),
  `PATCH /api/memory/{memory_id}`, `DELETE /api/memory/{memory_id}`,
  `DELETE /api/memory/users/{user_id}` (`?export=true` returns memories
  before deletion), `GET /api/memory/health` (health + counters). Backed by
  new `memory/admin.py` which BYPASSES the `_valid_user` gate (admin may
  inspect/manage any user incl. service/household); all ops non-fatal,
  admin timeout budget. (2) **CLI wrapper** `cli/memory-admin.sh` (health /
  list / search / update / delete / delete-user). (3) **Observability**:
  new dependency-free `memory/metrics.py` (thread-safe counters + histograms
  + per-user gauge, Prometheus text exposition, no secrets) wired into the
  interface (search/writeback latency+status, hit/stored counts, errors by
  op); `GET /metrics` endpoint; skill-runner added to the Prometheus scrape
  config. (4) **Backups:** `scripts/backup-memory.sh` kept current; restore
  tested end-to-end with a non-production user (`restore_test`): stored →
  snapshot → deleted live → restored into a throwaway Qdrant (port 16333)
  → full text + metadata recovered (text under `data` key). Unit tests
  145/145 (+25 Phase 8); live integration 60/60 (+8 Phase 8). REST smoke
  15/15 (auth 403/503/200, /metrics Prometheus text). Counts back to 0 / 18.
  **Post-rebuild (2026-08-28):** MANUAL STEP B done (image 00:59:57Z);
  live admin e2e green (seed/list/search/PATCH-verbatim/DELETE/
  delete-user+export on `memory_test`; CLI green; auth 200/403/403;
  admin key absent from logs; counts back to 0 / 18). Scrape gap: VM
  promscrape doesn't hot-reload by default → `configCheckInterval=30s`
  added (`b04a99b7`); one container recreate pending, then
  `up{job="skill-runner"}=1`. **DONE (2026-08-28):** recreate applied;
  `up{job="skill-runner"}=1`, all 12 `memory_*` series live.
- **Phase 9: IN PROGRESS** (started 2026-08-28) — hardening & migration
  readiness. (1) **Version pinning: DONE + committed (`f1c63336`)** —
  `litellm` `main-latest` → `v1.92.0` (the EXACT version running, verified
  via dist-info; matches config header's tested line, D8) and `qdrant`
  `latest` → `v1.18.1` (EXACT running version via GET /; Qdrant tags carry
  a `v` prefix). Zero version drift — pins lock what's proven. `mem0ai`
  already pinned (2.0.19). Awaiting **MANUAL STEP D** (`rebuild ai-only`)
  then **STEP B** (`rebuild skill-only`). (2) Least privilege: TODO.
  (3) Regression suite: TODO. (4) Embedding-migration procedure (doc only):
  TODO. (5) Feature-flag review: TODO.
- Last updated: 2026-08-28 (Phase 8 gate MET — scrape verified live).

## Operational constraint — container lifecycle is MANUAL (read first)

**The implementing model NEVER runs container lifecycle commands** (no
`docker (compose) up|down|restart|recreate|rm`, no `docker pull`, no
`./homelab.sh up|down|restart|rebuild|pull`). The session itself runs through
`skill-runner` → `litellm-proxy` (skill-runner holds a pooled HTTP client to
litellm) — restarting either breaks the session. Full protocol + post-checks +
rollback: `memory_todo.md` §3.0.

**Allowed docker usage:** read-only (`docker ps/inspect/logs --tail/exec
read-only`) + `docker run --rm` throwaway containers (no published ports, or
non-clashing only, e.g. 16333; never 4000/8091/6333/3000).

**Manual steps (Chuck runs, between model turns, after model commits + runs
`scripts/backup-memory.sh` and prints the step block):**

| Step | When | Command |
|---|---|---|
| A | litellm config changed | `docker restart litellm-proxy` |
| B | skill-runner code/env/image changed | `./homelab.sh rebuild skill-only` (litellm stays up) |
| C | new MCP container (Ph 6) | `./homelab.sh up mcp-only` |
| D | image pinning (Ph 9) | `./homelab.sh rebuild ai-only` |

**Post-checks (model runs, read-only):**
`curl -s http://localhost:4000/health/liveliness` ·
`curl -s http://192.168.4.54:8091/health` (THOR_IP, not localhost) ·
`docker ps` · `docker logs --tail 50 <ctr>`.

**Caveat:** after step A, the model's first LLM turn may fail once (stale
keep-alive in skill-runner's pool) — re-send the prompt if so.

**STATUS (2026-08-28):** Phase 8 COMPLETE (gate MET) — admin REST + CLI +
metrics + restore all live-verified post-rebuild; scrape wired into
VictoriaMetrics (`up{job="skill-runner"}=1`). Next: Phase 9 (hardening &
migration readiness) or Phase 6 (optional MCP).

## Decisions (locked by Chuck, 2026-08-25)

1. **v1 users: `chuck` only.** Build the key→user map so `son` is a one-line
   addition later (new key + map entry). Do NOT create son's key in v1.
2. **Channels: skill-runner only** (Siri, `/api/chat`, CLI, scheduler jobs).
   Open WebUI is being deprecated → OWUI memory is out of scope entirely.
3. **Backup:** git (config/code — already tracked) + copy `.env` to
   `/home/chuck/data/backups/` + Qdrant snapshot of `mem0_memories`.
   Wrap the two non-git steps in `scripts/backup-memory.sh`; run before any
   storage change and at every phase gate. No cron, no pg_dumpall in v1.
4. **Extraction LLM: `matrix-coder`** (qwen38-27b via vLLM). No A/B testing.
5. **Qdrant `0.0.0.0:6333` stays as-is** for v1 (revisit with family-KB work).

## Architecture (locked — Phase 0 delta design)

- **Engine:** Mem0 OSS as a Python library **in-process in `skill-runner`**
  (zero new containers; the one possible addition is an MCP container in Phase 6).
- **Storage:** existing **Qdrant**, new collection **`mem0_memories`**
  (768-dim, Cosine). No pgvector, no new Postgres/vector DB.
- **Embeddings:** LiteLLM-only. New alias **`homelab-embedding-v1`** →
  `ollama/nomic-embed-text` (same backend as existing `embeddings` alias).
  Mem0 OpenAI-compatible embedder → `http://litellm-proxy:4000/v1`.
- **Extraction LLM:** `matrix-coder` via LiteLLM.
- **Identity:** key→user map in skill-runner (no LiteLLM core changes).
  v1 user_ids: `chuck` (legacy `SIRI_API_KEY` maps to chuck), `service`
  (scheduler jobs), `unknown` (unknown key → no retrieval, no writeback, logged).
  `household` scope for explicitly shared facts. **Never** store raw key values
  in config, logs, or memory.
- **MCP memory tools:** Phase 6 only; model may never supply `user_id`.
- **Flags:** `MEMORY_ENABLED`, `MEMORY_RETRIEVAL_ENABLED`,
  `MEMORY_WRITEBACK_ENABLED`, `MEMORY_MCP_ENABLED=false`,
  `MEMORY_HOUSEHOLD_ENABLED`, `MEMORY_DEBUG_LOGGING` (all in `.env`).
- **Non-negotiables:** see `memory_todo.md` §7 (11 items; e.g. no secrets in
  memory, no LiteLLM bypass, graceful degradation, skills stay out of user
  memory, no container lifecycle commands from the model).

## Verified facts (2026-08-24 — do not re-derive; re-verify only where noted)

**Infra (Thor 192.168.4.54, docker network `ai-net`)**
- `litellm-proxy` (ghcr.io/berriai/litellm:main-latest — **unpinned**, Phase 9) :4000
- `litellm-db` (postgres:16) — LiteLLM metadata only; single `default_user_id`,
  no teams, 4 unnamed tokens. **No per-user keys exist.**
- `qdrant` (qdrant:latest) host port 6333, data `/home/chuck/data/qdrant`.
  Only collection: `family_kb` (384-dim, Cosine, 18 points) — **legacy KB, do
  not touch; never mix collections.**
- `skill-runner:local` :8091 (ai-net + public-net) — normalized gateway.
- `open-webui` :3000 — 1 user (Chuck, admin), talks to LiteLLM directly.
  Out of scope (deprecated).
- 8 MCP servers on ai-net, all registered in LiteLLM (`allow_all_keys: true`).
- `plausible-db` — analytics only, not for memory.
- **No backups exist.** `.env` is gitignored; `data/` untracked; compose/
  Caddyfile/litellm config/skills/MCP code ARE git-tracked.

**LiteLLM (verified via API 2026-08-24)**
- Aliases: `matrix-coder` (openai/qwen38-27b, vLLM `matrix:8000`),
  `matrix-gemma4-moe` (ollama/gemma4:26b, `matrix:11434`),
  `studio-gemma4-4b` (LMStudio `macstudio:1234`),
  `embeddings` (ollama/nomic-embed-text, `matrix:11434`), `hf-sd3`.
- `POST /v1/embeddings {"model":"embeddings"}` → **HTTP 200, 768-dim** (live).
- KB is 384-dim vs current 768-dim embeddings → KB built by decommissioned
  legacy harness; `mcp_knowledge` allowlist (`family_curated`/`homelab_curated`/
  `coding_curated`) matches no real collection; `kb_search` is exact-match
  scroll. All separate workstreams — do NOT fix in this project.

**Auth / entry points**
- `siri.choukalos.com` → Caddy → `skill-runner:8091` with `X-API-Key: $SIRI_API_KEY`
  (single shared key; skill-runner accepts a comma-separated key list).
- `llm.choukalos.com` → `litellm-proxy:4000` (`LITELLM_PUBLIC_API_KEY`).
- Scheduler jobs: `dispatch_job()` hardcodes `requester="siri"` (D10 → `service`).

## Key files

| File | Why |
|---|---|
| `memory_todo.md` | The plan: phases 0–9, gates, tests, non-negotiables |
| `skills/runner/main.py` | `api_chat` (~1893), `_chat_direct` (~1986, memory injection), `ChatRequest` (~1251, `memory` switch), `dispatch_job` (~254, `memory_enabled`) |
| `skills/siri_chat/skill.py` | `SYSTEM_PROMPT` (~99) — second injection point |
| `skills/runner/scheduler.py` | jobs (service identity) |
| `litellm/config.yml` | `model_list` (add `homelab-embedding-v1`), `mcp_servers` |
| `compose/compose.skill-runner.yml` | add `MEMORY_*` env |
| `compose/compose.ai-core.yml` | qdrant/litellm/open-webui services |
| `skills/runner/pyproject.toml` + `Dockerfile` | add `mem0ai` (pinned) |
| `memory/admin.py` | NEW in Phase 8 — admin ops (bypass `_valid_user`, non-fatal) |
| `memory/metrics.py` | NEW in Phase 8 — dependency-free Prometheus metrics |
| `cli/memory-admin.sh` | NEW in Phase 8 — admin CLI wrapper |
| `prometheus/prometheus.yml` | skill-runner scrape job (Phase 8) |
| `scripts/backup-memory.sh` | NEW in Phase 1 |
| `.env` | `MEMORY_*` vars (gitignored) |

## Phase 1 checklist (COMPLETE 2026-08-26)

1. ✅ `mkdir -p /home/chuck/data/backups` (chmod 700).
2. ✅ `scripts/backup-memory.sh` (commit `0429d5eb`, fixes `ec5966a8`/`0bacd50e`):
   .env copy (600) + Qdrant snapshot extraction + git-clean check. Snapshot
   extraction is via read-only `docker exec qdrant cat` — Qdrant 1.18 writes
   snapshots to `/qdrant/snapshots/` INSIDE the container (not the mounted
   volume). Restore tested (see phase log).
3. ✅ `homelab-embedding-v1` alias (commit `0429d5eb`); MANUAL STEP A run
   (twice: alias add, then `drop_params` fix `14c9a4ff`). Both aliases proven:
   `embeddings` 200/768-dim ~4.7s cold; `homelab-embedding-v1` 200/768-dim
   ~44ms warm. Post-checks green both times.
4. ✅ `matrix-coder` structured-output probe: valid JSON facts; 1/3 runs
   markdown-fenced the JSON → **Phase 2 parser must strip fences + retry on
   parse failure** (re-observed in round-trip: 1 of 2 adds failed extraction,
   retry succeeded).
5. ✅ Qdrant collection `mem0_memories` (created BY MEM0 itself — dense 768
   Cosine; no BM25 slot, fastembed not installed → semantic search only,
   fine for v1). Mem0 round-trip **ALL PASS** in throwaway container
   (add×2/search/get_all/update/delete/user isolation), disposable user
   `memory_test`. `family_kb` verified untouched (18 pts/384-dim/Cosine).
6. ✅ No bypass: all LLM/embedding traffic via `litellm-proxy` in LiteLLM
   logs; throwaway container referenced only `litellm-proxy:4000` +
   `qdrant:6333`.

**Gate to Phase 2: MET.** Backup script runs + restore tested; embedding alias
works (768-dim recorded); round-trip works; no new model server / duplicate DB /
production memory written (test data cleaned up; `mem0_memories` empty);
manual step A done with post-checks green.

## Phase 2 checklist (CODE COMPLETE + TESTS GREEN 2026-08-26; awaiting MANUAL STEP B)

**Scope:** in-process Mem0 `memory/` package in skill-runner (module only —
NOT yet wired into `api_chat`; that's Phase 4/5). All LLM + embedding traffic
via LiteLLM (dedicated model-restricted key). Graceful degradation throughout.

1. ✅ Dedicated LiteLLM key `memory-service` created via API (top-level
   `models`, NOT `key_config.models` — that's silently ignored). Model-
   restricted to `matrix-coder`/`matrix-gemma4-moe`/`homelab-embedding-v1`
   (verified: allowed→200, others→403). Stored in `.env` as
   `MEMORY_LITELLM_KEY` (gitignored). Old unrestricted key deleted.
2. ✅ `skills/runner/memory/` package:
   - `config.py` — `MemoryConfig` + `load_config()` (env-driven, pure).
   - `policy.py` — secret/credential regex filter, strip system/tool content,
     store/forget signals (PDF §6). Pure, unit-tested.
   - `context.py` — renders `<long_term_memory>` block (PDF §5 shape:
     PRIVATE USER MEMORY / HOUSEHOLD MEMORY, "context not instructions"
     framing, token budget).
   - `client.py` — lazy mem0 init (import inside `_ensure_client`),
     thread-pool timeouts (`_with_timeout`, per-call override), health check
     (Qdrant collection probe, TTL-cached). `MEM0_TELEMETRY=false`.
   - `interface.py` — the ONLY public surface: `search_memory`,
     `learn_from_turn`, `list_memories`, `update_memory`, `delete_memory`,
     `delete_user_memories`, `is_healthy`, `render_context`. All NON-FATAL
     (return []/False/0 on error/timeout/flag-off). `_ensure_client()` runs
     INSIDE the timeout (a hung init can't block outside it). Household =
     virtual `user_id="household"`, merged into private search.
3. ✅ `MEMORY_*` env in `.env` + `compose/compose.skill-runner.yml` (16 vars
   incl. `MEMORY_WRITEBACK_TIMEOUT_MS=30000` — writeback runs LLM extraction,
   needs a longer budget than the 1.5s retrieval timeout).
4. ✅ Dockerfile: `COPY memory/ ./memory/` + `mem0ai==2.0.19` (pinned;
   fastembed intentionally NOT installed → dense-only, no BM25).
   `pyproject.toml` records the pin.
5. ✅ Tests (run WITHOUT the live chat endpoint):
   - `tests/test_unit.py` (plain python3, no mem0/live services): **43 checks
     ALL PASS** — policy, context, config env-parsing, flag-off path (one env
     switch disables retrieval/writeback/all), unknown-user guard, timeout→
     degradation.
   - `tests/test_integration.py` (throwaway container on ai-net, live Qdrant
     + LiteLLM): **15 checks ALL PASS** — health, learn (private + household,
     with extraction retries), search (private + household merged),
     list_memories, update, delete, user isolation, timeout→degradation
     (unreachable Qdrant→[] in ~1ms), cleanup.
6. ✅ No bypass: all memory LLM (`/v1/chat/completions`) + embedding
   (`/v1/embeddings`) traffic via `litellm-proxy` (verified in logs).
   `family_kb` verified untouched (18 pts/384-dim/Cosine); `mem0_memories`
   empty after test cleanup.
7. ✅ **Self-deadlock found + fixed** (commit `f592da2d`): `_get_client()`
   held the non-reentrant module `_lock` while calling `_get_config()`
   (which re-acquires the same lock) → the FIRST memory call in a process
   (e.g. `is_healthy()` before any search/learn) hung forever. Found during
   post-rebuild live verification (`faulthandler` traceback: main thread
   blocked in `_get_config`'s `with _lock:` while `_get_client` held it).
   Chat-path functions were immune only because they call `_get_config()`
   first — latent for Phase 4/8 (`/api/memory/health`). Fix: resolve config
   outside the lock. Regression test: first `is_healthy()` after
   `_reset_singleton()` must return <5s (worker-thread join so a regression
   hangs the check, not the suite). Unit tests **45/45 PASS** (was 43).
   Fixed code verified vs live Qdrant (host, `localhost:6333`): `is_healthy()`
   → True, no hang. Live-container flag-off check (old image, safe path):
   `MEMORY_ENABLED=false` → search/learn/list all `[]` in 0ms.
8. ✅ Side fix (commit `91d5ee91`): `.gitignore` `logs/` line had an inline
   comment (invalid in gitignore) → logs were never actually ignored; two
   tracked log files untracked. (Was tripping the backup script's git-clean
   check.)
9. ✅ **Admin timeout budget** (this commit): second live rebuild verified
   the deadlock fix (`is_healthy` → True promptly) and the full live
   integration suite ran in-container: **14/15 PASS** (learn private +
   household, search merged, list, update, isolation, degradation,
   cleanup). The one FAIL: `delete_memory` returned False because a single
   mem0 `delete` measures **~2.3s** (probe: add 10s/5.2s cold/warm, get_all
   6ms, delete 2.3s, delete_all 0.4s) — over the 1.5s retrieval budget, so
   the op succeeded in the background but the caller got False. Fix: admin
   ops (`update_memory`/`delete_memory`/`delete_user_memories`) use a new
   `MEMORY_ADMIN_TIMEOUT_MS=10000` budget (store ops, no LLM, non-hot-path).
   Integration degradation test also fixed to pass a dummy api_key so it
   exercises the real unreachable-Qdrant path (was testing missing-creds).
   Unit tests **47/47 PASS**. `mem0_memories` empty + `family_kb` untouched
   after the run.

**Gate to Phase 3: MET (2026-08-27).** Module passes tests standalone; manual
step B#3 done with post-checks green; one env switch disables it (unit + live
container flag-off check). **Phase 3 gate also MET (2026-08-27):** extended
live suite 28/28 — isolation (chuck vs memory_test, both directions),
household fact visible to chuck, unknown principal → no retrieval/writeback,
secret-like content not stored, no raw keys in any Qdrant payload. OWUI/
master-key traffic never reaches skill-runner (D5); unmapped keys → `unknown`
(no memory access).

**Phase 2 gotchas (Phase 3+ must know):**
- mem0 REWRITES extracted facts into normalized phrasing ("User prefers oat
  milk lattes…") — don't match on the raw user text; use a surviving keyword.
- matrix-coder extraction is SLOW (2–5s) + occasionally emits JSON mem0's
  parser rejects ("Error parsing extraction response") → the fact is NOT
  stored; a retry loop (re-learn + verify via `list_memories`) is required.
- First memory op after startup includes mem0 init; if it exceeds the
  retrieval timeout it degrades (returns []) but the next op succeeds.
- `delete_all()` still takes top-level `user_id` (unlike search/get_all).
- Qdrant collection-info field is `points_count` (not `points`).

## Phase 4 checklist (CODE COMPLETE 2026-08-27; awaiting MANUAL STEP B + live verification)

**Scope:** automatic pre-request retrieval — relevant memory injected into
the system prompt before the LLM call, at BOTH chat call sites, non-fatal.

1. ✅ **ONE render path** — `interface.render_context(user_id, query) -> str`
   (search private + household → dedupe → threshold → budgeted
   `<long_term_memory>` block). Returns "" on error/timeout/flag-off/unknown
   user. Both call sites use it, so behavior stays identical:
   - `main.py::_chat_direct` — identity from the request contextvar
     (`get_current_context()`); block injected between system prompt and
     user message; wrapped in try/except (chat never breaks on memory).
   - `siri_chat/skill.py::_memory_block` — lazy `from memory import interface`
     (skill stays stdlib-importable standalone, loaded via importlib);
     identity from `job.user_id` (Phase 3); block injected into SYSTEM_PROMPT.
2. ✅ **Relevance gate** — `MEMORY_SCORE_THRESHOLD` (default 0.5; 0 disables)
   in `config.py` (`_env_float`) + applied in `search_memory` (both private
   and household branches) — unrelated memories are dropped before they can
   enter an unrelated task's context. `.env` + compose passthrough added.
3. ✅ **Request-level switch** — `ChatRequest.memory: Optional[dict]`;
   `{"enabled": false}` → `mem_on=False` in `api_chat` → `_chat_direct(...,
   memory_enabled=False)` (no search at all) + `dispatch_job(...,
   memory_enabled=False)` → `Job.memory_enabled` → skill skips injection.
4. ✅ **Instrumentation** — structured log per request, no secrets:
   `memory: user_id=… hits=… chars=… latency_ms=…` (main.py INFO) and
   `Memory: user_id=… block_chars=… latency_ms=…` (siri_chat job log).
5. ✅ **Unit tests +7** (`test_score_threshold`, fake client): high-score
   kept, below-threshold dropped, household at threshold kept, threshold=0
   keeps low scores, `render_context` empty when all below threshold, config
   parsing (0.7 parsed, invalid → default 0.5). **59/59 unit + 29/29
   identity pass.**
6. ✅ **Import/degradation smoke** (throwaway container, new code mounted
   ro): `main` + `siri_chat` import OK; `_memory_block` with no creds
   degrades to "" (search timeout → empty block, chat unaffected);
   `score_threshold` default 0.5.
7. ✅ **Live verification (post-rebuild, 2026-08-27)** — extended suite
   **35/35 ALL PASS** (throwaway container, live Qdrant/LiteLLM): relevant
   query injects the learned fact (len=388); unrelated nginx query → no
   coffee fact (threshold — genuine, no timeout); memory_test block has own
   tea, never chuck's coffee; unknown principal → empty block; retrieval
   flag off → empty block. End-to-end over HTTP (baked image): learned
   "oat milk flat whites" → `/api/chat` "What milk should I use…?" →
   "You should use oat milk, as you've recently switched to drinking oat
   milk flat whites in the morning" (preference used, not restated);
   `memory.enabled=false` → no embeddings/Qdrant/memory line (zero
   retrieval); cold start → `memory: hits=0 latency_ms=3291` (budget
   exceeded → degraded, chat still answered); warm → `hits=1 chars=377
   latency_ms=110`. Test fix: mem0 `update()` stores RAW text (no LLM
   re-extraction) → verify via list + matching query (old natural-question
   probe scored 0.45 < 0.5 gate — correct gate behavior, wrong probe).

**Gate to Phase 5: MET (2026-08-27).** Retrieval is live at both call sites,
non-fatal, budgeted, identity-scoped, switchable per request, instrumented,
and verified end-to-end. `mem0_memories` 0 pts + `family_kb` 18 pts after
the run. Backup taken at the gate.

**Phase 4 gotchas (Phase 5+ must know):**
- **mem0 `update()` stores the RAW text** (no LLM re-extraction; it only
  re-embeds). A raw one-liner scores ~0.45 against a natural question —
  below the 0.5 relevance gate (correct: weak matches aren't injected).
  Verify updates via `list_memories` + a query that matches the raw text.
  (Bite: the Phase 4 update-verification test failed on exactly this.)
- **Cold embedding calls** (first op after a restart, ~4.7s) can exceed the
  1.5s retrieval budget → that one search degrades to [] (chat proceeds);
  the next op succeeds (warm, ~44ms). Positive live checks retry up to 3x;
  negative checks stay single-shot (empty block is a valid "no injection").
- **First memory op in a fresh process** includes mem0 init inside the
  timeout budget → expect one degraded retrieval right after a rebuild
  (observed: `memory: hits=0 latency_ms=3291` on the first post-rebuild
  request; warm requests are ~110ms).

## Phase 5 checklist (GATE MET 2026-08-27)

**Scope:** post-turn learning — writeback into the chat loop (plan Phase 5).

1. ✅ **Writeback after successful response only** (plan item 1) —
   `_chat_direct` success path (main.py) + `siri_chat` final answer
   (skill.py). Synchronous for v1. Non-fatal (try/except; a writeback
   failure never breaks the answer). Budgeted via `MEMORY_WRITEBACK_TIMEOUT_MS`
   (30s — extraction runs an LLM). Gated by the request-level memory switch
   (`memory.enabled=false` → no retrieval AND no writeback; privacy).
   Identity: `_chat_direct` from the request contextvar; siri_chat from
   `job.user_id` (Phase 3). `unknown`/`service` → no writeback
   (`_valid_user` guard).
2. ✅ **Pre-filter** (plan item 2) — existing `policy.py` on the real
   writeback path: secret/credential regex reject, system/tool content
   stripped, no-user-content reject. (Unit + live checks.)
3. ✅ **Extraction instructions** (plan item 3) —
   `policy.DEFAULT_EXTRACTION_INSTRUCTIONS` (durable-facts-only inclusion
   list; NEVER-store list incl. secrets + prompt-injection directives;
   consolidation rule; direct-user = highest trust) passed to mem0 as
   `custom_instructions` (highest priority in mem0's prompt). Env override
   `MEMORY_EXTRACTION_INSTRUCTIONS` (empty = built-in). Provenance metadata
   on every stored fact: `source` (chat/direct_user), `importance`
   (normal/high), `confidence` (normal/high), `agent`, `turn_id` — mem0
   2.0.19 strips identity keys (`user_id`/`agent_id`/`run_id`/`actor_id`)
   from `add(metadata=...)` and treats top-level `agent_id`/`run_id` kwargs
   as *scope* keys (which would also scope mem0's internal dedup search
   per-turn, breaking cross-turn dedup), so provenance uses the free-form
   keys `agent`/`turn_id`.
4. ✅ **Conflict handling** (plan item 4) — mem0 2.0.19 OSS is ADD-only
   (no in-place update; supersede semantics live in the hosted v3 API):
   the extraction prompt instructs the LLM to emit changed preferences as a
   self-contained supersede statement ("User switched from X to Y"); the
   old fact is NOT duplicated; the context block carries both and sorts
   score-desc then recency-desc so the newer statement leads. Revisit:
   nightly LLM consolidation job (Phase 9).
5. ✅ **Explicit commands** (plan item 5) — `remember`/`forget` intents in
   `/api/chat` (imperative-only patterns: sentence-start or "please …";
   "do you remember …" stays chat). `remember` → `remember_direct`
   (source=direct_user, importance=high, confidence=high); `forget` →
   `forget_matching` (targeted delete of above-threshold hits; returns
   deleted texts). Admin REST endpoints stay in Phase 8. **Deterministic
   remember (post-rebuild fix):** `remember_direct` stores with
   `infer=False` (raw text, no LLM extraction) after stripping the
   imperative prefix (`policy.strip_remember_prefix`) — an explicit
   "remember this" must not silently fail on extraction-LLM flakiness
   (observed live: malformed JSON → stored=false). Policy pre-filter
   (secret reject) still applies.
6. ✅ **Write failures non-fatal** (plan item 6) — all new paths return
   []/False + log; verified degraded in throwaway container (no creds →
   [] promptly, no raise).
7. ✅ **Tests** — unit +24 (83/83: provenance metadata, remember_direct,
   forget_matching, extraction-instruction config); extended live suite +9
   (secret turn not stored; remember_direct persists + retrievable +
   `turn_id` metadata; changed preference → supersede statement stored,
   old fact not duplicated, rendered block carries the new fact;
   prompt-injection directive not stored). Identity 29/29.
8. ✅ **Smoke** (throwaway container, host code ro) — main + siri_chat
   import OK; intent detection correct (incl. no false positive on
   questions); flag-off writeback clean no-op; `warmup()` + first-turn
   writeback verified in a warm process (warmup ~3s; learn ~6s).
9. ✅ **Cold-start fix** — `interface.warmup()` (eager mem0 init,
   idempotent, non-fatal) runs in a background thread at skill-runner
   startup (lifespan hook in main.py), so the one-time init cost is NOT
   paid inside the first chat turn's 30s writeback budget (a cold first
   turn otherwise timed out the writeback and silently lost its facts).
10. ✅ **Live verification (post-rebuild)** — extended suite 48/48 (host
   code, pre-fix rebuild) + post-rebuild e2e on the final image: chat
   preference → stored (`source=chat`) → next chat uses it; `remember`
   intent → stored verbatim (4.1s, `infer=False`) + retrieved (hits=1,
   218ms); `forget` intent → deleted (0.44s); writeback latency ~6s
   warm (acceptable; note for Phase 9).
11. ✅ Cleanup: `mem0_memories` back to 0, `family_kb` 18. Commit +
    backup.

**Gate to Phase 6: MET (2026-08-27).** Phase 6 (optional MCP memory
tools) is additionally gated by the plan on "memory count stays small
after a week of use" — Phase 7 (jobs/agents/skills identity propagation)
has no such gate and can start immediately if preferred.

**Phase 5 gotchas (Phase 6+ must know):**
- mem0 2.0.19 strips the identity keys (`user_id`/`agent_id`/`run_id`/
  `actor_id`) from `add(metadata=...)` and treats top-level `agent_id`/
  `run_id` kwargs as *scope* keys — a scope key also scopes mem0's internal
  existing-memories search, so a per-turn `run_id` scope would break
  cross-turn dedup. Provenance is stored under the free-form keys `agent` /
  `turn_id` (mem0 result conversion puts free-form payload keys under
  `metadata`; the four identity keys are promoted to top-level result
  fields).
- mem0 2.0.19 OSS is ADD-only: the extraction prompt is additive
  ("sole operation is ADD"); changed preferences are stored as a new
  self-contained supersede statement (the prompt instructs the LLM to emit
  "User switched from X to Y"), the old fact remains, and `linked_memory_ids`
  is unreliable (observed null). Supersede semantics exist only in the
  hosted v3 API. Context rendering sorts score-desc then recency-desc so the
  newer statement leads. Revisit: nightly LLM consolidation job (Phase 9).
- Cold start: the first mem0 op in a fresh process pays the one-time init
  (lazy import + Qdrant connect, ~3s) inside the 30s writeback budget;
  with a slow LLM round-trip the first turn's writeback can time out and
  silently lose its facts. `interface.warmup()` runs at skill-runner
  startup (background thread, non-fatal) to move the init cost out of the
  first turn's budget.
- The extraction LLM (matrix-coder) occasionally returns malformed JSON
  ("Error parsing extraction response"); mem0 treats a parse failure as
  "nothing extracted" and returns `[]` — indistinguishable from a genuine
  empty extraction. A JSON-validity rule was added to the custom
  instructions; occasional writeback loss remains a known v1 degradation
  (non-fatal by design).
- Writeback is synchronous in v1 (plan decision): every successful chat
  turn runs an extraction LLM call (2–10s) before the response returns;
  budgeted at 30s (`MEMORY_WRITEBACK_TIMEOUT_MS`); revisit (queue/
  background) in Phase 9 if latency proves unacceptable.

## Phase 7 (jobs/agents/skills identity propagation) — status

- [x] `memory/jobctx.py`: `job_identity(job)` (safe extraction of
  user_id/run_id/memory_enabled; None/legacy job → unknown/on),
  `retrieve(job, query)` (gated, non-fatal, returns rendered block or
  ""), `writeback_turn(job, messages, ...)` (gated, non-fatal, source
  default "chat"), `writeback_outcome(job, text, agent)` (durable outcome,
  source=agent_result, confidence=normal, agent provenance tag).
- [x] `memory/__init__.py` exports the four jobctx helpers.
- [x] `siri_ask/skill.py`: retrieval into the system prompt + writeback
  after a successful answer (source=chat), via lazy `from memory import
  jobctx`.
- [x] `morning_brief/skill.py`: retrieval only (personalizes the brief);
  scheduled run under 'service' is a no-op, user-triggered run inherits
  the user. No writeback (brief output is ephemeral news).
- [x] `deep_research/skill.py`: durable OUTCOME writeback at COMPLETION
  only (source=agent_result, run_id correlation) — long-running-job rule
  (working state stays in the Job; only the durable result is stored).
- [x] Skills remain procedural memory: `policy.sanitize_turn` drops
  system/tool content so skill prompts are never stored (unit-tested).
- [x] Unit tests: `test_phase7_jobctx()` (+27 checks: identity
  extraction, gated retrieve/writeback, agent_result provenance,
  skill-content exclusion) → 120/120.
- [x] Integration tests: +5 live checks (scheduled/service writes nothing
  + no leak into the user; user job inherits user + provenance) → suite
  ALL PASS (52 checks executed).
- [x] Smoke (throwaway container): jobctx API + job_identity; all three
  modified skills import + memory hooks present; no-creds degradation is
  a clean no-op (no raise).
- [x] **MANUAL STEP B** — `./homelab.sh rebuild skill-only` (done 2026-08-27;
  image `6a8e759f`).
- [x] Post-rebuild: post-checks green (warmup thread at boot, jobctx baked
  in, health ok) → live integration suite 52/52 (incl. Phase 7) → live
  identity verification (user job → chuck; service job → service, no leak)
  → cleanup (counts 0 / 18).
- [x] Phase 7 gate: identity propagates dispatch → skill → sub-agent;
  scheduled jobs create no personal memory; user jobs inherit the user;
  agent outcomes tagged source=agent_result; skills not copied into Mem0.

**Gate to Phase 8: MET (2026-08-27).** Live identity verified post-
rebuild (user job → chuck; service job → service, no personal memory).

## Phase 8 (administration, observability, backups) — status

**CODE COMPLETE (2026-08-28; awaiting MANUAL STEP B + live admin e2e).**

- [x] Admin REST endpoints (admin-key protected, `MEMORY_ADMIN_API_KEY`):
  `GET /api/memory/users/{user_id}` (list/search: `q`, `scope`, `limit`),
  `PATCH /api/memory/{memory_id}`, `DELETE /api/memory/{memory_id}`,
  `DELETE /api/memory/users/{user_id}` (`?export=true`),
  `GET /api/memory/health`. New `memory/admin.py` bypasses `_valid_user`
  (admin may manage any user incl. service/household); all ops non-fatal,
  admin timeout budget. Auth: unset key → 503, bad/missing → 403, never
  logs the key.
- [x] CLI wrapper `cli/memory-admin.sh` (health / list / search / update /
  delete / delete-user). Reads the admin key from `MEMORY_ADMIN_API_KEY` or
  `MEMORY_ADMIN_KEY_FILE`; base URL from `SKILL_RUNNER_URL`.
- [x] Observability: dependency-free `memory/metrics.py` (thread-safe
  counters + histograms + per-user gauge; Prometheus text exposition; no
  secrets). Wired into the interface: search/writeback latency + status,
  hit/stored counts, errors by op. `GET /metrics` endpoint (unauthenticated,
  Prometheus-scraped). skill-runner added to `prometheus/prometheus.yml`
  (scrape `host.docker.internal:8091/metrics`). Structured logs already carry
  memory_id / user_id (never secrets).
- [x] Backups: `scripts/backup-memory.sh` kept current (.env + Qdrant
  snapshot + git-clean check). **Restore tested end-to-end** with a
  non-production user (`restore_test`): stored → snapshot → deleted live →
  restored into a throwaway Qdrant (port 16333) → full text + metadata
  recovered (text under the `data` payload key; provenance intact).
- [x] `.env` + compose passthrough: `MEMORY_ADMIN_API_KEY` (safe default
  empty = admin disabled / 503).
- [x] Tests: unit 145/145 (+25 Phase 8: admin bypass/scope/search/
  non-fatal + metrics exposition); live integration 60/60 (+8 Phase 8:
  admin list/search/health + metrics no-secrets); REST smoke 15/15 (auth
  403/503/200, /metrics Prometheus text, response shapes).
- [x] MANUAL STEP B: `./homelab.sh rebuild skill-only` (done 2026-08-28
  ~01:00; image 2026-08-28T00:59:57Z). Post-checks green: litellm alive,
  skill-runner `{"status":"ok"}`, clean startup + mem0 warmup (~4s),
  litellm-proxy uptime unchanged (separate project).
- [x] Post-rebuild live admin e2e (full cycle, non-production user
  `memory_test`): seed 2 → list (2) → semantic search (ranked) → PATCH
  update (verbatim, 200) → single DELETE (200) → DELETE user
  `?export=true` (export + delete) → list 0. CLI `health`/`list`/`search`
  green. Auth: admin key 200, bad key 403, no key 403. `/metrics` →
  Prometheus text (counters/histograms/per-user gauge). Admin key absent
  from logs (0 grep hits). Counts back to 0 / 18.
- [x] VictoriaMetrics scrape wiring: 3 fixes, all committed —
  (a) promscrape does NOT hot-reload by default →
  `--promscrape.configCheckInterval=30s` (`b04a99b7`; hot-reload
  CONFIRMED working — target changes applied without restart);
  (b) `host.docker.internal` = docker0 gateway (172.17.0.1), but
  skill-runner binds THOR_IP only → scrape target retargeted (`b824aa99`);
  (c) alias `thor` collides with the HOST's own hostname (resolves to
  127.0.1.1 from inside containers) → renamed `thor-lan` (`35c9b03b`).
  Needs ONE container recreate (manual, below) for the extra_hosts
  entry, then `up{job="skill-runner"}=1`. **DONE (2026-08-28):** recreate
  applied the `thor-lan` extra_hosts; target UP; `up{job="skill-runner"}=1`;
  all 12 `memory_*` series present; counters accumulating live.
- [x] Phase 8 gate: admin ops exercised manually ✅; restore test current ✅
  (2026-08-28); scrape verified ✅.

**Phase 9 (hardening & migration readiness) — started 2026-08-28:**
- [x] Pin versions: `mem0ai` (already 2.0.19), `litellm` → `v1.92.0`,
  `qdrant` → `v1.18.1` — committed `f1c63336`; gate backup taken
  (`env-20260828-0122.env` + `mem0_memories-20260828-0122.snapshot`).
- [ ] MANUAL STEP D: `./homelab.sh rebuild ai-only` (recreates all 10
  ai-core services with pinned images — litellm, qdrant, owui, redis,
  searxng+valkey, crawl4ai, family-wiki, presenton, litellm-db; data on
  bind mounts persists), then MANUAL STEP B: `./homelab.sh rebuild
  skill-only` (fresh pooled HTTP client to the recreated litellm).
- [ ] Post-rebuild verify: litellm health + `matrix-coder` + `embeddings`
  still work (litellm version UNCHANGED — v1.92.0 was already running —
  so this is a regression check, not a version-change check); qdrant
  1.18.1 serving both collections (counts 0 / 18); skill-runner health.
- [ ] Least privilege: Qdrant collection ACLs; memory-service credential
  minimal model access. (Qdrant 0.0.0.0:6333 stays per decision §0.5.)
- [ ] Regression suite: identity isolation, household scope, secret
  filtering, prompt-injection boundary, outage degradation, embedding-dim
  consistency.
- [ ] Embedding-migration procedure (PDF §9): document v1→v2 alias/
  collection cutover runbook (NO live migration).
- [ ] Feature-flag review: `MEMORY_ENABLED=false` end-to-end.

**Gate to Phase 9: MET (2026-08-28).** Admin ops exercised manually
(post-rebuild e2e on `memory_test`); restore test current (verified
2026-08-28); scrape verified — `up{job="skill-runner"}=1`, all 12
`memory_*` series in VictoriaMetrics. **Next: Phase 9** (hardening &
migration readiness: pin mem0ai/litellm/qdrant, least-privilege review,
regression suite, embedding-migration procedure).

**Manual step (monitoring-only, no AI services touched) — DONE 2026-08-28:**
```
docker compose --env-file .env -f compose/compose.monitoring.yml up -d --force-recreate victoria-metrics
```
Recreated ONLY victoria-metrics (grafana/node-exporter/cadvisor untouched;
data persisted in `/home/chuck/data/victoria-metrics`). Applied the
`thor-lan` extra_hosts entry (creation-time). Verified: target up,
`up{job="skill-runner"}=1`, all 12 `memory_*` series present.

**Phase 8 gotchas:**
- **Admin key ≠ user keys.** `MEMORY_ADMIN_API_KEY` is a SEPARATE secret from
  `SKILL_RUNNER_API_KEY` (the user key). `_require_admin()` only accepts the
  admin key; a valid user key is NOT admin. Unset admin key → 503 (admin
  disabled, fail-safe); bad/missing → 403. The key value is never logged.
- **Admin bypasses `_valid_user` by design.** The chat path rejects
  `unknown`/`service`/`household` (no personal memory), but the admin path
  must be able to inspect/manage ANY user (including service + household)
  for administration. `admin.list_user`/`delete_user` call the interface
  primitives directly (which do NOT apply `_valid_user`), so the admin
  identity is the trust boundary — hence the admin-key gate.
- **Qdrant payload text key is `data`, not `memory`/`text`.** When inspecting
  raw Qdrant points (restore verification, debugging), the stored text is
  under the `data` payload key; `text_lemmatized` is the lemmatized copy.
  mem0's `list`/`search` normalize it to a `memory`/`text` field, but raw
  Qdrant scroll shows `data`.
- **Restore is to a throwaway Qdrant, never the live one.** The restore test
  spins up a throwaway `qdrant/qdrant` on port 16333 (never 6333) and
  recovers the collection there. The live Qdrant is never overwritten by a
  restore test.
- **Metrics are process-local.** `memory/metrics.py` is an in-process
  singleton; counters reset on skill-runner restart. That's fine for
  Prometheus (it scrapes current values + computes rates). No persistence.

## Phase log

- **2026-08-28** — **Phase 9 started: version pinning (item 1) done +
  committed (`f1c63336`).** Recon: running litellm = EXACTLY 1.92.0
  (verified `litellm-1.92.0.dist-info` in the container's venv; image
  built 2026-07-03; matches config header's tested line per D8) and
  running qdrant = 1.18.1 (GET / version API). Both exact tags verified
  to exist upstream (`ghcr.io/berriai/litellm:v1.92.0` manifest OK;
  `qdrant/qdrant:v1.18.1` — note Qdrant tags carry a `v` prefix, so
  `1.18.1` alone 404s). Pins are ZERO-DRIFT: they lock the exact
  versions already running, removing floating-tag risk on the next
  rebuild without any version jump. `mem0ai` already pinned 2.0.19.
  Gate backup taken (`env-20260828-0122.env`,
  `mem0_memories-20260828-0122.snapshot`; tree clean at `f1c63336`).
  Awaiting MANUAL STEP D (`rebuild ai-only`) + STEP B (`rebuild
  skill-only`).

- **2026-08-28** — **Phase 8 GATE MET.** Final recreate applied the
  `thor-lan` extra_hosts (`192.168.4.54`); target `thor-lan:8091/metrics`
  UP; `up{job="skill-runner"}=1`; all 12 `memory_*` series present in
  VictoriaMetrics (search/writeback counters+latency histograms, hit/stored
  totals, per-user gauge); counters accumulating live. Phase 8 complete:
  admin REST + CLI + metrics + backups/restore all live-verified.
  Next: Phase 9 (hardening & migration readiness).

- **2026-08-28** — **Phase 8 scrape wiring: 3 fixes, 1 recreate left.**
  VictoriaMetrics recreate (manual) done; `configCheckInterval=30s` live.
  Hot-reload CONFIRMED (target changes applied without restart). Two more
  scrape fixes found + committed: (b) `host.docker.internal` is the
  docker0 gateway (172.17.0.1) — skill-runner binds THOR_IP only, so the
  scrape was refused; retargeted via extra_hosts (`b824aa99`). (c) alias
  `thor` collides with the host's OWN hostname (`127.0.1.1 thor` in host
  /etc/hosts → resolves to 127.0.1.1 from inside containers); renamed
  `thor-lan` (`35c9b03b`). Left: one recreate for the extra_hosts entry
  (creation-time) → verify `up{job="skill-runner"}=1` → Phase 8 gate MET.

- **2026-08-28** — **Phase 8: MANUAL STEP B done + live admin e2e green.**
  Rebuild 01:00 (image 00:59:57Z). Post-checks green (litellm alive,
  skill-runner ok, clean startup, mem0 warmup ~4s, litellm untouched).
  Live admin e2e (non-production `memory_test`): seed 2 → list 2 → search
  ranked → PATCH verbatim → single DELETE → delete-user `?export=true`
  (export+delete) → 0. CLI health/list/search green. Auth 200/403/403.
  `/metrics` Prometheus text live. Admin key absent from logs. Counts back
  to 0 / 18. **Scrape gap found:** VictoriaMetrics (v1.145.0, the
  "Prometheus" in this stack) does NOT hot-reload `--promscrape.config`
  by default, so the Phase 8 `skill-runner` job was not picked up. Fix:
  `--promscrape.configCheckInterval=30s` (`b04a99b7`) + one container
  recreate (manual). Next: recreate victoria-metrics → verify
  `up{job="skill-runner"}=1` → Phase 8 gate MET.

- **2026-08-28** — **Phase 8: CODE COMPLETE** (administration,
  observability, backups). New `memory/admin.py` (admin ops that bypass the
  `_valid_user` gate; non-fatal, admin timeout budget) + `memory/metrics.py`
  (dependency-free Prometheus counters/histograms/gauge, no secrets) +
  `cli/memory-admin.sh` (health/list/search/update/delete/delete-user).
  `main.py`: admin-key protected REST endpoints (`MEMORY_ADMIN_API_KEY`,
  distinct from user keys; unset → 503, bad → 403) + `GET /metrics`.
  Interface instrumented (search/writeback latency+status, hit/stored,
  errors by op). skill-runner added to the Prometheus scrape config. `.env`
  + compose passthrough for `MEMORY_ADMIN_API_KEY`. **Restore tested
  end-to-end** (non-production user `restore_test`): stored → snapshot →
  deleted live → restored into a throwaway Qdrant (port 16333) → full text
  + metadata recovered. Unit 145/145 (+25); live integration 60/60 (+8);
  REST smoke 15/15. Counts back to 0 / 18. Next: MANUAL STEP B
  (`./homelab.sh rebuild skill-only`) + live admin e2e + gate.

- **2026-08-27** — **Phase 7 gate MET.** Rebuild (`6a8e759f`). Post-
  checks green (warmup thread at boot, mem0 client warm; `jobctx.py`
  baked in with all 4 helpers). Live integration suite 52/52 (incl. 5
  Phase 7 checks; fixed a flaky count-comparison check that hit the 1.5s
  retrieval-timeout degradation — now asserts on the specific service
  content + retries the read). Live identity verification (real dispatch
  path): user-triggered `morning_brief` via `/api/chat` (chuck's key) →
  job log `Identity: user_id=chuck`, memory retrieve `user_id=chuck
  block_chars=0`; service `siri_ask` via `/skills/siri_ask` (no context)
  → job log `Identity: user_id=service`, Qdrant counts stayed 0/0 (no
  leak, no service memory). Counts back to 0 / 18. Phase 7 complete.
  Next: Phase 8 (admin REST endpoints) or Phase 6 (optional MCP) —
  awaiting direction.

- **2026-08-27** — **Phase 7: CODE COMPLETE** (jobs/agents/skills
  identity propagation; awaiting MANUAL STEP B). New `memory/jobctx.py`
  is the single propagation path (job_identity / retrieve / writeback_turn
  / writeback_outcome — all gated, non-fatal, lazy-import). Wired into
  siri_ask (retrieval + writeback, source=chat), morning_brief
  (retrieval only; scheduled 'service' run is a no-op, user-triggered run
  inherits the user), deep_research (durable outcome writeback at
  completion only, source=agent_result, run_id correlation). Skills stay
  procedural memory (sanitize_turn drops system/tool content — unit-
  tested). Unit 120/120 (+27); identity 29/29; integration suite ALL PASS
  (52 checks, +5 Phase 7 live checks: service writes nothing + no leak;
  user job inherits user + provenance). Smoke green. Next: MANUAL STEP B
  (`./homelab.sh rebuild skill-only`) → post-checks → live verification →
  Phase 7 gate.

- **2026-08-27** — **Phase 5 gate MET.** Second rebuild (deterministic
  `remember` fix, `a28cc639`). Post-checks green (warmup thread at boot,
  mem0 client warm in ~6s; `infer=False` + `strip_remember_prefix`
  baked in). Live e2e full cycle: `remember` intent → stored verbatim
  "my favorite hiking trail is Eagle Creek." in 4.1s (`infer=False`,
  no LLM in the loop — the earlier malformed-JSON failure class is
  gone); a follow-up chat turn retrieved it (hits=1, 218ms); `forget`
  intent → deleted (0.44s). Counts back to 0 / 18. Phase 5 complete.
  Next: Phase 6 (optional MCP; plan-gated on a week of use) or Phase 7
  (jobs/agents/skills identity propagation) — awaiting direction.

- **2026-08-27** — **Phase 5: deterministic `remember` fix** (post-
  rebuild e2e). Post-rebuild checks green (warmup thread started at boot,
  mem0 client warm; baked-in code verified). E2E: preference stated in
  chat → stored (`source=chat`) → follow-up used it; `forget` intent →
  deleted (0.5s). But the `remember` intent failed live (`stored=false`):
  `remember_direct` routed through the extraction LLM, which returned
  malformed JSON ("Error parsing extraction response") — mem0 treats a
  parse failure as "nothing extracted". Fix: `remember_direct` now stores
  verbatim with `infer=False` (no LLM in the loop) after stripping the
  imperative prefix (`policy.strip_remember_prefix`: "remember that …" /
  "please remember …" / "note that …" / "keep in mind …"; word-boundary
  safe — "Remembering …" untouched); `learn_from_turn` gained an `infer`
  param (chat writeback stays `infer=True`). Live probe: stored verbatim
  with full provenance in ~9.5s (embed only). Unit 93/93 (+10). Awaiting
  MANUAL STEP B (rebuild) + remember e2e re-test.

- **2026-08-27** — **Phase 5 live-suite fixes** (pre-rebuild). First live
  suite run 41/43: (1) `run_id` missing from stored metadata — mem0 2.0.19
  strips identity keys from `add(metadata=...)` and treats top-level
  `agent_id`/`run_id` kwargs as scope keys (which would also scope mem0's
  internal dedup search per-turn, breaking cross-turn dedup); provenance
  now stored under free-form keys `agent`/`turn_id`. (2) Consolidation
  check failed — mem0 2.0.19 OSS is ADD-only (additive extraction prompt,
  no in-place update; supersede semantics live in the hosted v3 API):
  changed preferences are stored as a self-contained supersede statement,
  old fact remains, `linked_memory_ids` unreliable (observed null). Live
  test now asserts: supersede statement stored, old fact not duplicated,
  rendered block carries the new fact; context rendering sorts score-desc
  then recency-desc; extraction prompt gained a supersede-statement rule +
  JSON-validity rule (matrix-coder occasionally returned malformed JSON —
  mem0 treats a parse failure as "nothing extracted"). (3) Cold-start
  writeback: first mem0 op in a fresh process exceeded the 30s writeback
  budget (init + first embed + LLM); added `interface.warmup()` + a
  background warmup thread at skill-runner startup (lifespan hook) so the
  one-time init cost is paid at boot, not in the first turn's budget
  (verified: warmup ~3s, first learn ~6s warm). Unit 83/83; identity
  29/29; main import + lifespan hook smoke green. Extended live suite
  re-running (43 checks).

- **2026-08-27** — **Phase 5 code complete** (post-turn writeback). Both
  chat call sites write back after successful responses only (non-fatal,
  budgeted, switch-gated). Provenance metadata (source/importance/
  confidence/agent_id/run_id) on every stored fact. Built-in extraction
  instructions (durable-facts-only; secrets + prompt-injection excluded)
  via mem0 `custom_instructions` + `MEMORY_EXTRACTION_INSTRUCTIONS` env.
  New `remember`/`forget` intents + `remember_direct`/`forget_matching`.
  Unit 83/83 (+24); identity 29/29; import/intent/degradation smoke green
  in throwaway container. Extended live suite +8 Phase 5 checks. **Awaiting
  MANUAL STEP B** (rebuild) + live verification + end-to-end writeback
  checks. Backup pending at gate.

- **2026-08-27** — **Phase 4 gate MET.** MANUAL STEP B run by Chuck;
  post-checks green; baked-in code verified (render_context/_memory_block/
  score_threshold/MEMORY_SCORE_THRESHOLD=0.5 in the image). Extended live
  suite **35/35 ALL PASS** (was 28; +8 render_context, update verification
  split into 3). One test bug found + fixed (`a350a899`): the update
  verification searched a natural question that scores ~0.45 against the
  RAW updated text (mem0 update stores raw text, no re-extraction) — below
  the new 0.5 gate, so the check failed despite a working update. Correct
  behavior, wrong test → now verifies via list + matching query. End-to-end
  over live /api/chat: learned preference changed the answer (oat milk),
  memory.enabled=false → zero retrieval (verified in logs), instrumentation
  line clean. Collections clean after (0 / 18). **Next: Phase 5**
  (writeback into the chat loop).
- **2026-08-27** — **Phase 4 code complete** (automatic pre-request
  retrieval). ONE render path `interface.render_context` injected at both
  chat call sites (`_chat_direct` + `siri_chat` `_memory_block`, lazy
  import, identity from `job.user_id`). `MEMORY_SCORE_THRESHOLD=0.5`
  relevance gate (config/interface/.env/compose). `ChatRequest.memory`
  per-request switch → `Job.memory_enabled`. Structured instrumentation log
  (no secrets). Unit 59/59 (+7 threshold checks); identity 29/29; import +
  degradation smoke in throwaway container (no creds → empty block, chat
  unaffected). Extended live suite +8 `render_context` checks. **Awaiting
  MANUAL STEP B** (rebuild) + live verification. Backup pending at gate.
- **2026-08-27** — **THIRD MANUAL STEP B + extended live suite 28/28 →
  Phase 2 AND Phase 3 gates MET.** Post-checks green (litellm alive,
  skill-runner ok, clean startup; litellm/qdrant untouched). Baked-in code
  verified in-container (`identity.py` present, new count logic present,
  mem0 2.0.19). Full extended suite (in-container, long timeout): health,
  learn private (tries=3) + household (tries=2), search private + household
  merged, list, **update True + reflected**, **delete True + removed**
  (admin budget fix verified live — the 14/15 blocker is gone), user
  isolation, chuck-vs-memory_test isolation (both directions), household
  visible to chuck, unknown principal → []/[], secret filtered, no fake/real
  key in any Qdrant payload, timeout→degradation, cleanup. One test bug
  fixed: the direct Qdrant payload scan used `GET /collections/{name}/points`
  (404 — removed in Qdrant 1.18) → now `POST /collections/{name}/points/scroll`
  (same gotcha class as the Phase 1 snapshot endpoint). Collection verified
  empty (0 pts) after the run; `family_kb` untouched (18 pts). Backup taken
  at the gate. **Next: Phase 4** (pre-request retrieval middleware).
- **2026-08-27** — **"memory_test_other 1 memory" mystery resolved: no ghost
  write.** The extended live suite run (chuck isolation section) was killed
  mid-run; manual cleanup loop printed pre-delete counts via
  `delete_user_memories()` — which returned `len(list_memories(user))`, and
  `list_memories` MERGES the household scope into EVERY user's view. So
  `memory_test_other` (0 private) reported 1 = the shared household
  "basement" fact; `chuck 2` = 1 private (black coffee) + 1 household;
  `household 1` = basement; `memory_test 0` = degraded count (cold-client
  get_all exceeded the 1.5s retrieval budget → []). `delete_all(user_id=…)`
  only removes that user's own points, so the household fact survived until
  the 4th delete; post-delete leftovers read 0. Collection verified empty
  (0 points), `family_kb` untouched (18 pts). **Fix (`9ded3a1c`):**
  `delete_user_memories` now counts only the user's OWN points (direct
  `get_all` with the user filter, admin budget) so the count matches what is
  actually deleted; +5 unit regression checks (52/52). Phase 3 identity code
  committed in the same commit (see Status). Backup `env-20260827-0122` +
  snapshot taken. **Next: THIRD MANUAL STEP B** → extended live suite →
  Phase 2 + Phase 3 gates.
- **2026-08-24** — Phase 0 inventory complete (full evidence:
  `memory_todo.md` Appendix A). 768-dim embedding verified live. 10 deltas
  vs. the source PDF identified (`memory_todo.md` §1.2).
- **2026-08-25** — Decisions 1–5 locked by Chuck; `memory_todo.md` updated;
  this file created. Operational constraint added: all container lifecycle
  steps (restarts/rebuilds) are manual, run by Chuck between model turns
  (`memory_todo.md` §3.0). Ready for Phase 1.
- **2026-08-26** — **Phase 1 complete.** Commits: `0429d5eb` (backup script +
  embedding alias), `14c9a4ff`+`ec5966a8`+`0bacd50e` (`drop_params` fix +
  snapshot-parsing fixes). Manual step A run twice (both post-check sets
  green). Restore test: throwaway qdrant on 16333 with snapshot mounted ro —
  Qdrant 1.18 endpoint is `PUT /collections/{name}/snapshots/recover` with a
  `file://` URI and `priority:"snapshot"` (old `POST .../restore` is gone;
  default `replica` priority restores EMPTY). Verified restored `memory_test`
  point (id 5dc6a78f…, payload `data` field) + vector search score 0.82.
  Cleanup: `memory_test` points deleted from live collection (empty, ready
  for Phase 2); throwaway containers removed.
  **mem0 2.0.19 gotchas (Phase 2 must know):** `search()`/`get_all()` take
  `filters={"user_id":…}` + `top_k` (no top-level `user_id`/`limit`); OpenAI
  embedder hardcodes `encoding_format=float` → `drop_params: true` on
  `homelab-embedding-v1` (done); set `MEM0_TELEMETRY=false` in compose env
  (PostHog telemetry ON by default); mem0 auto-creates `mem0migrations`
  collection (recreated on init — no backup needed); payload text field is
  `data`; extraction parse failures are silent (memory NOT stored) → retry
  loop required. **Qdrant 1.18:** collection create is `PUT /collections/{name}`.
  **Pre-existing, unrelated:** `plausible` restart loop (createdb failure);
  LiteLLM `GET /v1/skills` 500 (missing ANTHROPIC_API_KEY).
- **2026-08-26** — **Phase 2 code complete + tests green** (awaiting MANUAL
  STEP B). Built `skills/runner/memory/` (config/policy/context/client/
  interface; lazy mem0 import, thread-pool timeouts, non-fatal public
  surface, household scope, secret filter). Dedicated model-restricted
  LiteLLM key `memory-service` (top-level `models`). `MEMORY_*` env in `.env`
  + compose (16 vars). Dockerfile + pyproject pin `mem0ai==2.0.19`. Unit
  tests **43 PASS** (plain python3, no mem0); integration tests **15 PASS**
  (throwaway container, live Qdrant + LiteLLM: learn/search/list/update/
  delete/isolation/degradation/cleanup). No LiteLLM bypass (all traffic via
  litellm-proxy); `family_kb` untouched; `mem0_memories` empty. Not yet wired
  into `api_chat` (Phase 4/5). **2026-08-26 (later)** — First MANUAL STEP B
  run by Chuck (image rebuilt 02:27Z). Post-checks green: litellm
  `"I'm alive!"`, skill-runner `{"status":"ok"}`, clean startup logs, no
  restart loops. Live verification (`docker exec -i skill-runner python3`)
  found the singleton **self-deadlock**: `iface.is_healthy()` as first call
  hung >60s (faulthandler: blocked in `_get_config` `with _lock:` while
  `_get_client` held it). Root cause: non-reentrant lock re-acquired by the
  same thread. Fixed in `f592da2d` (config resolved outside the lock) +
  regression test (45/45 unit). Also fixed `.gitignore` logs pattern
  (`91d5ee91`). Backup re-run (env-20260826-1154 + snapshot).
  **Second MANUAL STEP B** (image 12:23Z) — post-checks green; fix verified
  baked in. Live integration suite in-container: 14/15 (delete_memory
  budget FAIL — mem0 delete ~2.3s > 1.5s retrieval budget). Latency probe
  (warm client): add 10.0s/5.2s, get_all 6ms, delete 2.3s, delete_all 0.4s.
  Fix: `MEMORY_ADMIN_TIMEOUT_MS=10000` budget for update/delete/delete_user
  (config/interface/compose/.env) + degradation test now uses dummy api_key
  (real network-failure path). Unit 47/47. `mem0_memories` empty, `family_kb`
  untouched (18 pts). **Next: THIRD MANUAL STEP B** → re-run live suite
  (expect 15/15) → Phase 2 gate → Phase 3.