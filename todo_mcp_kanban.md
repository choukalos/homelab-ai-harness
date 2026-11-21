# TODO — mcp_kanban (ai-kanban → homelab MCP tool)

Created 2026-11-21 (pi, thor). Decisions locked 2026-11-21 (chuck).
Goal: transform the `workspace/ai-kanban` code into the 14th homelab MCP
server (`mcp_kanban`): a Docker container that exposes the kanban tools via
the LiteLLM proxy's MCP tool listings **and** a web UI (the board) reachable
only on the local homelab. Checked in to this repo as `mcp/servers/kanban/`.

## Decisions (locked 2026-11-21)

| # | Decision | Choice |
|---|---|---|
| 1 | Capabilities | chuck → `admin`, dylan → `control` (queue/groom/start/stop tasks, no project admin) |
| 2 | Keys | Inbound MCP auth is already per-caller-key (key = user). Outbound LLM attribution: **Phase 1** service key; **Phase 2** per-user/per-agent key threading (design below) |
| 3 | GITHUB_TOKEN | In `.env` as `KANBAN_GITHUB_TOKEN` — **set + verified 2026-11-21** (container force-recreated; `git ls-remote` OK) |
| 4 | Model / concurrency | `.env`-tunable: `KANBAN_MODEL=matrix-coder`, `KANBAN_CONCURRENT_TASKS=1` (defaults, both changeable without code) |
| 5 | LAN port | `thor.local:3000` (openwebui dropped that port) |
| 6 | Commit | Commit to `main` when done |
| 7 | DB | **MySQL on Thor** (DB `ai_kanban`, user `kanban`); **chuck action item** to create DB+user (SQL below) |
| 8 | Web UI auth | None — LAN-only (LAN-IP bound) |

Plus (from the original design, unchanged):
- Server class: **stateful self-contained service** (owns DB, auth, agent
  sessions, orchestrator) — not a thin client.
- MCP transport: `transport: http` (streamable HTTP) at `POST /mcp`.
  Verified LiteLLM v1.104.0 supports `MCPTransport.http` + `extra_headers`
  forwarding. Tool names exposed BARE (native names, no server prefix —
  LiteLLM v1.104 does not prefix; verified 2026-11-21).
- LiteLLM entry: `mcp_kanban: {transport: http, url:
  http://mcp_kanban:3000/mcp, extra_headers: [Authorization], timeout: 7200}`.
- Web UI: `ports: ["${THOR_IP:-192.168.4.54}:3000:3000"]` (presenton pattern).
- Workspace: `/workspace` = `/home/chuck/workspace` rw, container runs
  `1000:1000`; `/data` = `/home/chuck/data/ai-kanban` (sessions, agent dir,
  harness clone).
- Skills: entrypoint clones `choukalos/homelab-ai-harness` → `/data/harness`
  at startup; all agent sessions get `agents-skills/`.
- Model validation against the proxy at boot (fail fast).

## Q2 — "can't the keys be the user or agent who uses the tool?"

**Inbound (who may use the tools): yes — already true.** The proxy forwards
each caller's LiteLLM key (`extra_headers: [Authorization]`); the container
scopes the tool set per key (chuck `admin` / dylan `control`; unknown keys
401). The key *is* the user for access control.

**Outbound (which key pays for the LLM work kanban performs): Phase 2.**
Today the container makes all LLM calls (grooming/task/QA/summary) with one
service key. To make the triggering user/agent's key pay:

1. **Capture the owner** — on each MCP call the container already receives
   the caller's key. Resolve it to a user via the proxy's `GET /key/info`
   (same mechanism `mcp_media` uses) and store `owner_user` on the idea at
   creation (propagates to its task). Web-UI-triggered work has no caller →
   `owner_user` empty (falls back to the service key).
2. **Use the owner's key for that work** — container holds a user→key map
   (`KANBAN_USER_KEYS=chuck=<key>,dylan=<key>`, like `MEMORY_USER_KEYS`).
   When running a session for a work item owned by user X, the Pi session
   authenticates to the proxy with X's key → LiteLLM bills spend to X's key.
   Implementation: per-user agent dir + `auth.json` + `ModelRuntime`
   (`/data/pi-agent-<user>`); session creation picks the runtime by
   `owner_user`. (The app currently writes a single `auth.json` at startup —
   this is the main code change.)
