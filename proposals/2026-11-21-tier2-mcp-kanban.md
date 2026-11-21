# mcp_kanban — ai-kanban as the 14th homelab MCP server

- slug: tier2-mcp-kanban
- date: 2026-11-21
- status: applied (2026-11-21: app code + compose entry + litellm config
  live; container built, running, and runtime-verified on thor —
  `/health` 200, board UI live at `thor.local:3000`, MCP key scoping verified
  (chuck admin 16 tools / dylan control 14 / unknown 401), MySQL migrations
  ran (7 tables), proxy registration + E2E verified (110 proxy tools,
  family-mcp-full access group extended), `KANBAN_GITHUB_TOKEN` set +
  verified (git ls-remote OK). All chuck action items done.)
- tier: 2
- target user: chuck
- source: workspace/ai-kanban (existing app, 46 TS files) + todo_mcp_kanban.md (decisions locked 2026-11-21)

## What
Transform the `workspace/ai-kanban` code into `mcp_kanban` — a stateful
self-contained Docker container (not a thin client) that:

- Exposes the kanban tools via the LiteLLM proxy's MCP tool listings
  (streamable HTTP at `POST /mcp`; tools surface BARE — native names
  like `list_projects`, no server prefix, same as the other 13 servers).
  Per-caller-key tool scoping: chuck `admin` (16 tools incl. project
  create/update), dylan `control` (14 tools — queue/groom/start/stop, no
  project admin), unknown keys 401.
- Serves the board web UI (Fastify + htmx) **LAN-only** — bound to
  `THOR_IP:3000` (presenton pattern), no auth (LAN trust).
- Owns its state: MySQL on Thor (DB `ai_kanban`, user `ai-kanban`; app runs
  versioned idempotent migrations at boot), in-process Pi agent sessions
  (groom/task/QA/summary roles via `matrix-coder`), and the task
  orchestrator (`KANBAN_CONCURRENT_TASKS`, default 1).
- Clones `choukalos/homelab-ai-harness` into `/data/harness` at startup so
  every agent session gets `agents-skills/`; validates the model against
  the proxy at boot (fail fast).

**Identity & keys (Phase 1):** inbound MCP auth is per-caller-key (the
proxy forwards the caller's LiteLLM key via `extra_headers: [Authorization]`;
key = user for access control). Outbound LLM work uses the service key
(`LITELLM_API_KEY` in the container). Per-user spend attribution is Phase 2
(design in `todo_mcp_kanban.md` Q2: `owner_user` capture + `KANBAN_USER_KEYS`
map + per-user Pi runtimes).

## Why
- The ai-kanban app exists and works, but lives outside the homelab: no
  container, no proxy registration, no homelab auth/identity pattern,
  LAN-inaccessible from the family network in a controlled way.
- Agents (pi sessions, skill runner) currently have no way to queue/groom/
  execute homelab work items by conversation; the board is the natural
  durable work queue for agent-initiated tasks (code, blog, media).
- Homelab convention: every tool provider is a standalone container on
  `ai-net` registered with LiteLLM — mcp_kanban is the 14th.

## Risk + rollback
**Medium.** New stateful service with a LAN-exposed (unauthenticated,
LAN-bound) web UI and outbound LLM spend via the service key.

- LAN exposure: port bound to `THOR_IP` only (not 0.0.0.0), no public
  route in Caddy, no Cloudflare tunnel — same trust model as presenton.
- Spend: all LLM work bills to the service key until Phase 2 attribution;
  `KANBAN_CONCURRENT_TASKS=1` caps concurrency.
- DB: dedicated DB + user with privileges on `ai_kanban.*` only
  (homelab convention, cf. `AI_DB_*`); app only creates tables.
- Rollback: `docker compose -f compose/compose.mcp.yml -p ai-mcp rm -sf
  mcp_kanban` + remove the `mcp_kanban` entry from `litellm/config.yml` +
  restart litellm. Data (MySQL tables, `/home/chuck/data/ai-kanban`) is
  left in place for re-attach.

## Files touched
- `mcp/servers/kanban/` — app (46 TS files) + Dockerfile + entrypoint.sh +
  `.env.example` + README + `deploy/litellm-mcp-snippet.yaml` + `.gitignore`
- `compose/compose.mcp.yml` — `mcp_kanban` service (env_file `../.env` —
  Compose v5 project dir is `compose/`, so `${...}` interpolation needs the
  repo `.env` visible there: symlink `compose/.env -> ../.env` (machine-local,
  gitignored) or a sourced shell; `env_file` alone does NOT feed interpolation)
- `litellm/config.yml.proposed-mcp-kanban` — full copy of live config + the
  `mcp_kanban` entry (14th server; `transport: http` — the only non-SSE MCP
  entry; verified supported in LiteLLM v1.104.0)
- `.env` — `# ===== mcp_kanban =====` block (machine-local): `KANBAN_MODEL`,
  `KANBAN_CONCURRENT_TASKS`, `KANBAN_MCP_KEY_CAPABILITIES`,
  `KANBAN_GITHUB_TOKEN` (empty — chuck action), `KANBAN_DB_USER/PASS/NAME`
- `todo_mcp_kanban.md` — decisions, Q2 design, status
- Docs: `mcp/README.md` + `mcp/servers/README.md` (kanban rows)

## Chuck action items (in order)
1. **GitHub token**: set `KANBAN_GITHUB_TOKEN` in `.env` (repo scope — the
   deploy stage pushes task branches / blog posts / media). The board runs
   without it; only the deploy stage's git push fails.
   **DONE 2026-11-21** — token set (chuck), container force-recreated to
   pick it up, verified: present in container env (40 chars), no config
   warning, `git ls-remote` against choukalos/homelab-ai-harness OK.
2. **LiteLLM swap**: replace `litellm/config.yml` with
   `litellm/config.yml.proposed-mcp-kanban` and restart
   (`docker compose -f compose/compose.ai-core.yml up -d litellm`).
   Restart severs active proxy sessions — pick a quiet moment.
   **DONE 2026-11-21** (chuck, manual restart).
3. **E2E through proxy** (after the swap): kanban tools visible in
   `/mcp-rest/tools/list`; call with chuck's key (full set) and dylan's
   key (control set).
   **DONE 2026-11-21** — required one extra fix: the `family-mcp-full`
   access group (`07c1acf8-...`) had to be extended with `mcp_kanban`
   (per-key MCP access is group-granted, default-deny — same step as the
   `mcp_sessions` addition 2026-11-21; updated via
   `PUT /v1/unified_access_group/<id>`). Results: 110 proxy tools
   (94 + 16 kanban, bare names, no collisions); chuck `list_projects`
   OK; dylan `list_projects` OK; dylan `create_project` refused
   (control < admin, correct); chuck `create_project` OK (row persisted
   in MySQL, test row removed); unknown key → 401.

---
_Drafted 2026-11-21 (pi, thor). Review with `cli/proposals.sh`; applying is a human decision._
_Applied 2026-11-21: board deployed + verified (8a2f212); proxy swap + access group + E2E same day._
