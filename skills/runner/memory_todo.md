# memory_todo.md — Long-Term Memory (Mem0) plan & state

> **2026-09-02 note:** this file is a **reconstruction**. The original `memory_todo.md`
> never landed on Thor (it only existed in the Mac pi session history of 2026-08-30/31).
> Rebuilt from: `memory/*.py` docstrings, `compose/compose.skill-runner.yml` comments,
> `.env` values, skill-runner logs, and the 2026-09-02 gap-analysis handoff from the
> Mac pi session. Phase numbers continue the original scheme.

**Owner:** chuck · **Code:** `/home/chuck/homelab/skills/runner/` (memory module: `memory/`)
**Compose:** `/home/chuck/homelab/compose/compose.skill-runner.yml` · **Env:** `/home/chuck/homelab/.env` (gitignored)

> **STATUS 2026-09-02 (post-execution):** Phase 3.1 (identity fix) ✅, X5 memory deleted ✅,
> Phase 11 (scoped endpoints + `mcp_memory` on :8005) ✅, **Phase 11.5 (LiteLLM gateway
> registration → Mac pi gets `memory_search`/`memory_list` with zero Mac-side changes) ✅**,
> Phase 12 (`recent_activity` skill + daily 17:00 CDT schedule + scheduler tz/persistence
> fixes) ✅. Remaining: Phase 13 week-later evaluation (~2026-09-06).

---

## 1. Verified state as of 2026-09-02 (all checked on Thor)