3. **Fallback** — no owner (web UI, background seeding, unresolvable key) →
   service key, as today.

**Plan:** Phase 1 ships with the service key (works now; access control is
already per-key). Phase 2 = per-user spend attribution. Adding the
`owner_user` column + identity capture in Phase 1 is cheap and makes
attribution data available from day one — do it in Phase 1 if low-risk, else
start Phase 2 with the schema change.

## MySQL on Thor (decision 7) — DONE 2026-11-21

App runs the table migrations itself; the **DB must pre-exist** and the user
needs privileges on `ai_kanban.*` only (homelab convention, cf. `AI_DB_*`).

**chuck action item — completed 2026-11-21**: DB `ai_kanban` + user
`ai-kanban` created on Thor (MySQL bound to `192.168.4.54:3306`, reached via
`thor.local` — the `MYSQL_DB_HOST` value); `KANBAN_DB_PASS` set in `.env`.

Reference (as executed — user named `ai-kanban`, not `kanban`):

```sql
CREATE DATABASE ai_kanban CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'ai-kanban'@'%' IDENTIFIED BY '<strong-password>';
GRANT ALL PRIVILEGES ON ai_kanban.* TO 'ai-kanban'@'%';
FLUSH PRIVILEGES;
```

`KANBAN_DB_PASS` set in `.env` (host `thor.local` — the `MYSQL_DB_HOST`
value; containers reach it the same way `mcp_mysql` does).

## Chuck action items (in order)

1. **MySQL**: ~~create `ai_kanban` DB + `kanban` user on Thor (SQL above);
   set `KANBAN_DB_PASS` in `.env`.~~ **DONE 2026-11-21** — DB `ai_kanban` +
   user `ai-kanban` created on Thor (privileges on `ai_kanban.*` only),
   `KANBAN_DB_PASS` set in `.env`; connectivity verified from thor
   (`mysql -h 192.168.4.54 -u ai-kanban` OK; DB visible, empty — the app
   ran its migrations at first boot: 7 tables).
2. **GitHub token**: set `KANBAN_GITHUB_TOKEN` in `.env` (repo scope — the
   deploy stage pushes task branches / blog posts / media).
   **DONE 2026-11-21** — token set (chuck); container force-recreated to
   pick it up; verified present in container env (40 chars), no config
   warning, `git ls-remote` against choukalos/homelab-ai-harness OK.
3. **LiteLLM swap**: replace `litellm/config.yml` with
   `litellm/config.yml.proposed-mcp-kanban` and restart
   (`docker compose -f compose/compose.ai-core.yml up -d litellm`). Restart
   severs active proxy sessions — pick a quiet moment.
   **DONE 2026-11-21** — chuck swapped + manual restart; proxy verified
   (110 tools) + E2E `tools/call` with chuck/dylan/unknown keys (see
   Pending item 1).

## Status

### Done
- [x] Explored: ai-kanban source (46 TS files), homelab MCP patterns, litellm
      config, compose, caddy, .env keys
- [x] Verified LiteLLM v1.104.0 MCP capabilities: `MCPTransport` =
      {sse, http, stdio}; `extra_headers` forwarding; tool prefix
      `{server}-{tool}`
- [x] Verified global `LITELLM_API_KEY` works against the proxy (200
      /v1/models, /model/info)
- [x] Verified host port 3000 free
- [x] Copied app into `mcp/servers/kanban/`: `src/` (46 files),
      `package.json`, `package-lock.json`, `tsconfig.json`, `Dockerfile`,
      `entrypoint.sh`, `.env.example`, `README.md`, `.gitignore`,
      `deploy/litellm-mcp-snippet.yaml`. Excluded: node_modules, dist, tmp,
      .env, .git, QNAP docker-compose.yml, dev-process docs (PLAN.md, draft
      requirements, improvement_todo, SDK_NOTES)
- [x] Tweaked `deploy/litellm-mcp-snippet.yaml` → homelab entry
      (transport: http, ai-net URL, extra_headers)
- [x] Tweaked `.env.example` → homelab defaults
- [x] Tweaked `README.md` → mcp_kanban naming, homelab deploy, new
      "Identity & keys" section, LAN client example
