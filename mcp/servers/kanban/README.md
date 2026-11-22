# mcp_kanban

A single Docker container that keeps LLM/GPU time productively used: drop ideas, groom them with an LLM, promote groomed ideas to a backlog, and have them executed to completion. Results are published per project or per task (GitHub, blog paths, media files). **MCP is the only mutation interface** (drop ideas, interactive grooming, task control — driven by conversation from any LLM client); the web GUI is a **read-only status view**, visible only on the homelab network.

This is the 14th MCP server in the homelab (`mcp/servers/kanban/`, container
`mcp_kanban`, `ai-net`). Unlike the thin-client servers (search, knowledge,
sessions, …), it is a **stateful self-contained service**: it owns its DB,
its auth, and its agent sessions, and exposes both a web UI and the MCP
tool set from one Fastify process. See the "Identity & keys" section for
how it fits the homelab key pattern.

## Architecture

One container, one Node process (Fastify):

```
┌──────────────────────── mcp_kanban container ───────────────────────┐
│  Node process (Fastify)                                             │
│  ├─ HTTP: HTMX GUI (read-only, LAN-only) + MCP endpoint (POST /mcp) │
│  ├─ service layer (board/projects/ideas/tasks/usage) — shared       │
│  ├─ orchestrator (queue, slots, dependencies, watchdog, cleanup)    │
│  ├─ Pi SDK — in-process sessions (task / grooming / QA / summary);  │
│  │    session files in /data/sessions                               │
│  └─ DB layer (SQLite or MySQL)                                      │
└──────────┬──────────────────────────────────────────┬───────────────┘
           /data (persistent)                         /workspace (read-write)
           /home/chuck/data/ai-kanban                 host /home/chuck/workspace/
```