| Item | State | Evidence |
|---|---|---|
| Container | `skill-runner` up since **2026-08-31T23:39:33Z**, healthy | `docker inspect` |
| Flags | `MEMORY_ENABLED/RETRIEVAL/WRITEBACK/HOUSEHOLD=true`; `MEMORY_MCP_ENABLED=false` (dead — no impl, see Phase 6); `MEMORY_DEBUG_LOGGING=false` | `.env` + container env |
| Identity map | `chuck=SKILL_RUNNER_API_KEY,chuck=LITELLM_KEY_CHUCK,dylan=LITELLM_KEY_DYLAN,service=SIRI_KEY_SERVICE` | `.env` line 133 |
| ⚠️ Identity bug | **Dylan's key resolves to `user_id=chuck`** (first-match-wins; `SKILL_RUNNER_API_KEY` = Chuck's + Dylan's LiteLLM keys). See **Phase 3.1** | `identity.py` `resolve()` + key cross-ref |
| Qdrant JWT | `sub=skill-runner`, rw-scoped to `mem0_memories`, **no `exp` claim → never expires**; verified working (scroll OK 2026-09-02) | JWT decode + live query |
| `mem0_memories` | **Exactly 1 point**: `user_id=chuck`, 2026-08-31T17:57:43Z — *"User owns a BMW X5 and inquired about its tire sizes…"* (likely **misattributed**: per KB the X5 is the wife's car) | Qdrant scroll + admin API |
| Dylan's memories | **0 points** | admin `GET /api/memory/users/dylan` |
| LiteLLM keys | `memory-service-v3` (user_id=memory-service, models: `matrix-coder`, `homelab-embedding-v1`, `embeddings` — least-privilege ✓); `chuck-remote`; `dylan-v2`. `SIRI_KEY_SERVICE` is identity-only, not a LiteLLM key | LiteLLM admin API |
| Extraction | model `matrix-coder`; `MEMORY_EXTRACTION_INSTRUCTIONS` empty → built-in conservative policy (`policy.DEFAULT_EXTRACTION_INSTRUCTIONS`); threshold 0.5, top_k 6, max 1500 ctx tokens; household virtual user `household` enabled | `.env` + `policy.py` |
| Writeback | synchronous in v1 (plan §5.1), non-fatal, 30 s budget | `main.py` `_chat_direct` |
| Log history | 2026-08-30: repeated LiteLLM 401s (extraction key rotated during dev: `sk-…M4Wg` → `sk-…WHbg`); 1.5 s retrieval timeouts at 08-30 12:17 and 08-31 12:57; **clean since the 08-31 17:57 writeback** | `logs/skill_runner/skill_runner.log` |
| KB on chat surface | ✅ `MCP_SERVER_KNOWLEDGE_URL` wired; `siri_chat` skill exposes `kb_search`/`kb_get_document`/`kb_list_documents` | compose + `skills/siri_chat/README.md` |
| pi (Mac) | KB only (mcp_knowledge), **no memory wiring** | Mac session (handoff) |
| Open WebUI | talks **directly** to `litellm-proxy:4000` (not skill-runner) → **no KB, no memory** | `docker inspect open-webui` |
| Scheduler | **0 scheduled jobs** | `GET /api/schedule` |
| `~/Code` repos | **Not on Thor** (Mac-only). `GITHUB_ACCESS_TOKEN` present in `.env` → GitHub API is the viable data source for recent-activity | `ls` + `.env` |
| `kb_user` | 3 points incl. manual *"Chuck's recent projects (as of 2026-09-02)"* (Portal v3, blog, …) | Qdrant scroll |
| CLI `--user` flag (Phase 5.2) | **Not implemented**; no `legacy` user exists in code (unmapped key → `unknown`, no retrieval/writeback) | grep of `main.py`, `identity.py` |
| Unrelated | `plausible` in restart loop (`Release.createdb` crash) | `docker logs` |

---

## 2. Phase status (original numbering)

| Phase | Scope | Status |
|---|---|---|
| 2 | In-process Mem0: retrieval before prompt, writeback after, household scope | ✅ done, verified working (retrieve+write cycle 2026-08-31 17:57Z) |
| 3 | Identity: key → user_id map | ✅ done, **shadowing bug fixed in Phase 3.1 (2026-09-02)** |
| 3.1 | P0 identity shadowing fix + conflict warning + regression tests | ✅ **done 2026-09-02** (see §3) |
| 4 | Per-request memory switch (`memory.enabled=false`) | ✅ done |
| 5 | Extraction instructions; explicit `remember`/`forget` intents; writeback policy | ✅ mostly done; instructions empty (defaults); **5.2 CLI `--user` flag not implemented** |
| 6 | Memory MCP server (`MEMORY_MCP_ENABLED`) | ❌ dead flag — **superseded by Phase 11** (scoped endpoints + external `mcp_memory` container); flag can be removed later |
| 7 | Multi-agent (`agent_id`) | reserved |
| 8 | Admin API (`/api/memory/*`, distinct admin key) | ✅ verified: health / users / PATCH / DELETE all key-gated |
| 9 | Least-privilege Qdrant JWT (rw, `mem0_memories` only) | ✅ valid; **no expiry**; re-issue via `scripts/qdrant-jwt.py` (signed with `QDRANT_ADMIN_API_KEY`) |
| 10 | `service` user for scheduler/unattributed jobs | ✅ (`USER_SERVICE`, `MEMORY_USER_KEYS` service entry) |
| 11 | Scoped memory endpoints + `mcp_memory` + pi wiring | ✅ **done 2026-09-02** (pi wiring completed via Phase 11.5 gateway registration — no Mac-side changes) |
| 11.5 | LiteLLM gateway registration (Mac pi access, key-scoped) | ✅ **done 2026-09-02** (server `57edf1fe…`, access group `mcp-memory-chuck` on Chuck's key; Dylan → 403; zero reloads) |
| 12 | Recent-activity capture (scheduled job) | ✅ **done 2026-09-02** (conversation-first; GitHub only for known identities; daily 17:00 CDT) |

---

## 3. New work (from 2026-09-02 gap analysis)

### Phase 3.1 — P0: fix identity-map shadowing (privacy bug) — ✅ DONE 2026-09-02
**Bug:** `IdentityResolver.resolve()` is first-match-wins. Map order
`chuck=SKILL_RUNNER_API_KEY, …, dylan=LITELLM_KEY_DYLAN, …` with
`SKILL_RUNNER_API_KEY=${LITELLM_KEY_CHUCK},${LITELLM_KEY_DYLAN}` means **Dylan's
LiteLLM key matches entry #1 and resolves to `user_id=chuck`** — his memories are
written under Chuck's identity, and Chuck's retrieval would surface Dylan's facts.
(Design intent: per-user isolation; Chuck's surfaces must never see Dylan's memories.)

**Done:**
1. ✅ `.env`: `MEMORY_USER_KEYS=chuck=LITELLM_KEY_CHUCK,dylan=LITELLM_KEY_DYLAN,service=SIRI_KEY_SERVICE`
   (legacy `chuck=SKILL_RUNNER_API_KEY` entry dropped; chat-endpoint auth unchanged —
   still accepts both keys via `SKILL_RUNNER_API_KEY`). Stale comment block updated.
2. ✅ Container recreated (`docker compose up -d` — `docker restart` does not re-read `env_file`).
   **Verified:** Dylan key → `user_id=dylan`, Chuck key → `user_id=chuck` (log: `Chat request: … user_id=dylan`).
3. ✅ `identity.py`: `IdentityResolver.__init__` now calls `_warn_on_conflicts()` — logs a loud
   `MEMORY_USER_KEYS CONFLICT` warning (naming users + env var names, never raw key values)
   when one key value maps to >1 user. Regression tests added to `memory/tests/test_identity.py`
   (shadowing scenario fires warning + resolves to first user; fixed disjoint map resolves cleanly).
   All identity tests pass; `test_unit.py` 147/147.
4. ✅ Misattributed X5 memory deleted (`DELETE /api/memory/08725395-…`, admin key); chuck count 1 → 0.

### Phase 11 — Scoped memory search endpoint + pi (Mac) wiring — ✅ DONE 2026-09-02
Goal: *any* authenticated surface can answer "what do you know about me" from memory.

**Done:**
1. ✅ `POST /api/memory/search` + `POST /api/memory/list` in `main.py` (user-key auth:
   `X-API-Key` must be in `SKILL_RUNNER_API_KEY`, then `resolve_user_id()`; unmapped → 403;
   NOT the admin key — admin has no user scope). `top_k` clamped 1–20, `limit` 1–100.
   **Verified:** Chuck key → `user_id=chuck` hits; Dylan key → `user_id=dylan` 0 hits (isolation);
   Siri service key & garbage key → 403. Full round-trip verified (write → search → delete).
2. ✅ `mcp_memory` container (`/home/chuck/homelab/mcp/servers/memory/`, FastMCP streamable-http):
   tools `memory_search(query, top_k?)`, `memory_list(limit?)`. Identity threading: caller's
   `Authorization: Bearer <LiteLLM key>` is forwarded to skill-runner as `X-API-Key` and
   resolved **per-caller** (chuck → chuck, dylan → dylan); fallback `MEMORY_USER_KEY` =
   Chuck's key when no header. LAN-published on **:8005** (compose.mcp.yml).
   **Verified via MCP handshake:** tools/list OK; memory_search as Chuck → 1 hit (his fact);
   as Dylan → 0 hits. Isolation enforced server-side, not in the MCP layer.
3. ✅ **Mac pi wiring — via the LiteLLM MCP gateway (no Mac-side changes needed).**
   Discovery: **pi has no built-in MCP support** (docs/usage.md: "It intentionally does not
   include built-in MCP… build or install those workflows as extensions"). Since
   `mcp_knowledge` is not LAN-published, the Mac pi's `kb_search` tools can only come from the
   **LiteLLM MCP gateway** (`/mcp-rest/tools/*` on :4000). So `mcp_memory` was registered with
   LiteLLM and now surfaces to the Mac pi exactly like `kb_search` — see **Phase 11.5**.
   The direct :8005 path remains as the per-caller-key path (Dylan's future pi, Open WebUI).

### Phase 11.5 — LiteLLM gateway registration (Mac pi access) — ✅ DONE 2026-09-02
Goal: the Mac pi gets `memory_search`/`memory_list` through the same mechanism it already uses
for `kb_search`, with **zero LiteLLM reloads** and **no Mac-side config changes**.

**Done:**
1. ✅ Registered `mcp_memory` with LiteLLM (`POST /v1/mcp/server`): server_id
   `57edf1fe-2244-4a4d-a455-11da65f46c9e`, url `http://mcp_memory:8000/mcp` (docker-internal),
   transport `http`, `allow_all_keys=false`.
2. ✅ **Access control** via LiteLLM access groups (key-level, not team-level):
   - Access group `mcp-memory-chuck` (`6b4fc668-2720-403f-8e6b-3bbece1405b1`):
     `access_mcp_server_ids=[57edf1fe…]`.
   - Group attached to **Chuck's key** via `POST /key/update` → `access_group_ids`.
   - Note: the group's `assigned_key_ids` is bookkeeping only — the grant is the key's
     `access_group_ids` (verified in `user_api_key_auth_mcp.py`:
     `_get_key_access_group_mcp_server_extras`, "no `assigned_key_ids` re-check").
   - Cleanup: first registration (server `926c97ba…`) was deleted after the group pointed at
     the stale id; the unused `chuck-mcp` team (created while probing team-based restriction)
     was deleted.
3. ✅ **Verified (no reload needed — registration is dynamic):**
   - `/mcp-rest/tools/list` (Chuck key) → `memory_search`, `memory_list` present (58 tools).
   - Gateway call as **Chuck** → `user_id=chuck` + solar-battery memory hit.
   - Gateway call as **Dylan** → **403 access_denied** ("The key is not allowed to access
     server mcp_memory").
   - Direct :8005 path unchanged (per-caller key; Chuck → chuck, Dylan → dylan, verified
     earlier in the session).
4. ⚠️ **Design note — `delegate_auth_to_upstream` does NOT forward the caller's key**
   (empirically verified: Dylan's gateway call resolved to `user_id=chuck` via the
   `MEMORY_USER_KEY` fallback before the access group was in place). Consequence: **all
   gateway calls resolve to `chuck`** — which is safe *because* only Chuck's key can reach the
   server through the gateway (access group). Dylan's memory access must go via the direct
   :8005 path with his own key (or a second gateway registration + his own access group when
   he gets pi). Do not "fix" this by widening the access group.
5. Mac pi: no config change required — `memory_search`/`memory_list` appear in its tool list
   the same way `kb_search` does. If the Mac pi caches its tool list, a session restart picks
   up the new tools.

### Phase 12 — Recent-activity capture (scheduled job) — ✅ DONE 2026-09-02
Goal: durable answer to "what have I been doing recently" on every surface.
**Design (per chuck's 2026-09-02 answers):** conversation-first (what the user did with the
assistant clients/surfaces), distilled; GitHub is secondary and **only for users with a known
GitHub identity** (chuck = `choukalos` via `GITHUB_ACCESS_TOKEN`; dylan has none → skipped);
**all users** get it.

**Done:**
1. ✅ `skills/recent_activity/` (skill.yml + skill.py). Per user, lookback `days` (default 7):
   - **skill_jobs** (MySQL durable index, `JSON_EXTRACT(data,'$.user_id')` filter) — what the user asked the assistant to do;
   - **recent Mem0 memories** (in-process `interface.list_memories`);
   - **GitHub public events** (push/PR/issue) — only if user is in `config.github_users` AND token present.
   No inputs → skip user (no LLM call, no writes). Distill via `matrix-coder` (5–10 grouped
   bullets) → write (a) dated fact to `kb_user` via `kb_add_fact` (mcp_knowledge) and
   (b) Mem0 for that user (`learn_from_turn`, `source=scheduled`, importance normal).
   Artifact: `/home/chuck/data/media/homelab_reports/recent_activity_YYYYMMDD_HHMM.md`.
   **Verified end-to-end** (39 s run): chuck updated (solar battery blog+marketing, quantum
   deep-research, investing analysis — all real job history); dylan skipped (0 inputs);
   kb_user point + mem0 fact confirmed in Qdrant.
2. ✅ Scheduled: `daily-recent-activity`, cron `0 17 * * *`, timezone `America/Chicago`,
   `params.days=7`, id `05ab224fed61`, next run 2026-09-02T17:00-05:00 (22:00 UTC).
3. ✅ **Scheduler fixes** (found during deployment):
   - `scheduler.py`: cron now matches in the entry's `timezone` (`_local_now` via zoneinfo,
     DST-safe; invalid tz → warning + UTC fallback). Previously the `timezone` field was
     stored but ignored (cron always matched UTC).
   - `compose.skill-runner.yml`: `SCHEDULER_CONFIG_PATH=/app/data/scheduler/scheduler.json`
     (was defaulting to ephemeral `~/.thor/scheduler.json` → schedules lost on recreate).
     Schedules now persist across container recreation.
4. Dylan: automatic — the job iterates every user in `MEMORY_USER_KEYS`; Dylan gets a summary
   once he has activity (his GitHub is skipped until an identity is configured).

### Phase 13 — Week-later evaluation (due ~2026-09-06)
Memory went live 2026-08-30/31; one-week checkpoint. Checklist:
- [ ] **Extraction quality:** spot-check stored facts. Known suspect: the single X5 fact (ownership misattribution — wife's car). Any secrets/ephemera stored? (policy should block)
- [ ] **Retrieval relevance:** with threshold 0.5 / top_k 6 — false positives injected into unrelated chats? false negatives on personal questions?
- [ ] **Latency:** 1.5 s retrieval budget — timeouts observed 08-30/08-31 (2×). Acceptable? (tune `MEMORY_TIMEOUT_MS` or warmup)
- [ ] **Household scope:** zero `household`-user points so far — is that expected (no one used "share with household") or a gap?
- [ ] **Privacy:** after Phase 3.1 — cross-user test (search as dylan must not return chuck's facts and vice versa); verify unmapped keys get nothing. ✅ **pre-verified 2026-09-02** (scoped endpoints + mcp_memory: dylan sees 0 of chuck's facts; unmapped/garbage keys → 403)
- [ ] **Operational:** enable `MEMORY_DEBUG_LOGGING=true` during the eval window; check counters (`/api/memory/health`) — note counters are in-memory and reset on restart (consider persisting to the MySQL job store later).
- [ ] **Volume caveat:** only 1 memory exists so far — evaluation is thin until real traffic (Dylan via Siri path, pi wiring) lands.

---

## 4. Open questions (for chuck — 2026-09-02)

1. ✅ **Phase 3.1 fix:** applied (approved 2026-09-02).
2. ✅ **The one stored memory** ("User owns a BMW X5…"): confirmed misattributed by chuck → **deleted**.
3. ✅ **pi wiring:** `mcp_memory` container built + verified; **Mac pi access via LiteLLM gateway registration (Phase 11.5)** — no Mac-side config needed (pi has no built-in MCP; the Mac pi reaches `kb_search` through the LiteLLM MCP gateway, so `mcp_memory` registered there surfaces identically).
4. ✅ **Recent-activity job:** conversation-first, all users, GitHub only for known identities (chuck=`choukalos`); daily 17:00 CDT — **built, tested, scheduled**.
5. ✅ **File location:** `skills/runner/memory_todo.md` (this file).
6. **Evaluation:** want Dylan to generate real memory traffic (chat via Siri path) before the 09-06 checkpoint so the eval isn't based on 1 fact? (Still open.)

**Remaining Mac-side action:** none required. If the Mac pi session caches its tool list, restart the pi session (or re-run tools/list) so `memory_search`/`memory_list` appear, then test in pi: "what do you know about me?" / "what have I been doing recently?" — should pull from `memory_search` + `kb_search`.

---

## 5. Evidence log (2026-09-02)

- `docker inspect skill-runner`: env dump (all `MEMORY_*`), start time 2026-08-31T23:39:33Z, mounts.
- JWT decode: `{"sub":"skill-runner","access":[{"collection":"mem0_memories","access":"rw"}]}` — no `exp`.
- Qdrant scroll with JWT: 1 point total (chuck, 2026-08-31T17:57:43Z, X5 fact).
- Admin API (`MEMORY_ADMIN_API_KEY`): health OK; `users/chuck` count=1; `users/dylan` count=0.
- Key cross-reference (python): `LITELLM_KEY_DYLAN` ∈ `SKILL_RUNNER_API_KEY` → first-match resolves to `chuck` (bug).
- LiteLLM `/key/info`: memory-service-v3 (model-restricted ✓), chuck-remote, dylan-v2.
- `logs/skill_runner/skill_runner.log`: 401s (08-30), 1.5 s timeouts (08-30 12:17, 08-31 12:57), clean after 08-31 17:57.
- `grep mcp_enabled`: defined in `config.py` only — Phase 6 unimplemented.
- `GET /api/schedule`: 0 jobs. `ls /home/chuck/Code`: absent on Thor.
- Open WebUI env: `OPENAI_API_BASE_URL=http://litellm-proxy:4000/v1` (bypasses skill-runner).
- `kb_user` scroll: 3 points incl. manual recent-projects fact (2026-09-02).
- KB raw sources host path: `/home/chuck/data/ai-kb/raw` (→ `/data/ai-kb/raw` in mcp_knowledge).

### Execution evidence (2026-09-02, post-fix)

- Identity: `POST /api/chat` with Dylan key → log `Chat request: … user_id=dylan`; Chuck key → `user_id=chuck`. (Before fix: Dylan key → `chuck`.)
- Scoped endpoints: `POST /api/memory/search` — Chuck key → `user_id=chuck` 1 hit (his test fact); Dylan key → `user_id=dylan` 0 hits; Siri service key → 403; garbage key → 403.
- Round-trip: in-process `learn_from_turn` write → visible to chuck via HTTP + MCP, invisible to dylan → deleted via admin API.
- `mcp_memory` (192.168.4.54:8005/mcp): MCP initialize + tools/list (`memory_search`, `memory_list`) + tools/call as both keys → correct per-user scoping.
- `recent_activity` job `36ae6775bce8` (days=7): completed in 39 s — chuck 6 inputs (jobs=5, memories=1, github=0) → kb_user fact + 1 mem0 fact; dylan skipped (0 inputs). Artifact `recent_activity_20260902_0054.md`.
- `kb_user` scroll post-run: 4 points incl. new "Chuck's recent activity (as of 2026-09-02)".
- Schedule `05ab224fed61` (`daily-recent-activity`, `0 17 * * *`, America/Chicago): `next_run_at=2026-09-02T17:00:00-05:00` (CDT-aware after scheduler tz fix); persisted in `/home/chuck/homelab/data/scheduler/scheduler.json`.
- GitHub token owner: `choukalos` (chuck) — used only for chuck; dylan skipped (no known identity).
- **Zero LiteLLM reloads** — all work used existing keys (chuck-remote, dylan-v2, memory-service-v3, master).

### Phase 11.5 evidence (2026-09-02, gateway registration)

- `POST /v1/mcp/server` → server `57edf1fe-2244-4a4d-a455-11da65f46c9e` (url `http://mcp_memory:8000/mcp`, `allow_all_keys=false`). First registration `926c97ba…` deleted after access group pointed at stale id.
- Access group `mcp-memory-chuck` (`6b4fc668-2720-403f-8e6b-3bbece1405b1`): `access_mcp_server_ids=[57edf1fe…]`; attached to Chuck's key via `POST /key/update` → `access_group_ids` (verified in source: grant = key's `access_group_ids`, no `assigned_key_ids` re-check).
- `/mcp-rest/tools/list` (Chuck key): `memory_search`, `memory_list` present (58 tools total) — **no LiteLLM reload**.
- Gateway `tools/call` as **Chuck** → `user_id=chuck` + solar-battery memory (score 0.64).
- Gateway `tools/call` as **Dylan** → **403 access_denied**.
- `delegate_auth_to_upstream` probed: does NOT forward caller key (Dylan's call resolved to chuck via fallback before the access group existed) → documented as design note; safe because only Chuck's key reaches the gateway server.
- Cleanup: unused team `chuck-mcp` (`ec690cf6…`) deleted.