- [x] Fixed Dockerfile header comment
- [x] **`.env`**: appended `# ===== mcp_kanban =====` block —
      `KANBAN_MODEL`, `KANBAN_CONCURRENT_TASKS`,
      `KANBAN_MCP_KEY_CAPABILITIES=faxfoUszvw:admin;JAS3o6tu0A:control`,
      `KANBAN_GITHUB_TOKEN` (empty — action), `KANBAN_DB_USER/DB_PASS/DB_NAME`
      (pass filled 2026-11-21 — chuck created DB `ai_kanban` + user
      `ai-kanban` on Thor with privileges; connectivity verified from thor:
      `mysql -h 192.168.4.54 -u ai-kanban` OK, DB visible)
- [x] **compose** (2026-11-21): `mcp_kanban` added to `compose/compose.mcp.yml`
      (MySQL + KANBAN_* mapping + `env_file: ../.env` — see the
      Compose-v5-interpolation note in Verification below)
- [x] **Proposed litellm config** (2026-11-21): `litellm/config.yml.proposed-mcp-kanban`
      = full copy of live config + the `mcp_kanban` entry (14th server,
      `transport: http`). Live config untouched — chuck swaps it in (action item 2)
- [x] **Docs** (2026-11-21): kanban rows in `mcp/README.md` + `mcp/servers/README.md`
- [x] **Proposal doc** (2026-11-21): `proposals/2026-11-21-tier2-mcp-kanban.md`
- [x] **Build verification** (2026-11-21): `docker compose -f
      compose/compose.mcp.yml -p ai-mcp build mcp_kanban` — clean build
      (npm ci + Go 1.24.5 tarball + TS build; no build-essential needed —
      better-sqlite3 prebuilds covered node22/bookworm; MySQL driver is
      pure JS)
- [x] **Runtime verification** (2026-11-21): container up; entrypoint
      pulled harness skills + validated `matrix-coder` against the proxy
      (fail-fast OK); app booted on MySQL; **7 tables migrated**
      (projects, ideas, tasks, task_events, usage, kv, schema_migrations);
      `/health` 200 (`{"ok":true,"model":"matrix-coder","db":"mysql",
      "concurrentTasks":1}`); board UI 200 at `http://192.168.4.54:3000`
      (LAN-bound, no auth); direct `/mcp` tools/list key scoping verified:
      chuck key → 16 tools (admin, incl. create_project/update_project),
      dylan key → 14 tools (control, no project admin), unknown key → 401
      with a helpful message. Note: first boot failed twice — (a) Docker
      created `/home/chuck/data/ai-kanban` root-owned (fixed: chown 1000:1000
      via a throwaway root container — chuck has no passwordless sudo),
      (b) `${...}` interpolation empty (fixed: `env_file: ../.env` in the
      compose entry + `compose/.env -> ../.env` symlink; see below)
- [x] **Commit** (decision 6, 2026-11-21): WIP checkpoint `3243885` (app
      code + todo) + deploy commit (compose entry, proposed litellm config,
      docs, proposal)
- [x] **Pattern-fit assessment** (2026-11-21): in the proposal doc —
      stateful self-contained service (deliberate exception to the
      read-mostly thin-client pattern, like mcp_sessions); streamable-HTTP
      transport (only non-SSE MCP entry — verified supported in LiteLLM
      v1.104.0); per-key tool scoping (mcp_sessions pattern); LAN-only UI
      (presenton pattern); dedicated MySQL DB/user (AI_DB_* convention)

### Pending
1. ~~**E2E through proxy** (after chuck swaps the litellm config): kanban
   tools visible in the proxy tool list; call with chuck's key (full set)
   and dylan's key (control set); unknown key → 401~~
   **DONE 2026-11-21** — proxy swap applied (chuck, manual restart) +
   `family-mcp-full` access group extended with `mcp_kanban` (default-deny
   per-key MCP access; same step as mcp_sessions). Verified: 110 proxy
   tools (94 + 16 kanban, bare names, no collisions); chuck `list_projects`
   OK; dylan `list_projects` OK (read ⊂ control); dylan `create_project`
   refused (control < admin — correct); chuck `create_project` OK (MySQL
   row persisted; test row removed); unknown key → 401.

### Done (2026-11-21, post-deploy)
- Proxy registration: `mcp_kanban` in the live `litellm/config.yml` +
  running proxy (14th MCP server; `transport: http`)