- **Workflow:** per project — **Idea → Grooming (interactive LLM chat via MCP) → Icebox** (LLM-identified dependencies); global board — **Backlog → Running → QA → Deploy → Done**, plus **Needs Attention** (resolve via MCP: `task_status` → dialog → `restart_task` with a resolution note → Backlog).
- **Models:** one model via the LiteLLM proxy (`MODEL`, validated at startup — fail fast); per-role thinking levels (groom `xhigh`, task `medium`, QA `xhigh`, summary `medium`).
- **MCP:** the container's MCP endpoint is registered with the LiteLLM proxy (`mcp_kanban` under `mcp_servers:`, `transport: http`), so any LLM client holding an authorized LiteLLM key — including clients outside the homelab — can drive the board by conversation. Tool names are exposed as `mcp_kanban-<tool>`.
- **Skills:** the homelab-ai-harness repo is cloned/pulled into `/data/harness` at startup; all sessions get all of its skills. Refresh = restart/rebuild (auto-pull at startup).
- **Deploy stage:** automated after QA pass, routed by task `kind` (code → GitHub push; blog → blog repo path; media → one of the project's public file directories; other → no-op). Failure → Needs Attention (retryable).

## Resilience (Slice 5)

- **Pause / resume / stop** — `paused` is an orthogonal flag on running tasks (stop ─► paused ──one-click──► running). MCP: `pause_task`, `resume_task`, `stop_task` (the web UI is read-only — no control buttons). Pause/stop aborts the session and keeps the `running` state; resume re-runs from `last_commit` with the mission brief + progress summary re-injected.
- **Watchdog** — per-task heartbeat (default 60s) written while a task's session is alive and producing activity (log lines, commits, usage); 10 minutes of silence moves the task to **Needs Attention** (reason `watchdog: no activity for …`) and aborts the session. The task detail page shows the last-activity timestamp, and the board card shows the paused/watchdog state via the Needs Attention column.
- **Auto-resume on container start** — any task left in `running` (not paused) when the container stopped is rehydrated at startup: re-clone/checkout `last_commit`, restore the Pi session file (`SessionManager.open` on the stable `task-<id>.jsonl` path), re-inject the mission brief + progress summary, continue. Paused tasks stay paused until explicitly resumed.
- **7-day workspace cleanup** — a background job (at startup + daily) deletes `/workspace/task-<id>` and `/workspace/groom-<id>` dirs older than 7 days (`WORKSPACE_CLEANUP_DAYS`, default 7). Only app-managed dirs (the `task-<id>` / `groom-<id>` naming convention) are touched; in-flight workspaces (running/deploy tasks, actively-grooming ideas) are kept. `delete_project` also removes the project's workspace dirs immediately. Durable results are pushed by the deploy stage before a task leaves the deploy state.
- **Concurrency** — `CONCURRENT_TASKS > 1` runs multiple task sessions in parallel (one Pi session + workspace per task; slot count verified by tests).

## Toolchain

The image ships **node, python, go, hugo (extended, pinned)** — the supported task toolchain (extensible). Hugo enables the Homelab Blog project: tasks build the Hugo site and run `./deploy.sh` (pushes built output to the `deploy` branch; the portal git-sync publishes choukalos.com). Media processing (ffmpeg/yt-dlp) is **not** baked in: agents use the media pipeline's MCP tools via the LiteLLM proxy, and the proxy's MCP tool set is dynamic (sessions pick up whatever the proxy exposes at session start).

## Volumes

| Mount | Persistence | Contents |
|---|---|---|
| `/data` | persistent (`/home/chuck/data/ai-kanban`) | SQLite DB (default driver), Pi session files, project specs, board/idea/task state + conversation logs, compaction summaries, usage records, app-owned agent dir (`/data/pi-agent`), homelab-ai-harness clone (`/data/harness`) |
| `/workspace` | host's `/home/chuck/workspace/`, read-write | agent scratch space: one dir per running/recent task (`task-<id>`: fresh git clone, working files, build artifacts) + media build folders + grooming scratch (`groom-<idea>`). Transitory by design — durable results are pushed out; task/groom dirs are swept after 7 days (or immediately on project delete). |

## Configuration (.env)

Copy `.env.example` to `.env` and fill in. Real environment variables override the file.

| Var | Default | Purpose |
|---|---|---|
| `LITELLM_BASE_URL` | `http://litellm-proxy:4000/v1` (homelab) | LiteLLM proxy endpoint (OpenAI-compatible base URL) |
| `LITELLM_API_KEY` | homelab service key | dual role: outbound LLM calls (models) **and** the "kanban key" — full MCP tool set on `/mcp` |
| `MODEL` | — (required) | model ID in the LiteLLM config; validated against the proxy at startup (fail fast) |
| — (cost rates) | fetched at startup | spend is estimated from the model's rates in the proxy's `/model/info` endpoint (same data as the Grafana dashboards); no env config needed. Unavailable/no costs → tokens tracked, reports show $0.00. Cache reads estimate at $0 (the endpoint has no cache-read price) |
| `GITHUB_TOKEN` | — | git push auth (deploy stage) |
| `DB_DRIVER` | `sqlite` | `sqlite` (default) or `mysql` |
| `SQLITE_PATH` | `/data/kanban.db` | SQLite file location (override for local dev) |
| `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE` | `3306` (port) | external MySQL (homelab/Thor); dedicated user + **pre-created** DB; user has table-level privileges; the app runs migrations (tables only). Required when `DB_DRIVER=mysql` |
| `HOST_WORKSPACE_PATH` | `/home/chuck/workspace` | host path mounted read-write at `/workspace` |
| `HARNESS_REPO_URL` | `https://github.com/choukalos/homelab-ai-harness` | git URL of the homelab-ai-harness repo; cloned/pulled into `/data/harness` at startup |
| `HARNESS_SKILLS_PATH` | `agent-skills` | path within the harness repo where skills live |
| `GROOM_THINKING` | `xhigh` | grooming chat thinking level |
| `GROOM_TURN_STALL_MINUTES` | per level (5/10/15/20/30) | grooming turn watchdog: abort a turn with no streaming activity after this many minutes. Defaults scale with `GROOM_THINKING` (`GROOM_STALL_MS_BY_LEVEL`: off/minimal 5, low 10, medium 15, high 20, xhigh/max 30 — deep xhigh turns can be legitimately quiet 10+ min); this env var overrides for all levels |
| `TASK_THINKING` | `medium` | task execution thinking level |
| `QA_THINKING` | `xhigh` | QA thinking level |
| `SUMMARY_THINKING` | `medium` | project state-summary thinking level |
| `CONCURRENT_TASKS` | `1` | max tasks running at once |
| `BIND_ADDR` / `PORT` | `0.0.0.0` / `3000` | GUI/API bind (homelab interface only; no auth — LAN-only) |
| `MCP_KEY_CAPABILITIES` | `faxfoUszvw:admin;JAS3o6tu0A:control` (homelab) | MCP guardrails for multi-user keys: `key-suffix:cap1,cap2;...` (key-suffix = the TAIL of a Bearer key; caps = `read` / `control` / `admin` or individual tool names). The kanban key (`LITELLM_API_KEY`) always gets the full tool set; other keys must match an entry or the MCP endpoint rejects them with a clear error. Homelab: chuck's + dylan's LiteLLM key tails → `admin` / `control` (update the suffixes on key rotation). |
| `USER_KEYS` | — (unset) | Per-user LLM spend attribution (Phase 2): comma-separated `name=full-LiteLLM-key` pairs. Sessions for work owned by a user (grooming/task/QA/summary) run against the proxy with that user's key, so LiteLLM bills the spend to the user's key/budget; usage rows carry the owner (per-user spend trend on `/reports`). Unset, or an owner without an entry → the work bills to the service key. Each key is validated against the proxy at boot (fail fast). Homelab: compose interpolates `USER_KEYS=chuck=${LITELLM_KEY_CHUCK},dylan=${LITELLM_KEY_DYLAN}`. **Also drives MCP owner attribution** (improvements batch): the caller's key is matched in full against these values — a match stamps that user name on the items they create (the kanban key → `kanban`; an authorized key with no entry → `unknown`). One map, no separate owner env var. |
| `WORKSPACE_CLEANUP_DAYS` | `7` | Age (days) after which idle `/workspace/task-<id>` / `groom-<id>` scratch dirs are swept (startup + daily). In-flight workspaces are never touched; `delete_project` removes the project's dirs immediately. |
| `AI_KANBAN_DATA_DIR` | `/data` | data dir root (DB, sessions, agent dir, harness); override for local dev — use a **persistent** dir, not `/tmp` (macOS purges `/tmp` while the server runs) |
| `AI_KANBAN_WORKSPACE_DIR` | `/workspace` | agent scratch root (task-<id> / groom-<idea> dirs); override for local dev |

## Local development

Prereqs: Node 20+.

```bash
npm install
cp .env.example .env    # fill in LITELLM_BASE_URL / LITELLM_API_KEY / MODEL

# Point the data dir + SQLite DB at a local path (optional).
# Use a PERSISTENT directory — not /tmp, which macOS purges while the
# server keeps running (the app then holds an unlinked DB file and loses
# task workspaces + grooming transcripts).
export AI_KANBAN_DATA_DIR=$HOME/Code/ai-experiments/ai-kanban-local-data/data
export SQLITE_PATH=$AI_KANBAN_DATA_DIR/kanban.db
export AI_KANBAN_WORKSPACE_DIR=$HOME/Code/ai-experiments/ai-kanban-local-data/workspace

npm run dev             # tsx watch (dev server)
npm test                # build + node --test
npm run build && npm start
```

The app validates `MODEL` against the LiteLLM proxy at startup and fails fast with a clear error if it is not served.

## Deploy (homelab)

Lives in the homelab-ai-harness repo as `mcp/servers/kanban/` and is deployed
through `compose/compose.mcp.yml` (service `mcp_kanban`, `ai-net`).

1. Build and start (from the homelab repo root):
   ```bash
   docker compose -f compose/compose.mcp.yml up -d --build mcp_kanban
   ```
   The entrypoint clones/pulls the harness skills repo, validates `MODEL`
   against the LiteLLM proxy (fail fast), and starts the app. Migrations are
   versioned + idempotent and run at app startup (both drivers; MySQL = tables
   only, DB pre-created).
2. Register the container's MCP endpoint with the LiteLLM proxy: the
   `mcp_kanban` entry under `mcp_servers:` in `litellm/config.yml` (see
   [`deploy/litellm-mcp-snippet.yaml`](deploy/litellm-mcp-snippet.yaml)).
   **Do not edit the live proxy config directly** — stage a proposed config
   and have the operator swap it in, then restart `litellm`.
3. Open `http://thor.local:3000` on the homelab network (LAN-only, no auth —
   bound to the LAN IP, not `0.0.0.0`).

## Identity & keys

Same key-forwarding pattern as `mcp_sessions` / `mcp_skills` / `mcp_memory`:
the caller's LiteLLM key is forwarded to the container by the proxy
(`extra_headers: [Authorization]` on the `mcp_kanban` entry) and the
container reads it as the `Authorization: Bearer <key>` on `/mcp`.

Two differences from the thin-client servers (this is a stateful service,
not a client over skill-runner):

- **No per-user data isolation** — the board is a single shared homelab
  resource. The guardrail is *per-key capability scoping* instead:
  `MCP_KEY_CAPABILITIES` maps a key's tail to a capability set
  (`read` ⊂ `control` ⊂ `admin`). Homelab defaults: chuck → `admin`,
  dylan → `control`. Unknown keys are rejected with a clear error.
- **Dual key role** — the container's `LITELLM_API_KEY` (the homelab
  service key) is used both for outbound LLM calls (groom/task/QA/summary)
  and as the "kanban key" that always gets the full tool set on `/mcp`.
