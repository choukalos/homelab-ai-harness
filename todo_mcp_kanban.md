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
| 3 | GITHUB_TOKEN | In `.env` as `KANBAN_GITHUB_TOKEN` (configured); **chuck action item** to fill the token |
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
  forwarding. Tool names exposed as `mcp_kanban-<tool>`.
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

## MySQL on Thor (decision 7)

App runs the table migrations itself; the **DB must pre-exist** and the user
needs privileges on `ai_kanban.*` only (homelab convention, cf. `AI_DB_*`).

**chuck action item** — run on Thor (`mysql -u root -p`):

```sql
CREATE DATABASE ai_kanban CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'kanban'@'%' IDENTIFIED BY '<strong-password>';
GRANT ALL PRIVILEGES ON ai_kanban.* TO 'kanban'@'%';
FLUSH PRIVILEGES;
```

Then set `KANBAN_DB_PASS` in `.env` (user `kanban`, DB `ai_kanban`, host
`thor.local` — already the `MYSQL_DB_HOST` value; containers reach it the
same way `mcp_mysql` does).

## Chuck action items (in order)

1. **MySQL**: create `ai_kanban` DB + `kanban` user on Thor (SQL above); set
   `KANBAN_DB_PASS` in `.env`.
2. **GitHub token**: set `KANBAN_GITHUB_TOKEN` in `.env` (repo scope — the
   deploy stage pushes task branches / blog posts / media).
3. **LiteLLM swap**: replace `litellm/config.yml` with
   `litellm/config.yml.proposed-mcp-kanban` and restart
   (`docker compose -f compose/compose.ai-core.yml up -d litellm`). Restart
   severs active proxy sessions — pick a quiet moment.

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
      (pass empty — action)

### Not started
1. **compose**: add `mcp_kanban` to `compose/compose.mcp.yml` (draft below —
   now with MySQL + KANBAN_* mapping)
2. **Proposed litellm config**: `litellm/config.yml.proposed-mcp-kanban` =
   full copy of current `config.yml` + the `mcp_kanban` entry. **Do not touch
   the live config** — chuck swaps it in (action item 3).
3. **Docs**: kanban rows in `mcp/README.md` + `mcp/servers/README.md`
4. **Proposal doc**: `proposals/2026-11-21-tier2-mcp-kanban.md`
   (What/Why/Risk/Files per proposals/README pattern)
5. **Build verification**: `docker compose -f compose/compose.mcp.yml build
   mcp_kanban` — highest-risk step (npm ci + Go tarball + better-sqlite3
   native module; if prebuilds miss, add `build-essential` to the Dockerfile)
6. **Runtime verification** (after build): `up -d`, `/health` 200, board UI
   at `http://thor.local:3000`, direct `/mcp` tools/list with chuck key
7. **E2E through proxy** (after chuck swaps the litellm config):
   `mcp_kanban-list_projects` visible in the proxy tool list; call with
   chuck's key (full set) and dylan's key (control set); unknown key → 401
8. **Commit** to `main` (decision 6)
9. **Pattern-fit assessment** (final summary + proposal doc)

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

## Phase 2 (follow-up, not in this change)

- Per-user/per-agent LLM spend attribution (Q2 design above): `owner_user`
  capture + per-user `ModelRuntime`/auth + `KANBAN_USER_KEYS` map.
- Consider: per-project cost budgets / alerts once attribution lands.