- App fix: unauthenticated discovery (initialize/tools/list/ping) allowed
  so the proxy's global registry handshake works; `tools/call` still
  requires a valid Bearer key (192/192 tests green)
- `family-mcp-full` access group: +mcp_kanban (14 servers; description
  updated) via `PUT /v1/unified_access_group/07c1acf8-...`
- E2E through proxy (see Pending item 1 above)

### Draft compose entry (for step 1)

```yaml
  # --- Kanban (mcp_kanban): LLM task queue + grooming + execution ----------
  # Stateful service (not a thin client): Fastify GUI + REST + MCP
  # (streamable HTTP at /mcp) + in-process Pi agent sessions + orchestrator.
  # Web UI is LAN-only (bound to THOR_IP, no auth — LAN trust).
  # MySQL on Thor: DB ai_kanban pre-created (chuck), app runs table migrations.
  mcp_kanban:
    build:
      context: ../mcp/servers/kanban
    container_name: mcp_kanban
    # Run as chuck (uid/gid 1000): /data writes must be chuck-owned.
    user: "1000:1000"
    environment:
      # LiteLLM proxy (models + MCP tools) — internal ai-net URL.
      - LITELLM_BASE_URL=http://litellm-proxy:4000/v1
      # Service key: outbound LLM calls AND the "kanban key" (full MCP set).
      # Phase 2: per-user key threading (todo_mcp_kanban.md Q2).
      - LITELLM_API_KEY=${LITELLM_API_KEY}
      # Model + concurrency: .env-tunable (KANBAN_MODEL / KANBAN_CONCURRENT_TASKS).
      - MODEL=${KANBAN_MODEL:-matrix-coder}
      - CONCURRENT_TASKS=${KANBAN_CONCURRENT_TASKS:-1}
      # git push auth (deploy stage) — unset until chuck provides it.
      - GITHUB_TOKEN=${KANBAN_GITHUB_TOKEN:-}
      # MySQL on Thor (DB pre-created; app runs migrations — tables only).
      - DB_DRIVER=mysql
      - MYSQL_HOST=${MYSQL_DB_HOST:-thor.local}
      - MYSQL_PORT=3306
      - MYSQL_USER=${KANBAN_DB_USER}
      - MYSQL_PASSWORD=${KANBAN_DB_PASS}
      - MYSQL_DATABASE=${KANBAN_DB_NAME}
      # Per-role thinking levels (app defaults).
      - GROOM_THINKING=xhigh
      - TASK_THINKING=medium
      - QA_THINKING=xhigh
      - SUMMARY_THINKING=medium
      # Caller-key scoping (tails of LITELLM_KEY_CHUCK / LITELLM_KEY_DYLAN).
      - MCP_KEY_CAPABILITIES=${KANBAN_MCP_KEY_CAPABILITIES}
    # LAN-only web UI (presenton pattern: LAN-IP bind, not 0.0.0.0).
    ports:
      - "${THOR_IP:-192.168.4.54}:3000:3000"
    volumes:
      - /home/chuck/data/ai-kanban:/data
      - /home/chuck/workspace:/workspace
    restart: unless-stopped
    networks:
      - ai-net
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://127.0.0.1:3000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
```

## Verification notes / open items

- **Compose v5 `.env` interpolation (found 2026-11-21, cost two failed
  boots):** with `docker compose -f compose/compose.mcp.yml`, the project
  directory is the **compose file's directory** (`compose/`), so compose's
  interpolation engine looks for `compose/.env` — not the repo `.env`.
  `env_file: ../.env` in a service only injects vars into the *container*;
  it does NOT feed `${...}` interpolation. Fix (both applied): (a)
  `env_file: - ../.env` on the mcp_kanban entry (searxng pattern), and
  (b) machine-local symlink `compose/.env -> ../.env` (gitignored via the
  `.env` pattern) so interpolation works for any compose file in `compose/`.
  Pre-existing services (mcp_sessions etc.) got their values because their
  deploy shells had sourced the repo `.env` — recreate them any other way
  and their `${...}` refs resolve empty.
- **Docker-created bind dirs are root-owned**: first `up` created
  `/home/chuck/data/ai-kanban` as root (uid 0) — the `1000:1000` container
  then failed on `/data` writes. Fix: chown via a throwaway root container
  (`docker run --rm -v /home/chuck/data/ai-kanban:/data alpine chown -R
  1000:1000 /data`) — chuck has no passwordless sudo on thor. Pre-create
  chuck-owned dirs before first `up` for future stateful services.