- **Per-user spend attribution (Phase 2)** — `USER_KEYS` maps owner names to
  full LiteLLM keys. Every agent session (grooming/task/QA/summary) picks a
  *key profile* by the work item's owner: a mapped owner runs on a
  per-user agent dir (`/data/pi-agent-<name>`, own `auth.json` +
  `ModelRuntime`) so LiteLLM bills the spend to the user's key/budget;
  no owner or an unmapped owner falls back to the service key. Usage rows
  carry the owner, which the reports page renders as a per-user spend trend
  (rolling 12 months; per-project and total span all keys).

The web UI has no auth by design (LAN-only, bound to the LAN IP). The
`/mcp` endpoint is key-gated even on the LAN port.

## MCP usage

The container exposes its tools as an MCP server over streamable HTTP at
`POST /mcp` on the same Fastify app. It is registered with the LiteLLM proxy
(`mcp_kanban`, `transport: http`), so clients normally reach it through the
proxy's MCP gateway; the proxy forwards the caller's LiteLLM key, and the
container scopes the tool set per key (see "Identity & keys").

Tools (23; thin layer over the same service functions the read-only web UI
uses for its status views):

| Group | Tools |
|---|---|
| Ideas | `list_ideas`, `add_idea`, `edit_idea` (state `idea` only), `discard_idea` (soft delete) |
| Grooming (interactive) | `start_grooming` (seed turn: the LLM researches, states assumptions, asks questions), `groom_message` (one blocking turn), `groom_status` (poll: state, turn-in-flight, transcript tail, spec), `groom_accept` (background finalize → icebox), `groom_cancel`, `groom_re_groom` (fresh session) |
| Icebox | `move_to_backlog` (one or more; tasks inherit the idea's owner) |
| Board | `start_task`, `pause_task`, `resume_task`, `stop_task`, `retry_deploy`, `restart_task` (needs-attention → Backlog, optional resolution note) |
| Status | `board_status` (task counts + idea pipeline counts `ideaCounts` + needs-attention summaries + running), `task_status` (state, log tail, usage, failure reason), `project_status` (incl. LLM state summary + icebox listing) |
| Projects | `list_projects`, `get_project`, `create_project`, `update_project`, `delete_project` (admin; 409 while a task is running/deploy) |

**Owner attribution:** the web UI is read-only, so every mutation is
authenticated (a LiteLLM key) and stamped with the caller's owner (full-key
match against `USER_KEYS`; the kanban key → `kanban`). Projects/ideas are
stamped at creation; tasks inherit the idea's owner.

