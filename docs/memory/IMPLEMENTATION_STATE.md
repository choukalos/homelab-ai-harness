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
- **Next: Phase 4** (automatic pre-request retrieval — middleware injection
  in `_chat_direct` + `siri_chat`, ONE render path, request-level switch,
  instrumentation). Not yet started.
- Last updated: 2026-08-27.

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
| `skills/runner/main.py` | `api_chat` (~1790), `_chat_direct` (~1912), `ChatRequest` (~1211), `dispatch_job` (233), `LiteLLMClient` (391) |
| `skills/siri_chat/skill.py` | `SYSTEM_PROMPT` (~99) — second injection point |
| `skills/runner/scheduler.py` | jobs (service identity) |
| `litellm/config.yml` | `model_list` (add `homelab-embedding-v1`), `mcp_servers` |
| `compose/compose.skill-runner.yml` | add `MEMORY_*` env |
| `compose/compose.ai-core.yml` | qdrant/litellm/open-webui services |
| `skills/runner/pyproject.toml` + `Dockerfile` | add `mem0ai` (pinned) |
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

## Phase log

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