- **Proxy MCP gateway probe hung**: `POST http://litellm-proxy:4000/mcp`
  (initialize) blocked with no response (aborted after ~2 min). The kanban
  *task agents* use the proxy's MCP gateway (origin of LITELLM_BASE_URL +
  `/mcp`) for the dynamic tool set during task execution. If the proxy's
  experimental MCP-server surface is not answering, task agents run without
  the proxy's MCP tools (degraded, not broken). Re-probe with a 10s timeout
  before declaring it a problem; core kanban functionality does not depend on it.
- **better-sqlite3**: native module; prebuilds should cover node22/bookworm.
  If `npm ci` fails to find a prebuild, add `build-essential` to the
  Dockerfile (python3 already present). (MySQL driver is pure JS — no issue.)
- **MySQL migration check**: after first boot, verify the app created the
  tables (`mysql ai_kanban -e "SHOW TABLES"` should list projects, ideas,
  tasks, task_events, usage, kv).
- **LiteLLM restart severs active proxy sessions** — the config swap is an
  explicit operator step (like the 2026-11-21 studio-gemma4 flag reload).

## MCP-first cutover (2026-11-21) — IMPLEMENTED (deploy + E2E pending)

Plan: `proposals/2026-11-21-tier2-mcp-kanban-mcp-first.md` (status:
implemented). Decisions locked 2026-11-21 (chuck): web UI (thor.local:3000)
becomes **read-only**; MCP is the only mutation interface. New MCP tools:
interactive grooming (start_grooming / groom_message / groom_status /
groom_accept / groom_cancel / groom_re_groom — the LLM asks questions and
the user steers from their client of choice), `discard_idea`,
`board_status` (needs-attention counts + per-job summary for in-dialog
resolution via task_status → restart_task). The one-shot `groom_idea` tool
is **removed** (grooming is interactive by design). **Owner attribution**
(key → user name via `KANBAN_MCP_KEY_OWNERS` in the repo `.env`, passed to
the container as `MCP_KEY_OWNERS`) on projects/ideas/tasks, shown as a tag
on the board/web view. Note: this **pulls owner capture forward from
Phase 2** — the `owner` columns are the attribution data Phase 2's spend
work uses.

Implementation (2026-11-21, committed):
- [x] Migration `0002_owner` (owner columns on projects/ideas/tasks,
      both drivers) + Drizzle schema
- [x] MCP: 16 → 23 tools (chuck 23 / dylan 21); `groom_idea` removed;
      interactive grooming + `discard_idea` + `board_status` added
- [x] Owner threading: `resolveMcpOwner` (kanban key → `kanban`, tail
      match, else `unknown`); `create_project`/`add_idea` stamp the caller;
      tasks inherit the idea's owner at `move_to_backlog`
- [x] Read-only UI: all mutation endpoints/forms removed (REST 404);
      groom page = read-only transcript viewer; owner tags on board/
      project/task views; `list_ideas` excludes discarded ideas
- [x] Dead code deleted: `src/agent/resolve.ts` (+ mock + test) — the MCP
      resolution loop (task_status → restart_task) replaces it
- [x] `npm test` green (172 tests: 171 pass, 1 skip = MySQL w/o test server)
- [ ] Deploy on thor: `docker compose -f compose/compose.mcp.yml up -d
      --build mcp_kanban` (compose now passes `MCP_KEY_OWNERS`;
      `.env` has `KANBAN_MCP_KEY_OWNERS=chuck:faxfoUszvw;dylan:JAS3o6tu0A`)
- [ ] Verify post-deploy: migration `0002_owner` applied (owner column on
      3 tables); UI read-only (no forms; owner tags); E2E via proxy —
      23 new tools visible, **no bare-name collisions** against the other
      proxy tools, chuck/dylan calls stamp the right owner, unknown key 401

## Phase 2 (follow-up, not in this change)

- Per-user/per-agent LLM spend attribution (Q2 design above): ~~`owner_user`
  capture~~ (done in the MCP-first change: `owner` columns +
  `KANBAN_KEY_OWNERS`) + per-user `ModelRuntime`/auth + `KANBAN_USER_KEYS` map.
- Consider: per-project cost budgets / alerts once attribution lands.
