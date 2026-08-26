# Long-Term Memory — Implementation State

> **Handoff file for the implementing model.** Start every phase by reading THIS
> file + `homelab/memory_todo.md` (full plan: phases, gates, tests, non-negotiables).
> Update this file at the end of every phase. Keep < ~5K tokens.
> **No secret values here — ever.** (Key names/paths yes; key contents no.)

## Status

- **Phase 0: COMPLETE** (2026-08-24 inventory; 2026-08-25 decisions locked).
- **Phase 1: COMPLETE** (2026-08-26; all gates green — see phase log).
- **Next: Phase 2** — skill-runner memory core (in-process Mem0, identity map,
  retrieval/writeback hooks, `MEMORY_*` env). Gate: `./homelab.sh rebuild skill-only`
  (MANUAL STEP B).
- Last updated: 2026-08-26.

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

## Phase log

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