Example client config (direct to the container on the LAN; via the proxy,
use the proxy's MCP gateway URL — the proxy forwards your LiteLLM key):

```json
{
  "mcpServers": {
    "mcp_kanban": {
      "type": "http",
      "url": "http://192.168.4.54:3000/mcp",
      "headers": { "Authorization": "Bearer <your LiteLLM key>" }
    }
  }
}
```

## Project layout

```
mcp/servers/kanban/
├── Dockerfile
├── entrypoint.sh          # harness skills pull + model validation, then start
├── deploy/
│   └── litellm-mcp-snippet.yaml   # mcp_servers entry for litellm/config.yml
├── .env.example
├── README.md
├── package.json
└── src/
    ├── main.ts            # bootstrap: config, db, http, mcp, orchestrator
    ├── config.ts          # .env parsing/defaults + startup validation
    ├── db/                # Drizzle schema + migrations (sqlite/mysql); tables.ts = driver-conditional table objects (JSON columns map correctly on both drivers)
    ├── services/          # board, projects, ideas, tasks, usage (transport-agnostic)
    ├── http/              # Fastify routes + HTMX templates
    ├── charts.ts          # server-rendered SVG chart helpers
    ├── mcp/               # MCP tool layer over services
    ├── orchestrator.ts    # queue, slots, dependency gating, watchdog, cleanup
    ├── skills.ts          # harness clone/pull at startup
    └── agent/             # Pi session lifecycle (task / grooming / QA / summary)
```
