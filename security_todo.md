# Security Plan — LiteLLM Public Access + Homelab Hardening

> Created: 2026-09-06 (audit session 22:09–22:33; plan completed same evening)
> Status: **Phases 0–4 DONE (2026-11-15)** — Caddy key gate live on
> `llm.choukalos.com`, per-key MCP scoping (default-deny + `family-mcp-full`
> group), key hygiene (spend tracking on, orphan key deleted, dead keys
> removed), LAN exposure shrunk (all rebinds/mapping removals applied +
> verified; `ss -tlnp` matches expected survivors; device-side confirmations
> done from Mac Studio 2026-11-15). **Phase 7 DONE 2026-11-21** (docs sync —
> see §5). Phases 5–6 + 8
> not started (Phase 5 blocked on D4). Open WebUI removed 2026-11-15
> (9.3-O1 resolved by removal). Phase 9 (secrets management & rotation
> program) added as a **grooming stub** 2026-11-21. Phase 10 (host security
> monitoring & reporting) added 2026-11-24 after the `url565.planning.com`
> alert investigation (not started). Phase 11 (public-surface security
> monitoring — CF tunnel, InvestHub, blog, extensible registry) added
> 2026-11-24 (not started). Phase 12 (file bridge `mcp_filebridge` — unified
> file edge: public relay + work areas + publish targets; D10–D16 decided
> 2026-11-24) added 2026-11-24. **P12-A (public face) landed 2026-11-26**
> (task 16): `mcp_filebridge` service + Caddy cutover committed; **LIVE on
> thor 2026-11-26** — deploy runbook executed (build + start, cutover, public
> battery, kill switch, regression, port diff — all green; see task-16
> report "Deployed" section). **P12-B (MCP face + full default-deny registry
> + 1b tokens) + P12-C (publish engine + `file_publish` + thin publish-file
> wrapper) IMPLEMENTED 2026-11-26 (pi-long-task run 10f37f65) — pending
> deploy** (config-only wiring in place: compose mounts + `litellm/config.yml`
> entry; deploy runbook `docs/filebridge_p12bc_deploy.md`). Phase 13 (LiteLLM key
> lifecycle + `.env` consolidation — the agent-key driver; the decided slice
> of the Phase 9 stub) added 2026-11-26 (DONE 2026-11-26 — all 5 work items
> complete).
> Goal: only Chuck's and Dylan's LiteLLM keys may reach `llm.choukalos.com` /
> `siri.choukalos.com`; every other layer (LAN exposure, host firewall, key
> hygiene, monitoring) hardened in depth.

---

## 1. Findings (audit, 2026-09-06)

| # | Sev | Finding | Where | Fix |
|---|---|---|---|---|
| F1 | **HIGH** | `llm.choukalos.com` has **no key gate at Caddy** — `reverse_proxy http://litellm-proxy:4000` for all paths. Docs claim a `$LITELLM_PUBLIC_API_KEY` gate that does not exist in the Caddyfile. Auth relies entirely on LiteLLM's own key check. | `caddy/Caddyfile` `@llm` block | Phase 1 |
| F2 | **HIGH** | All **10 MCP servers** are `allow_all_keys: true` in LiteLLM → *any* valid key (incl. the public chuck/dylan keys) can drive home-LAN tools from the internet: `mcp_media` (GPU pipeline), `mcp_mysql` (DB reads), `mcp_filesystem` (**write** to workspace), `mcp_homelab_status` (docker ps/logs), `mcp_knowledge`, `mcp_vision`, `mcp_skills`, etc. | `litellm/config.yml` `mcp_servers:` | Phase 2 |
| F3 | MED | `chuck-remote` + `dylan-v2` keys: **no model scope, no budget, no RPM/TPM limits, no expiry**. | LiteLLM DB `LiteLLM_VerificationToken` | Phase 3 |
| F4 | MED | Spend tracking disabled (`disable_spend_logs: true`, `disable_spend_updates: true`) → budgets **cannot be enforced** even if set. | `litellm/config.yml` `general_settings` | Phase 3 |
| F5 | MED | **3 orphaned `default_user_id` keys** (no alias, $0.25 budget each; created 07-15 / 08-15 / 08-30 via the **LiteLLM dashboard UI**). Investigated 2026-09-06: zero references anywhere in the repo (compose/scripts/code/docs), zero spend, empty AuditLog, no request-log tables; all plausible consumers ruled out (open-webui → master key, pi → Chuck's key, skill-runner/mcp_* → master, CLI → SIRI_API_KEY). Conclusion: **manual test keys, safe to retire** (block → observe → delete). | LiteLLM DB | Phase 3 |
| F6 | MED | `LITELLM_MASTER_KEY == LITELLM_API_KEY` (same `sk-cb1678…` token) injected into 6 internal consumers (open-webui, presenton, mcp_knowledge, mcp_mysql, mcp_vision, skill-runner). Master key = proxy admin = all models + all MCP servers. Acceptable *while it stays internal* — which is exactly what Phases 1/4/5 guarantee. **2026-11-15: now 5 consumers** (open-webui removed). | `.env`, `compose/*.yml` | Phase 3 (document) + Phase 8 (internal-service key — decided) |
| F7 | MED | Wide `0.0.0.0` host bindings: MySQL `3306/33060`, Qdrant `6333`, LiteLLM `4000`, SearXNG `8088`, Open WebUI `3000`, monitoring stack `3001/8081/8082/9090/9091/9100`, `mcp_memory 8005`, crawl4ai `11235`. **ufw not running.** | `compose/*.yml`, host | Phase 4/5 |
| F8 | MED | `mcp_memory` (host `:8005`) has **no auth of its own** and falls back to `MEMORY_USER_KEY` (Chuck's key) when the caller sends none → any LAN client can search **Chuck's private memories** unauthenticated. **RESOLVED 2026-11-15 (Phase 4): host mapping removed** (no LAN consumers per log audit). | `compose/compose.mcp.yml`, `mcp/servers/memory/server.py` | Phase 4 ✅ |
| F9 | LOW | sshd config not fully verified (password auth / root login status unknown). | host | Phase 5 |
| F10 | LOW | Stale docs: `thor_public_access_model.md` describes a `$LITELLM_PUBLIC_API_KEY` gate and key table that don't match reality. | `docs/` | Phase 7 |
| F11 | INFO | `.env` key consumers confirmed (2026-09-06): `LITELLM_PUBLIC_API_KEY` is **dead** (assigned to an unused variable in `lib/litellm-keys.sh:12`, passed to the litellm-proxy container env but unused; Caddy never used it) → remove. `SIRI_API_KEY` **in use** (`cli/run-skill.sh` legacy mode, `cli/verify_attribution.sh` T7) and `HARNESS_API_KEY` **in use** (open-webui → skill-runner harness) → keep. **2026-11-15: `LITELLM_PUBLIC_API_KEY` removed (Phase 3); `HARNESS_API_KEY` also removed** (its only consumer, open-webui, was removed the same day). | `.env`, `lib/litellm-keys.sh`, `cli/*.sh` | Phase 3 |

### Key inventory (live, 2026-09-06)

| key_alias | user_id | scope | budget | rpm/tpm | notes |
|---|---|---|---|---|---|
| `chuck-remote` | chuck | none (all models + all MCP) | none | none | public (llm + siri routes) |
| `dylan-v2` | dylan | none (all models + all MCP) | none | none | public (llm + siri routes) |
| `memory-service-v3` | memory-service | models: matrix-coder, homelab-embedding-v1, embeddings | none | none | internal (skill-runner mem0) |
| *(no alias)* | default_user_id | none | $0.25 | none | created 2026-07-15 via dashboard UI — **orphaned test key** (investigated, F5) |
| *(no alias)* | default_user_id | none | $0.25 | none | created 2026-08-15 via dashboard UI — **orphaned test key** (investigated, F5) |
| *(no alias)* | default_user_id | none | $0.25 | none | created 2026-08-30 via dashboard UI — **orphaned test key** (investigated, F5) |
| master (`sk-cb1678…`) | — | admin, everything | — | — | internal services only (F6) |

### Key inventory (live, 2026-11-15 — after Phases 2–3)

| key_alias | user_id | scope | budget | rpm/tpm | notes |
|---|---|---|---|---|---|
| `chuck` | chuck | all models | none (family decision: no cap) | none (D2b: no rate limits, decided 2026-11-15) | public (llm + siri routes); MCP: all 14 via `family-mcp-full` group |
| `dylan` | dylan | all models | none | none | public (llm + siri routes); MCP: all 14 via `family-mcp-full` group |
| *(no alias)* | — | models: matrix-coder, homelab-embedding-v1 | none | none | internal (skill-runner mem0, `MEMORY_LITELLM_KEY`); MCP: **none** (default-deny, Phase 2) |
| *(no alias, `sk-...sOsg`)* | default_user_id | all models | $1 | none | **DELETED 2026-11-15** — F5 orphan; blocked same day, then deleted (observation window waived — already expired 2026-10-05, zero spend). (The other 2 F5 orphans, created 07-15 / 08-15, were already deleted before 2026-11-15.) |
| master (`sk-cb1678…`) | — | admin, everything | — | — | internal only (F6); MCP: all 14 via `admin_view_unscoped` (verified in v1.104.0 source) |

**2026-11-21 refresh (Phase 7):** no key adds/removals since 2026-11-15
(verified live: 3 keys + master). MCP counts updated — `family-mcp-full`
extended to all **14** servers (+`mcp_sessions`, +`mcp_kanban`, both
2026-11-21; group description in the DB records the same).

---

## 2. Travel question (from the audit session)

**MCP tooling WILL work away from home.** The MCP servers run as Docker
containers on Thor's LAN; your Mac only talks to `llm.choukalos.com` through
the Cloudflare Tunnel. Tool calls execute *server-side* on the LAN — the
media pipeline / MySQL / Qdrant calls you saw using internal IPs are made by
the MCP containers, not by your Mac. The real risk is the reverse direction:
a remote caller can *drive* home-LAN tools. Phases 1–2 shrink exactly that.

---

## 3. Target state

```
Internet → Cloudflare Tunnel → Caddy (key gate: chuck OR dylan key only)
                                  → LiteLLM (per-key MCP/model scoping, budgets)
                                  → MCP containers (LAN, docker-net only)
LAN      → ufw (192.168.4.0/24 only) → services bound to THOR_IP, not 0.0.0.0
```

- Public API surface = 2 human keys, each with model + MCP scope, budget, and rate limits.
- No admin routes, no unscoped keys, no unauthenticated LAN paths to personal data.
- Every public route logged; 401 spikes and spend spikes visible in Grafana.

---

## 4. Recommended Approach

**Order matters: close the public surface first, then key hygiene, then LAN.**
Phases 0–3 are the trip-critical set; 4–5 are local hardening that should be
done at home with a LAN client nearby.

### Session A — Public surface (before the trip, ~1–2 h)

| Step | Phase | Why first |
|---|---|---|
| Backup + key snapshot | 0 | Rollback safety net for everything below |
| Caddy key gate on `llm.choukalos.com` | 1 | Biggest single exposure: a public route with no gate. After this, only the chuck/dylan keys can reach the proxy at all. |
| Per-key MCP scoping (kill `allow_all_keys`) | 2 | Second biggest: valid keys currently unlock all 10 home-LAN MCP tools from the internet. |
| Key hygiene (guardrails, retire orphans + dead key) | 3 | Caps the blast radius of a leaked key; cleans up dead/unknown keys. |

After Session A, verify:
- [x] Public routes accept only the two family keys (negative-tested with a wrong key) — 2026-11-15 (Phase 1: wrong/no key → 401 on `llm.choukalos.com`; ungrouped key → 0 MCP servers)
- [x] MCP tooling verified working from outside the LAN (Mac Studio on cellular) — confirms the trip story end-to-end — **verified 2026-11-15**: Chuck used the chuck key remotely from Houston ~3 weeks (M–Thu) covering the travel story, and the new gated path was verified the same day via CF edge → tunnel → caddy with live `mcp_search` tool calls on both family keys.
- [x] Commit + push (config changes are git-tracked) — 2026-11-15 (`191572b`, `eb0542b`, `67ef257`, `fec6483`)

### Session B — LAN + host (when home, LAN client nearby, ~1 h)

| Step | Phase | Notes |
|---|---|---|
| Port rebinds / mapping removals | 4 | One compose stack at a time; verify the consumer before each change; keep a LAN client open to smoke-test after each recreate |
| ufw + SSH hardening | 5 | Do ufw **last** in this session, and only from a LAN session (a remote-session misstep could lock you out) |

### Session C — Detection + docs (anytime, ~30 min)

Phases 6–7: 401/spend alerts, key-audit script, rotation cadence, doc sync.
Phase 8 (internal-service key) is independent — any time.

### Sizing / risk notes

- **Highest-leverage 30 minutes:** Phase 1 alone (the Caddy gate). If time is
  short before leaving, do Phase 0 + 1 and nothing else.
- **Do not do Phase 4/5 while traveling** — you need LAN access to verify, and
  a ufw mistake from a remote session can lock you out.
- **Phase 2 is the one change that can alter daily behavior** (e.g. Dylan's
  tool access). Test each family key end-to-end (a real tool call per key) before closing the laptop.
- Every phase has a one-step rollback (documented per phase); Phase 0 backups
  make all of them safe.

---

## 5. Phases

### Phase 0 — Backup & baseline (do first, every time) — **DONE 2026-11-15**

- [x] `git add -A && git commit` (Caddyfile, litellm config, compose, .env is gitignored — copy it separately):
      `cp .env /home/chuck/data/backups/env-$(date +%F).bak && chmod 600 /home/chuck/data/backups/env-$(date +%F).bak`
      — tree clean at `d6b0241` (nothing to commit); `.env` → `/home/chuck/data/backups/env-2026-11-15.bak` (600)
- [x] `bash scripts/backup-memory.sh` (Qdrant snapshot)
      — `mem0_memories-20261115-0021.snapshot` + `env-20261115-0021.env` in `/home/chuck/data/backups/`
- [x] Snapshot LiteLLM key table (read-only):
      — `/home/chuck/data/backups/keys-2026-11-15.txt` (4 keys: `chuck`, `dylan`,
      model-scoped memory-service key, **1** orphaned `default_user_id`
      `sk-...sOsg` — 2 of the 3 F5 orphans already gone since 2026-09-06)
- [x] Record current port state: `ss -tlnp | grep LISTEN > /tmp/ports-$(date +%F).txt`
      — `/home/chuck/data/backups/ports-2026-11-15.txt` (38 lines; F7 bindings
      confirmed: 3306/6333/4000/8088/3000/monitoring/8005/11235 on 0.0.0.0;
      skill-runner on 192.168.4.54:8091)

### Phase 1 — Caddy key gate on `llm.choukalos.com` (public = chuck/dylan only) — **DONE 2026-11-15**

Makes Caddy the first line of defense: even if LiteLLM auth is misconfigured,
only the two family keys can reach the proxy over the public route.

- [x] Replace the `@llm` block in `caddy/Caddyfile`:

```caddy
@llm host llm.choukalos.com
handle @llm {
	# Key gate: only Chuck's or Dylan's LiteLLM key (X-Api-Key header, or
	# Authorization: Bearer <key> for OpenAI-SDK clients). Everything else 401.
	# Same expression shape as the existing siri gate (De Morgan of OR-of-keys).
	@noAuth expression {http.request.header.X-Api-Key} != '{$LITELLM_KEY_CHUCK}' && {http.request.header.X-Api-Key} != '{$LITELLM_KEY_DYLAN}' && {http.request.header.Authorization} != "Bearer {$LITELLM_KEY_CHUCK}" && {http.request.header.Authorization} != "Bearer {$LITELLM_KEY_DYLAN}"
	respond @noAuth "Unauthorized" 401
	reverse_proxy http://litellm-proxy:4000
}
```

- [x] `docker exec caddy caddy reload --config /etc/caddy/Caddyfile` (or restart the caddy container)
      — `caddy validate` green, reloaded 2026-11-15; gate merged with the
      existing reverse_proxy options (flush_interval -1 + header_up kept)
- [x] Verify (from outside the LAN, e.g. Mac Studio) — verified 2026-11-15
      via the public URL (thor → CF edge → tunnel → caddy, the full public
      path):
  - [x] `curl -s https://llm.choukalos.com/v1/models -H "X-Api-Key: $LITELLM_KEY_CHUCK"` → 200
  - [x] same with Dylan's key → 200
  - [x] same with a wrong key → **401**
  - [x] no key → **401**
  - [x] `Authorization: Bearer <chuck key>` → 200 (and dylan Bearer → 200)
- [x] Verify `siri.choukalos.com` still works (unchanged): `/siri/*` + `/api/*` with both keys → 200; wrong key → 401.
      — 2026-11-15: `/siri/api/schedule` chuck 200 / dylan 200 / wrong 401; `/health` 200; 401 body = "Unauthorized"
- [x] **Note for the future:** the siri route only accepts `X-Api-Key` (not `Bearer`). iOS Shortcuts use `X-Api-Key` — fine today; if a client needs `Bearer` there, mirror the expression above. (Documented in the Caddyfile comment.)
- [x] **Key-rotation procedure (document in Phase 7):** when rotating `LITELLM_KEY_CHUCK`/`LITELLM_KEY_DYLAN`, update `.env` **and** reload Caddy, or the public routes break. (Note added to the Caddyfile comment 2026-11-15; formal doc in Phase 7.)

Rollback: restore previous Caddyfile block + reload.

### Phase 2 — Per-key MCP scoping (kill `allow_all_keys`) — **DONE 2026-11-15**

With Phase 1 done, the public path only carries chuck/dylan keys — but those
keys currently unlock **all 12 MCP servers** (12, not 10 — `mcp_datahub` and
`mcp_memory` were added after the 2026-09-06 audit). Scope them explicitly
(default-deny; grant what each key needs).

**Decision (Chuck, 2026-11-15): both family keys get ALL MCP tools incl.
skill runner** → one group `family-mcp-full` with all 12 servers + both keys.

**Decision matrix (default = both family keys get everything; tighten Dylan's if desired — see §6):**

| MCP server | chuck | dylan | memory-service | default_user_id keys |
|---|---|---|---|---|
| mcp_search, mcp_crawl, mcp_knowledge, mcp_filesystem_readonly, mcp_mysql | ✅ | ✅ | ❌ | ❌ (verify need first) |
| mcp_media, mcp_vision (long GPU jobs) | ✅ | ✅ | ❌ | ❌ |
| mcp_homelab_status (docker ps/logs) | ✅ | ✅ | ❌ | ❌ |
| mcp_filesystem (**write** to workspace) | ✅ | ✅ *(decision point)* | ❌ | ❌ |
| mcp_skills (runs family skills) | ✅ | ✅ | ❌ | ❌ |

Mechanism (verified against installed source, litellm **v1.104.0** — bumped
from the v1.92 the original plan was researched on):

- [x] Remove `allow_all_keys: true` from **all 12** entries in `litellm/config.yml` (keep `url`, `timeout`, `extra_headers` as-is). Default is `false` = deny.
      — done 2026-11-15 (12/12 removed, YAML validated; config bind-mounted
      at `/app/config.yaml:ro`, takes effect on restart)
- [x] Restart `litellm-proxy` (config reload) — **Chuck's step** (standing
      rule: he runs litellm restarts; a recreate drops in-flight sessions).
      `cd /home/chuck/homelab && docker compose -f compose/compose.ai-core.yml --env-file .env restart litellm`
      — restarted 2026-11-15 (note: `up -d` is a no-op here — the compose
      definition is unchanged, only the bind-mounted config changed; a plain
      `restart` re-reads it).
- [x] Grant via **access group** (single place to manage; API verified present in v1.104.0):
  - [x] Get key IDs (hashed `token` field): `GET /key/info` (NOT `/v1/key/info` — 404 in v1.104) with each key
        — chuck `96f581ff…aea407`, dylan `41f50f3e…669ea` (full hashes in git history / this section's create call)
  - [x] Create group with master key: `POST /v1/access_group`
        — created 2026-11-15: `family-mcp-full`
        (`07c1acf8-ffb6-4dbc-918d-9c7199f76fa1`), 12 server IDs, both family keys.
        `assigned_key_ids` = hashed tokens (verified in source:
        `_sync_add_access_group_to_keys` matches `LiteLLM_VerificationToken.token`).
        DB check: both key rows carry `access_group_ids = {07c1acf8-…}`.
  - [ ] (If Dylan gets a narrower set later: second group `dylan-mcp-scoped` with his subset + his key only; a key in two groups gets the union — so use exactly one group per key.)
- [x] `memory-service` key: leave with **no** MCP grant (models only) — default-deny covers it.
- [x] `default_user_id` key: no grant (blocked in Phase 3 anyway).
- [x] **Master key behavior (verified in v1.104.0 source, not just the old v1.92 note):** `mcp_server_manager.get_allowed_mcp_servers` → `admin_view_unscoped(user_api_key_auth)` = admin view + no explicit `object_permission.mcp_servers` → **whole registry**. Master key (proxy admin, no object_permission) still sees all 12 after the change → internal containers (skill-runner, mcp_*) that authenticate with it are unaffected. Documented in thor_public_access_model.md (Phase 7).
- [x] Verify per key (each from the public URL, after Phase 1) — endpoint is
      `GET /v1/mcp/tools` (per-key tool listing incl. access groups; tool names
      are `mcp_<server>-<tool>`). Baseline pre-restart: chuck sees 89 tools / all 12 servers.
      — verified 2026-11-15 post-restart:
  - [x] chuck key → 12 servers (89 tools, via `family-mcp-full`)
  - [x] dylan key → 12 servers (89 tools, via `family-mcp-full`)
  - [x] memory-service key (LAN) → **0** MCP servers (89 → 0: default-deny proven live)
  - [x] negative: a key not in any group → 0 servers / 403 on tool call
        (temp key `phase2-negative-test` generated → 0 tools / 0 servers → deleted)
  - [x] master key (LAN) → 12 servers (admin_view_unscoped — expected, documented)
- [x] Smoke-test one tool end-to-end per family (e.g. `mcp_search.search_web` via `llm.choukalos.com` with each key).
      — verified 2026-11-15: `mcp_search-search_web` via MCP streamable-HTTP on
      `https://llm.choukalos.com/mcp` returned live results with **both** chuck's
      and dylan's keys (full public path: CF → tunnel → caddy gate → litellm → mcp_search).
      Internal consumers unaffected: skill-runner memory health `healthy: true`,
      live search 6 hits / `degraded: false`, zero auth errors in 30 min of logs.

Rollback: re-add `allow_all_keys: true` + restart litellm-proxy (or delete the access group: `DELETE /v1/access_group/{id}`).

### Phase 3 — Key hygiene (guardrails, retire orphans + dead key) — **DONE 2026-11-15**

- [x] **Enable spend tracking** (prerequisite for budgets): in `litellm/config.yml` set `disable_spend_logs: false`, `disable_spend_updates: false`; restart litellm-proxy.
      — config edited 2026-11-15; takes effect on the Phase 3 recreate (below)
- [x] **Set limits on the two public keys** — family decision (2026-09-06): **no budget cap** (power users). Rate guardrails pending D2b:
      — resolved 2026-11-15: **no budget cap, no rate limits** (D2b decided: none).
      No limits set on either public key; spend tracking (above) is the
      visibility layer instead.
- [x] **Retire the orphaned `default_user_id` keys** (investigation complete 2026-09-06 — see F5: dashboard-created test keys, zero repo references, zero spend):
      — only **1 of the 3** remained in the DB on 2026-11-15 (`sk-...sOsg`,
      `3409157c…d8a9`); the other two (created 07-15 / 08-15) were already deleted.
      It was also already **expired 2026-10-05** (doubly dead).
  - [x] confirm with Dylan that none of the 3 was pasted into a client — Chuck approved proceeding 2026-11-15; zero spend + F5 consumer ruling-out + the other 2 already deleted make this low-risk; block (not delete) keeps it reversible
  - [x] **block** (soft, reversible) — done 2026-11-15 via `POST /key/block` with the
        key hash (note: `./homelab.sh key block default_user_id` fails — `/key/list`
        excludes this key so the CLI hash lookup can't find it; the API takes the
        hash directly). DB: `blocked = t`
  - [x] observe a few days — any breakage means someone was using one → unblock + investigate
        — observation window waived 2026-11-15 (Chuck): key was blocked AND
        already expired 2026-10-05, zero spend, F5 ruled out all consumers
  - [x] **delete**: `POST /key/delete` with the same hash (after observation)
        — **deleted 2026-11-15** (`deleted_keys` confirmed; DB now holds
        exactly chuck, dylan, memory-service)
- [x] **Retire the dead `.env` key** (consumer check done 2026-09-06):
  - [x] remove `LITELLM_PUBLIC_API_KEY` from `.env` + `compose/compose.ai-core.yml` (litellm service env) + the unused variable at `lib/litellm-keys.sh` + the mention in the `homelab.sh` header comment
        — done 2026-11-15 (all 4 sites); leaves the running container's env on the Phase 3 recreate
  - [x] **keep** `SIRI_API_KEY` (in use: `cli/run-skill.sh` legacy mode, `cli/verify_attribution.sh` T7) and `HARNESS_API_KEY` (in use: open-webui → skill-runner harness) — consumers documented in `docs/thor_public_access_model.md` (pulled forward from Phase 7, done 2026-11-15)
        — postscript 2026-11-15: open-webui was removed the same day (owner
turns out it was unused), so `HARNESS_API_KEY` (its only consumer) was also
removed from `.env`; `SIRI_API_KEY` stays.
- [x] **Document master-key usage** (F6): note added to `docs/thor_public_access_model.md` — `LITELLM_MASTER_KEY == LITELLM_API_KEY` is internal-only by design (docker network + LAN only after Phases 4/5); full doc re-synced 2026-11-15 (F10: stale `$LITELLM_PUBLIC_API_KEY` gate description replaced with the live Caddy key gate + current key table + MCP groups + rotation procedure).
- [x] **Dedicated `internal-service` key** — decided 2026-09-06 (was optional): see **Phase 8** (not started).
- [x] Re-run the key inventory snapshot (Phase 0 command) and paste the new table into §1 for the record — done 2026-11-15 (see §1, "Key inventory (live, 2026-11-15)").

**Phase 3 apply step (Chuck):** `up -d litellm` — this time it **recreates** (the compose env changed: `LITELLM_PUBLIC_API_KEY` line removed), which loads the spend-tracking config AND drops the dead key from the container env:
`cd /home/chuck/homelab && docker compose -f compose/compose.ai-core.yml --env-file .env up -d litellm`
Verify after: (1) container env has no `LITELLM_PUBLIC_API_KEY`, (2) spend tracking live (new requests log spend; `key list` spend column moves), (3) sanity: chuck key 200 on `/v1/models` via public URL, MCP visibility unchanged (chuck 12 / memory-service 0).
— **applied + verified 2026-11-15:** recreate done (Up, healthy);
(1) container env: 0 matches for `LITELLM_PUBLIC_API_KEY` (only
LITELLM_MASTER_KEY + LITELLM_API_KEY remain); (2) spend tracking live:
`LiteLLM_SpendLogs` rows writing (4 rows, newest seconds old, full
request/response + per-call spend; key spend field moving $1.21 → $1.47);
(3) chuck 200 on public `/v1/models`; MCP visibility unchanged (chuck
89 tools / 12 servers, memory-service 0). Note: the spend-log tables did
not exist at all (spend logs had been off since before the 2026-09-06
audit) — LiteLLM created them on the first logged request after the flip.

Rollback: budgets/limits are per-key DB rows — revert via `/v1/key/update`; `.env` restore from Phase 0 backup.

### Phase 4 — Shrink LAN exposure (rebind / remove host port mappings) — **DONE 2026-11-15**

Principle: containers talk over the docker network (`ai-net`); host port
publishing is only for things a human needs from another machine.

| Port (owner) | Current | Action | Verify consumer first |
|---|---|---|---|
| `3306/33060` (mysql) | 0.0.0.0 | bind `192.168.4.54:3306:3306` | skill-runner uses `MYSQL_DB_HOST=thor.local` → THOR_IP binding keeps it working |
| `6333` (qdrant) | 0.0.0.0 | **remove host mapping** (or THOR_IP) | `MEMORY_QDRANT_URL=http://qdrant:6333` = docker DNS; check `compose.mcp.yml` QDRANT_URL too |
| `4000` (litellm-proxy) | 0.0.0.0 | bind `192.168.4.54:4000:4000` | LAN clients (open-webui, the former main consumer, was removed 2026-11-15 — check remaining LAN consumers before rebinding) |
| `8088` (searxng) | 0.0.0.0 | **remove host mapping** | mcp_search calls `http://searxng:8080` (docker DNS) — confirm |
| ~~`3000` (open-webui)~~ | — | **REMOVED 2026-11-15** (service gone; no rebind needed) | — |
| `3001` (grafana), `8081` (cadvisor), `8082` (plausible), `9090/9091` (victoria-metrics), `9100` (node-exporter) | 0.0.0.0 | bind to `192.168.4.54:` | monitoring is LAN-admin only |
| `8005` (mcp_memory) | 0.0.0.0, **unauthenticated, falls back to Chuck's key (F8)** | **remove host mapping** | consumers reach it via `mcp_memory:8000` on ai-net (LiteLLM config) — confirm no direct LAN client |
| `11235` (crawl4ai) | 0.0.0.0 | **remove host mapping** | mcp_crawl uses docker DNS — confirm |
| `80/443` (caddy) | 0.0.0.0 | keep | tunnel + LAN |
| `22` (ssh) | 0.0.0.0 | keep; restrict source in Phase 5 | — |

**Consumer verification (done 2026-11-15):**
- qdrant 6333: 6 thor scripts defaulted to `localhost:6333` (backup-memory/kb/nas/restore, reembed-memory, memory-regression) → **rebind to THOR_IP** (not full removal) + script defaults updated to `192.168.4.54:6333`. Docker-DNS consumers (mcp_knowledge `QDRANT_URL=http://qdrant:6333`, skill-runner `MEMORY_QDRANT_URL`) unaffected.
- litellm 4000: `lib/litellm-keys.sh` (`LITELLM_PROXY` default 127.0.0.1:4000), `scripts/reembed-memory.py`, `scripts/mcp-verify.py` used localhost → defaults updated to `192.168.4.54:4000`. VictoriaMetrics scrapes `host.docker.internal:4000` (LAN IP — unaffected). `skills/deep_research/skill.py` default is dead (runner injects `litellm-proxy:4000`). CLI `LAN_BASE` already used the LAN IP.
- searxng 8088: only consumer is mcp_search via docker DNS (`searxng:8080`) → removed.
- crawl4ai 11235: only consumer is mcp_crawl via docker DNS → removed.
- mcp_memory 8005: **log audit 2026-11-15: zero Mac traffic** (172.18.x docker-bridge only + 1 hit from thor itself) → removed (F8 closed). Mac pi uses skill-runner `/api/memory/*` (8091).
- mysql 3306: data-hub/report-hub/mcp_mysql/skill-runner all use `thor.local` (=192.168.4.54) → THOR_IP bind keeps them. No host scripts use localhost:3306.
- monitoring: VM promscrape targets are docker DNS / `host.docker.internal` → host binds are human-only.

**Applied 2026-11-15 (safe stacks):** qdrant + searxng + crawl4ai (ai-core), monitoring stack (5 services + 9091), mcp_memory (mcp) recreated. Verified: `ss -tlnp` shows the new binds; qdrant reachable at 192.168.4.54:6333 (localhost now refused); MCP 89 tools / 12 servers (all connected via docker DNS); live `mcp_search.search_web` tool call OK; Grafana 200 at 192.168.4.54:3001.

**Applied + verified 2026-11-15 (both remaining items):**
1. litellm recreate (rebind 4000) — done; `192.168.4.54:4000` live (`/health/liveliness` → "I'm alive!"), public route + MCP 12 servers / 89 tools on chuck key (re-verified post-mysql-rebind).
2. MySQL rebind (host service, sudo) — done: `bind-address = 192.168.4.54` in `/etc/mysql/mysql.conf.d/mysqld.cnf` (mysqlx stays `127.0.0.1:33060`); `systemctl restart mysql` clean.

Verify after — **verified 2026-11-15**:
- (1) litellm at 192.168.4.54:4000 ✅ + public route 200 + MCP 12 servers / 89 tools (chuck key) ✅
- (2) mysql at 192.168.4.54:3306 ✅ — direct `mysql -h 192.168.4.54` OK for both `ai` (homelab, 10 tables) and `investor` (investorhub, 26 tables) users; data-hub `/api/health` ok (9811 transactions); report-hub 200; skill-runner `/health` 200 (note: endpoint is `/health`, not `/api/health`); mcp_mysql connected + processing MCP requests (log `1054 Unknown column` lines are LLM-SQL schema mismatches, not connectivity); invest-hub-server mysql2 connect with app DSN → `investorhub` ok; public `api.choukalos.com` 401 on protected route (auth working) + `invest.choukalos.com` client 200.

- [x] For each row: grep the consumer, change the compose `ports:` entry, `docker compose up -d <stack>` (recreate, no data loss — verify after).
- [x] Re-run `ss -tlnp | grep LISTEN` — expected survivors: `22, 80, 443, 192.168.4.54:{3306,4000,3001,8081,8082,9090,9091,9100,5000,6333,8091,8100,8101}` (3000 gone with OWUI; 33060 stays 127.0.0.1).
      — re-ran 2026-11-15: exact match (only extras: systemd-resolved `127.0.0.53/54:53`, host-internal, harmless).
- [x] Confirm from a LAN client (Mac Studio): Grafana, `llm.choukalos.com`, `siri.choukalos.com` all still work; confirm from a phone on a *different* network (cellular) that the public routes still work.
      — closed 2026-11-15: Mac Studio (LAN) confirmed Grafana + `llm.choukalos.com` live; public routes continuously in use from outside (incl. cellular) since Phase 1 verification.

Rollback: restore the `ports:` lines from git + recreate.

### Phase 5 — Host firewall (ufw) + SSH hardening

Defense in depth: even if a future service binds 0.0.0.0, only the home LAN
gets in. (Cloudflare Tunnel is outbound from the caddy container — an inbound
deny does **not** break it.)

- [ ] SSH baseline (F9): `sshd -T | grep -iE '^(passwordauthentication|permitrootlogin|kbdinteractiveauthentication|pubkeyauthentication)'`
  - [ ] ensure `passwordauthentication no`, `permitrootlogin no`, `pubkeyauthentication yes` (edit `/etc/ssh/sshd_config.d/`, `systemctl reload ssh`)
  - [ ] ⚠️ **LAN session only — do at home, not via the router OpenVPN.**
        Remote access currently rides the router's OpenVPN (Tailscale plan
        dropped 2026-11-06); a lockout mid-change would kill the only remote
        path. Tracked as a manual task in `docs/thor_manual_tasks.md`
        (Phase 16).
- [ ] ufw (draft — **discuss before executing**, see §6 open questions):
  ```bash
  sudo ufw default deny incoming
  sudo ufw default allow outgoing
  sudo ufw allow from 192.168.4.0/24          # home LAN (Thor 192.168.4.54, Mac Studio, phones)
  sudo ufw allow from 192.168.5.0/24          # second home subnet (Lego, Matrix, ...)
  sudo ufw enable
  sudo ufw status verbose
  ```
  (The explicit `port 22` rule is subsumed by the subnet allows; keep a narrower SSH-only rule only if we decide SSH should be tighter than the rest.)
- [ ] Verify after enable (do NOT do this from a remote session that isn't on the LAN):
  - [ ] LAN client can reach Thor (Open WebUI, SSH)
  - [ ] public routes (tunnel) still work from cellular
  - [ ] `ss -tlnp` unchanged (ufw doesn't rebind anything)
- [ ] **Open discussion (D4):** home has two subnets — `192.168.4.0/24` (Thor `192.168.4.54`, Mac Studio) and `192.168.5.0/24` (Lego, Matrix, ...). Questions to settle before executing:
  - [ ] Is `192.168.5.0/24` a separate VLAN/SSID with its own gateway? (If the router routes `.5 → .4`, the two subnet-allow rules above are sufficient — Thor's ufw only sees traffic addressed to Thor.)
  - [ ] Which Thor services do `.5` devices legitimately need (Open WebUI `:3000`, Grafana `:3001`, presenton `:5000`, skill-runner `:8091`)? Anything else from `.5` can be denied after Phase 4 rebinding.
  - [ ] Is there a guest network (third range)? If yes → default-deny covers it; confirm no guest device needs Thor.
  - [ ] SSH: allow both subnets, or `192.168.4.0/24` only?

Rollback: `sudo ufw disable`.

### Phase 6 — Monitoring & detection

- [ ] **401 spike alert** on `llm.choukalos.com` + `siri.choukalos.com` (Caddy access logs → Victoria Metrics → Grafana alert): sustained >N 401s/min = brute force or leaked key. (Exact metric wiring per `docs/thor_observability_plan.md`.)
- [ ] **Spend alert** per LiteLLM key (now that spend tracking is on, Phase 3): alert if `chuck`/`dylan` spend > $X/day.
- [ ] **Key audit script** `scripts/audit-litellm-keys.sh`: list keys (alias, user, budget, rpm/tpm, models, MCP group) + compare against the §1 inventory table; run monthly / after any key change.
- [ ] **Quarterly key rotation** cadence for `LITELLM_KEY_CHUCK` / `LITELLM_KEY_DYLAN` (rotate → update `.env` → Caddy reload → old key deleted in LiteLLM). GitHub PAT rotation has a one-command tool since 2026-11-21: `scripts/rotate-github-tokens.sh` (see `docs/thor_public_access_model.md` § Key Strategy → GitHub Tokens).
- [ ] Log-review habit: after any trip/absence, skim Caddy logs for 401s + LiteLLM spend for the period.

### Phase 7 — Docs sync — **DONE 2026-11-21**

- [x] `docs/thor_public_access_model.md` — **done 2026-11-15** (pulled forward with Phase 3; content re-verified 2026-11-15):
  - [x] `llm.choukalos.com` row: auth = Caddy OR-gate (chuck/dylan keys, `X-Api-Key` or `Bearer`), not `$LITELLM_PUBLIC_API_KEY`
  - [x] Key table: current inventory (Phase 3 output) incl. MCP access groups
  - [x] Add master-key-internal-only note (F6) + key-rotation procedure
- [x] `docs/thor_mcp_architecture.md`: note the 2026-08-25 `allow_all_keys` decision is **superseded** — per-key access groups now (Phase 2). **Landed 2026-11-20** (commit `4b130f4` docs refresh: Rules section carries the superseded note — "verified 2026-11-20", all 3 `allow_all_keys` references in the file now read as superseded); re-verified 2026-11-21.
- [x] Update this file: mark phases done with dates as they land; keep the §1 inventory table current. **Done 2026-11-21** — header status + Phase 7 marked; §1 table MCP counts refreshed 12/13 → 14 (live-verified: 3 keys + master, `family-mcp-full` = 14 servers).

---

### Phase 8 — Dedicated `internal-service` key (decided 2026-09-06)

Goal: internal containers stop using the master key; the master key becomes
admin-only (key management via `./homelab.sh key ...`, dashboard).

Master-key consumers found 2026-09-06 (6 services; **5 as of 2026-11-15** — open-webui removed):
| Service | Env var | Location |
|---|---|---|
| ~~open-webui~~ | ~~`OPENAI_API_KEY=${LITELLM_MASTER_KEY}`~~ | **removed 2026-11-15** (service gone) |
| presenton | `CUSTOM_LLM_API_KEY=${LITELLM_API_KEY}` | `compose/compose.ai-core.yml:179` |
| mcp_knowledge | `LITELLM_API_KEY=${LITELLM_API_KEY}` | `compose/compose.mcp.yml:22` (embeddings + vision fallback) |
| mcp_mysql | `LITELLM_API_KEY=${LITELLM_API_KEY}` | `compose/compose.mcp.yml:84` (matrix-coder nl→sql) |
| mcp_vision | `LITELLM_API_KEY=${LITELLM_API_KEY}` | `compose/compose.mcp.yml:152` (matrix-coder frame analysis) |
| skill-runner | `LITELLM_API_KEY=${LITELLM_API_KEY}` | `compose/compose.skill-runner.yml:17` |

- [ ] Mint key: `./homelab.sh key add internal-service --alias internal-service` (all models, **no MCP group**, no budget — internal trust; per-service model scoping is a later nicety)
- [ ] Add `LITELLM_KEY_INTERNAL=${sk-...}` to `.env` (Phase 0 backup first)
- [ ] Point each consumer env var above at `${LITELLM_KEY_INTERNAL}` — the litellm-proxy container keeps its own `LITELLM_MASTER_KEY`/`LITELLM_API_KEY` (the proxy needs its master key)
- [ ] Recreate affected containers one stack at a time; verify each (presenton render, MCP tool calls, skill run)
- [ ] Confirm the master key is now used only by: the litellm-proxy container itself + `./homelab.sh key ...` admin ops
- [ ] Update docs (Phase 7) + key inventory (§1)

Rollback: revert consumer env vars to `${LITELLM_API_KEY}`/`${LITELLM_MASTER_KEY}`, recreate, `./homelab.sh key delete internal-service`.

---

### Phase 9 — Secrets management & rotation program — **STUB (2026-11-21, groom with pi)**

> Status: **stub — groom before scoping.** Triggered by the 2026-11-21 GitHub
> token-rotation work (`scripts/rotate-github-tokens.sh` + the runner-token
> discussion). Goal: turn ad-hoc key handling into a program — inventory,
> delivery, rotation, breach response — and decide how far to move away from
> the single massive `.env`.
>
> **2026-11-26:** the LiteLLM/agent-key slice is scoped and decided as
> **Phase 13** (key lifecycle tooling, `.env` dedupe, alias-based capability
> map, agent key conventions) — the agent-driven subset of this agenda
> (items 1/2-lite/4 for the LiteLLM class). The rest of this agenda stands.

**Current state (facts, 2026-11-21):**
- One massive `.env` at repo root — 97 vars, ~30 secrets (LiteLLM keys,
  several MySQL users/passwords, Qdrant admin+RO, CF tunnel, GitHub PATs,
  JWT secrets, app-level keys). Perms `600`, gitignored. Single source of
  truth for every stack.
- Delivery to containers: compose `${...}` interpolation + `env_file: .env`
  whole-file injection on many services → **carrier problem**: ~13 containers
  (caddy, cloudflared, skill-runner, searxng, plausible, the hubs, …) carry
  ALL secrets in their env although most use only a few. `docker inspect`
  on any of them dumps the whole secret set.
- Rotation tooling (partial, per-secret): `scripts/rotate-github-tokens.sh`
  (GitHub classic PAT — API-minted, 2026-11-21), `scripts/rotate-cf-tunnel.sh`,
  `./homelab.sh key …` (LiteLLM), Caddy-reload procedure
  (`docs/thor_public_access_model.md` § Key Strategy). No orchestrator,
  no cadence, no runbooks for the rest (MySQL, Qdrant, app keys).
- Drift detection: `scripts/key-sync-check.sh` (2026-10-21 incident) —
  catches stale values in containers after a rotation. **Not** a leak detector.
- Known dead secret: `GITHUB_RUNNER_TOKEN` (fine-grained PAT, unconsumed —
  ~~revoke in UI + drop the `.env` line~~ **DONE 2026-11-21: revoked in UI,
  line removed from `.env`**).
- Known sharing: one classic PAT (`GITHUB_ACCESS_TOKEN`) powers 3 self-hosted
  runners + the mcp_kanban deploy stage (`KANBAN_GITHUB_TOKEN`, same value).
- `.env.bak-*` rotation backups were NOT gitignored (fixed 2026-11-21).

**Insights carried in from the 2026-11-21 GitHub rotation work:**
1. **Least-privilege scope per consumer.** Runners only need Actions r/w on
   their own repo (job checkouts use the ephemeral job token); kanban deploy
   only needs Contents r/w on its target repos. One `repo`-scope PAT for all
   of them is the anti-pattern (leak = everything).
2. **Classic vs fine-grained PAT trade-off.** Classic: coarse scope
   (`repo` = all repos) but what the runners currently expect. Fine-grained:
   per-repo + per-permission (least privilege). **Both are UI-only now** —
   GitHub removed the classic-PAT creation API endpoint (`POST /user/tokens`
   → 404, verified 2026-11-21), so rotation tooling is receive-and-verify:
   mint in the UI, script takes the token (`--new-token-file` or hidden
   paste), verifies it, applies it deterministically.
3. **Expiry as a safety net.** ~120-day expiry on a 90-day rotation cadence
   makes a forgotten rotation fail-closed instead of lingering.
4. **Rotation ≠ revocation.** A rotated token stays valid until revoked; every
   runbook must end with the revocation step (manual for GitHub classic PATs —
   no API for that).
5. **Discovery beats hardcoding.** Consumer discovery from compose source
   (name-based) + live env (value-based) caught the 4 real consumers AND the
   9 carriers; hardcoded lists go stale.
6. **GitHub App is the end-state for runners** (ephemeral installation tokens,
   no long-lived PATs); kanban could mint 1-h installation tokens at deploy
   time → zero long-lived push secrets. Bigger migration (runner image swap).
7. **Backups and temp files are secrets.** `.env.bak-*` and the mint-response
   temp file carry full secrets → gitignore + auto-prune + mktemp/trap
   discipline.

**Grooming agenda (open questions — decide before scoping):**
1. **Inventory.** Master secrets table: secret | issuer | consumers (env var,
   container) | scope | rotation cadence | revocation path (API/UI/manual) |
   breach response. Covers everything in `.env`, not just the ones with
   scripts today.
2. **Delivery.** Move from whole-`.env` injection to per-service env (each
   container gets only its vars). Options by effort: (a) compose
   `environment:` lists per service (no new tooling), (b) Docker secrets,
   (c) external manager (SOPS-encrypted `.env` / Vault). Decide target +
   migration order. (This is the "stop loading a massive .env" question.)
3. **Storage & at-rest.** `.env` is 600 + gitignored (good). Decide:
   encrypted off-host backup (age/SOPS), `.env.bak-*` lifecycle (auto-prune
   >30d?), secret scanning in CI (gitleaks) so nothing ever lands in git.
4. **Rotation program.** Per-class cadence (GitHub 90d, LiteLLM quarterly,
   CF per tunnel doc, MySQL/Qdrant annual or on personnel change, app keys
   annual). One `scripts/rotate-all.sh` orchestrator vs per-secret runbooks?
   Extend `thor_public_access_model.md` § Key Strategy to ALL secrets.
   (GitHub rotation script already has the receive-and-verify pattern —
   `--new-token-file` + hidden paste — since the PAT creation API endpoint
   was removed 2026-11-21; generalize it to other UI-only secrets.)
5. **Breach response.** Detection: GitHub audit log / abuse alerts, LiteLLM
   spend + 401 alerts (Phase 6), CF logs, key-sync-check (drift ≠ leak).
   Response runbook: **REVOKE first** (fastest kill-switch), then rotate, then
   investigate. One table-top exercise (simulate a leaked runner token).
6. **Least-privilege pass.** Per-consumer MySQL users (already done for
   ai-kanban — audit the rest), Qdrant RO vs admin, Phase 8 internal-service
   key (master key out of 5 consumers), retire dead secrets
   (~~GITHUB_RUNNER_TOKEN~~ — revoked + removed 2026-11-21).
7. **Runner tokens (2026-11-21 discussion).** Option A: per-repo fine-grained
   PATs (3 runners + 1 kanban push token; `--manual` rotation). Option B:
   GitHub App (runners + ephemeral kanban tokens). Working recommendation:
   **A now, B as end-state**.

**Exit criteria (stub → real phases when groomed):** inventory table complete +
committed; per-service env migration ordered; rotation runbook for every
secret class; one full rotation drill executed end-to-end (incl. revocation);
breach runbook + table-top done.

---

### Phase 10 — Host security monitoring & reporting — **ADDED 2026-11-24 (not started)**

> Trigger: the 2026-11-24 manual investigation (company security alert about
> `url565.planning.com` — result: **clean**; no mail stack on the host, no SMTP
> connections, zero trace of the domain, no external brute-force, only a few
> failed logins from Chuck's own LAN devices). That check was ad hoc; this
> phase makes it a standing daily baseline-diff scan with reporting. Complements
> Phase 6 (LiteLLM/Caddy-specific alerts) at the host layer.

**Design: baseline-diff.** The host has a known-good state (Phase 4 port
survivors, one human user, stock cron/timers, known container fleet, **no mail
binaries**). The scan diffs live state against a baseline file and reports
deviations. The baseline is refreshed only by explicit `--update` after an
intentional change — silent drift is the signal.

- [ ] **Baseline capture** `scripts/security-baseline.sh` → `/home/chuck/data/security/baseline.txt`:
  - [ ] `ss -tlnp` listeners (Phase 4 expected survivors are the expectation)
  - [ ] user accounts UID ≥ 1000 (expected: `chuck` only)
  - [ ] cron state: `/etc/crontab`, `/etc/cron.d/*`, `/var/spool/cron/crontabs/*` (list + hashes)
  - [ ] `systemctl list-timers --all` (unit names)
  - [ ] `docker ps -a` (names + images)
  - [ ] mail-tool watchlist (`sendmail msmtp ssmtp mail mutt swaks postfix`) — expected: **none present**
  - [ ] record capture timestamp; refresh only via explicit `--update` flag (auto-refresh would defeat the diff)
- [ ] **Daily scan** `scripts/security-scan.sh` + `scripts/systemd/security-scan-daily.{service,timer}` (mirror the `backup-nas-daily` pattern; root service, ~00:30 UTC off-peak):
  - [ ] **auth.log (last 24h):** failed passwords, invalid users, source IPs outside the known set (`10.8.0.2`, `192.168.4.0/24`, `192.168.5.0/24`) → anomaly
  - [ ] **port diff:** `ss -tlnp` vs baseline → new or removed listener = anomaly (a new listener is the classic implant signature)
  - [ ] **outbound connections:** ESTAB on SMTP ports (25/465/587) → immediate anomaly; new external peer IPs (excluding LAN + known CDN/Cloudflare ranges) → note
  - [ ] **account/cron/timer drift:** new UID ≥ 1000 users, new crontabs, new timers → anomaly
  - [ ] **container drift:** new/renamed containers vs baseline → anomaly (typosquatted image names are an attack vector)
  - [ ] **mail-tool appearance:** any watchlist binary now present → anomaly (this host should never send mail)
  - [ ] **sensitive-file changes:** mtime < 24h under `/etc` (apt/dpkg-managed filtered via `dpkg.log`), `/usr/bin`, `/usr/local/bin` → note
  - [ ] **process check:** long-running processes not attributable to a known container or host service → note
- [ ] **Daily report** → `/home/chuck/data/security/reports/security-report-YYYY-MM-DD.md`:
  - [ ] verdict line (`CLEAN` / `N anomalies` / `M notes`), each finding with evidence (command + output), full baseline-diff table
  - [ ] anomalies appended to `/home/chuck/data/security/alerts.log` (one line, machine-readable: `timestamp | severity | check | detail`)
- [ ] **Weekly digest** (weekly timer, same pattern): summarize the last 7 daily reports → `/home/chuck/data/security/reports/security-weekly-YYYY-Www.md` (anomaly counts, recurring notes, auth.log trends — e.g. "3 failed logins from 192.168.4.56 this week vs 0 last week")
- [ ] **Alert delivery (D7 — decide before wiring):** where do anomalies reach Chuck? Options: (a) file-only (`alerts.log`) + check on demand, (b) Siri/Shortcuts push (no notification path exists in the repo yet — would be net-new), (c) Grafana metric via `node_exporter_textfile` (`security_scan_anomalies_total`, `security_scan_last_run`) + dashboard panel. Working recommendation: **(c) + (a) now, (b) later**.
- [ ] **On-demand status:** `./homelab.sh security status` — latest report verdict, unread alert count, baseline age (stale baseline is itself a warning)
- [ ] **Retention:** prune daily reports > 90d, weekly digests > 52w (inside the scan)
- [ ] **False-positive tuning:** first 2 weeks = observation mode (report only, nothing escalated); then set thresholds from observed noise (apt upgrades, container recreates, Chuck's own LAN logins)

Rollback: `systemctl disable --now security-scan-daily.timer` (+ weekly); scripts are additive (new files only) — deletion is the full rollback. No service changes.

**Out of scope (tracked elsewhere):** LiteLLM 401/spend alerts (Phase 6), CVE cross-checks (§9-style periodic sessions), the work laptop (company-managed, not this host).

---

### Phase 11 — Public-surface security monitoring (tunnel + InvestHub + blog, extensible) — **ADDED 2026-11-24 (not started)**

> Trigger: the 2026-11-24 security check exposed the gap — Phase 10 covers the
> host, but the **internet-facing surface** (7 Caddy hostnames behind the
> Cloudflare Tunnel) is only monitored ad hoc (§9 CVE cross-check, §7 manual
> negative tests). This phase makes the public surface a standing,
> registry-driven monitoring target.
> **Extensibility rule: adding a public site = adding one registry entry**
> (11.0) — every check below reads the registry. The §11.6 runbook is the
> contract for future sites.

**Current public surface (verified 2026-11-24 from `caddy/Caddyfile` + `docker ps`):**

| Domain | Backend | Auth | Risk notes |
|---|---|---|---|
| `llm.choukalos.com` | caddy → litellm-proxy:4000 | Caddy key gate (chuck/dylan) | keys + all 14 MCP tools behind it |
| `siri.choukalos.com` | caddy → skill-runner:8091; `/dl`,`/upload` → **192.168.4.55:8189 (LAN service via tunnel)** — relay re-scoped in **Phase 12** | X-Api-Key on `/siri/*`,`/api/*`,`/upload` | LAN GPU host reachable publicly (gated) — canary the gate |
| `api.choukalos.com` | caddy → invest-hub-server:4000 | JWT on protected routes | **public user input + `investorhub` DB → 11.3** |
| `invest.choukalos.com` | caddy → invest-hub-client:80 (static) + invest-hub-server:4000 (API paths) | none (static) / JWT via API paths | client app |
| `choukalos.com` | caddy → portal:8080 (Hugo static + portal); `/media/files/*` → skill-runner:8091 | none (public) | **read-only containers (verified `ReadonlyRootfs=true` on portal + portal-git-sync) → 11.4** |
| `www.choukalos.com` | redirect → choukalos.com | — | probe: redirect intact |
| `plausible.choukalos.com` | caddy → plausible:8000 | admin UI internet-blocked | probe: block still holds |

#### 11.0 — Public-surface registry (extensibility core)

- [ ] `security/public-surface.yml` — single source of truth; every 11.x check reads it. Seed (versions from §9.2, backends from the 2026-11-24 Caddyfile read):
  ```yaml
  tunnel: <CF tunnel name — confirm>
  domains:
    llm.choukalos.com:
      backend: caddy → litellm-proxy:4000
      stack: {litellm: 1.104.0, caddy: 2.11.7}      # versions feed 11.5 CVE cross-check
      auth: caddy-key-gate (chuck/dylan)
      probes:
        - {path: /v1/models, expect: 200, with: chuck-key}
        - {path: /v1/models, expect: 401, with: none}
        - {path: /v1/models, expect: 401, with: wrong-key}
        - {path: /ui/, expect: 404, with: chuck-key}        # no admin UI
    siri.choukalos.com:
      backend: caddy → skill-runner:8091 (+ 192.168.4.55:8189 for /dl,/upload)
      stack: {fastapi: 0.156.8}
      auth: X-Api-Key on /siri/*, /api/*, /upload
      probes:
        - {path: /health, expect: 200, with: none}
        - {path: /api/schedule, expect: 401, with: none}    # canary: gate must hold
        - {path: /api/schedule, expect: 200, with: chuck-key}
    api.choukalos.com:
      backend: caddy → invest-hub-server:4000
      stack: {express: 5.2.1, prisma: 7.8}
      auth: JWT on protected routes
      data: public user input + investorhub DB
      probes:                          # enumerate protected routes during build
        - {path: /api/famous-portfolios/1, expect: 200, with: none}
        - {path: /api/<protected>, expect: 401, with: none}
        - {path: /api/<protected>, expect: 401, with: expired-jwt}
      log_sources: [invest-hub-server]
      db: {name: investorhub, schema_diff: weekly}
    invest.choukalos.com:
      backend: caddy → invest-hub-client:80 + invest-hub-server:4000 (API paths)
      stack: {nginx: 1.31.7}
      probes: [{path: /, expect: 200, with: none}]
    choukalos.com:
      backend: caddy → portal:8080 (/media/files/* → skill-runner:8091)
      stack: {hugo: ">=0.168.0"}
      integrity: content-hash vs blog repo deploy commit (11.4)
      probes: [{path: /, expect: 200, with: none}]
    www.choukalos.com:
      backend: redirect → choukalos.com
      probes: [{path: /, expect: 301/302 → choukalos.com}]
    plausible.choukalos.com:
      backend: caddy → plausible:8000
      stack: {plausible: 3.2.0}
      probes:
        - {path: /js/script.js, expect: 200, with: none}
        - {path: /admin/<path>, expect: 404, with: none}      # canary: admin block must hold
  ```
  (`probes` = expected responses per auth state — the negative ones are leak detectors; `log_sources` = containers whose logs feed 11.3-style anomaly detection; `db` = schema-diff target.)
- [ ] **Registry lint** (daily): every Caddyfile `host` matcher + every CF tunnel ingress hostname must map to a registry entry, and vice versa — unknown on either side = alert (this is what makes the registry the single source of truth)

#### 11.1 — Cloudflare Tunnel layer

- [ ] **Tunnel ingress audit** (daily, CF API — same CF token `scripts/rotate-cf-tunnel.sh` uses): fetch tunnel ingress rules + public hostnames, diff vs registry → **unknown public hostname or new ingress path = P0** (closes the §9.4 caveat: extra CF hostnames bypassing Caddy)
- [ ] **cloudflared version check** (weekly): running version vs latest release + published CVEs → note/alert (feeds 11.5)
- [ ] **Tunnel health** (daily): reconnect count + origin errors from cloudflared logs; reconnect storm (>N/h, threshold from observation mode) = alert (flap = DoS or compromise)
- [ ] **CF account hygiene** (monthly): API-token inventory (scope + last-used), CF login alerts enabled, token rotation per `rotate-cf-tunnel.sh` cadence

#### 11.2 — External black-box probes (per registry entry)

- [ ] `scripts/security-probe.sh` (or .py): per registry domain — TLS (protocol floor ≥1.2, cert expiry ≥14d), security headers (HSTS, X-Content-Type-Options, no version disclosure in `Server`/error pages), all registry `probes` (expected 200/401/404 per auth state), admin-route absence (`/ui/`, `/admin`, `/api/keys` → 404/401)
- [ ] **Must run from outside the LAN** — D8 (vantage point). Results → daily report (per-domain section) + `alerts.log` on any deviation
- [ ] **Negative-path canary (P0 semantics):** a probe that should 401/404 returning 200 unauthenticated is an **auth regression / leak**, not a probe failure → immediate alert (D7 channel)

#### 11.3 — InvestHub deep-dive (public input + DB)

Highest-risk surface: public user input → Express → Prisma → MySQL. (Log shape verified 2026-11-24: morgan HTTP lines **without client IPs** → per-IP signals come from **Caddy access logs**; app-level signals from `invest-hub-server`.)

- [ ] **API anomaly detection** (daily, last 24h):
  - [ ] **Caddy access logs:** 401/403 rate per source IP (brute force / credential stuffing; threshold from observation mode)
  - [ ] **invest-hub-server logs:** SQL-error spikes (SQLi signature — distinct from the known LLM-SQL `1054` noise in mcp_mysql, different container + different signature), 5xx spikes per endpoint, JWT failures (invalid/expired bursts), payload-size outliers (abnormally large POST bodies)
  - [ ] note: HikariCP connection-leak warnings already appear in normal logs (2026-11-24) — baseline them as noise, don't alert on them
- [ ] **DB state diff** (weekly, `investorhub`): snapshot `information_schema` (tables, columns, users + privileges) → diff vs previous → **schema or privilege change = P0** (catches malicious DDL and accidental drift alike)
- [ ] **WAF / rate limiting (D9):** Cloudflare Managed Ruleset (OWASP Core) + per-domain rate limit on `api.choukalos.com` — decide on/off + thresholds; if on, CF WAF block logs become an extra 11.3 log source
- [ ] **Dependency scan** (weekly): `npm audit` + OSV on the invest-hub repo (currently ad-hoc per §9) → alert on new high/critical; results into the weekly digest

#### 11.4 — Blog + Plausible integrity (read-only verification)

Read-only is a mitigation, not a monitor — verify it stays true:

- [ ] **Deployed-content integrity** (daily): hash portal's served files (git-sync volume) vs `git ls-tree` of the deployed commit in the blog repo → mismatch = tampering (host or repo) — **P0**
- [ ] **Read-only posture check** (daily): `docker inspect` portal + portal-git-sync — `ReadonlyRootfs` unchanged (baseline 2026-11-24: both `true`) + mount modes; a writable path appearing = anomaly
- [ ] **Hugo pin check** (weekly): blog repo pin (≥0.168.0, 9.3-H1) + build-machine `hugo version` — drift = note
- [ ] **Plausible admin block** (daily probe, in 11.2 registry): admin path from outside → 404; a 200 = **P0**

#### 11.5 — CVE cross-check cadence (make §9 standing)

- [ ] **Monthly**: re-run the §9 process against every `stack` version in the registry (NVD/GHSA/OSV/vendor advisories since last run) → new items become 9.3-style tracked rows in §9.3
- [ ] **Event-driven**: OSV/npm-audit alerts (11.3) or a major vendor CPU (e.g. Oracle/Microsoft patch day) triggers an off-cycle pass
- [ ] §9.3 table stays the durable record; the monthly pass is the standing trigger

#### 11.6 — Reporting & the "add a new site" runbook

- [ ] All 11.x findings flow into **Phase 10's pipeline**: same daily report (a "Public surface" section per domain), same `alerts.log`, same weekly digest, same Grafana textfile metrics (`security_probe_failures_total{domain=...}`, `security_tunnel_audit_anomalies_total`)
- [ ] **P0 definitions** (immediate alert via D7 channel + incident note in this file): unauth 200 on an auth-required route, content-tamper mismatch, unknown public hostname/ingress, schema or privilege change on `investorhub`, admin UI reachable on plausible
- [ ] **Add-a-site runbook** (the extensibility contract — future public sites follow these 6 steps):
  1. Registry entry: domain, backend, stack versions, auth model, `probes` (incl. at least one negative canary), `log_sources`, `db` if applicable
  2. Caddy route + CF tunnel ingress via the existing deploy path
  3. Baseline capture (Phase 10 `--update` + registry lint green)
  4. External probe live from the D8 vantage point
  5. Negative-path canary defined (which route must 401/404)
  6. Verify: §7 checklist + first daily report shows the domain CLEAN

Rollback: registry + scripts are additive (new files); disable the probe/audit timers; CF WAF ruleset removal via CF API/dashboard. No service changes.

**Out of scope:** host-layer checks (Phase 10), LiteLLM 401/spend (Phase 6), the work laptop.

---

### Phase 12 — File bridge: unified file edge (public relay + work areas + publish targets) — **ADDED 2026-11-24 (not started; D10–D16 decided 2026-11-24)**

> Trigger: follow-up to the 2026-11-24 public-surface review (Phase 11).
> `siri.choukalos.com/media/pipeline/*` currently proxies **directly to Matrix
> (192.168.4.55:8189)** — the GPU host is an internet-facing origin. Initial
> proposal: relay via skill-runner. After scoping the full file-transfer
> surface (below), the recommendation changed to a **dedicated service** —
> the file edge is bigger than a 2-endpoint relay.

**Why not skill-runner (Q1 resolution, 2026-11-24):**
- skill-runner holds the most secrets in the stack (memory admin keys, `SIRI_KEY_SERVICE`, session data) + a rw mount to `proposals/`. A data-plane role (multipart parsing, path handling, large-file streaming) is exactly the code that gets parsing bugs — that attack surface doesn't belong in that container.
- Lifecycle coupling: 500 MB uploads / long downloads vs in-flight skill runs + sessions — a restart of either role shouldn't kill the other.
- Identity: this is the homelab's **file edge** (public HTTP + MCP tools + work-area/publish-target registry), not a relay — it gets its own service, its own MCP server, its own Phase 11 registry entry.
- Cost acknowledged: one more container (small: FastAPI + httpx + config).

**Current file-transfer surface (verified 2026-11-24):**

*Work areas (intra-homelab):*

| Work area | Location | Notes |
|---|---|---|
| Matrix pipeline | `http://192.168.4.55:8189` (API) | `media_jobs`, 14-day retention; the GPU-host path |
| Media staging | `/home/chuck/workspace/media` | `MEDIA_STAGING_DIR` (mcp_media `media_put`) |
| Pipeline fetch | `/home/chuck/data/media/generated/pipeline` | `MEDIA_PIPELINE_FETCH_DIR`; approved publish root |
| Siri outputs | `/home/chuck/data/media/siri_outputs` | ⚠️ **publicly served today via `/media/files/siri_outputs/*` with human-readable names** (e.g. `siri_output_..._what-coffee-do-I-like.txt`) — violates the Tier-2 "opaque IDs" assumption → 12.4 |
| NAS media store | `lego.local` `workspace` → `/mnt/lego-media-store` | cifs automount (soft); mcp_kanban binds `/media-store` |
| Per-category media | `/home/chuck/data/media/{demos,images,clips,...}` | artifact tree under `ARTIFACT_ROOT` |

*Publish targets:*

| Target | Mechanism today | Notes |
|---|---|---|
| Blog drop | `publish-file` skill → `/home/chuck/data/media/public/{ai,images,audio,video,tabs}` → `choukalos.com/files/{subdir}/{name}` | validated, atomic, size-capped, idempotent; source roots restricted to `data/media` + `workspace` |
| (future) bluebovinegroup | — | per-target adapter + registry entry |

*Clients (recipients):* Siri (iOS) via `siri.choukalos.com` (`/media/files/*` public, `/media/pipeline/dl/<token>` signed); laptop via LiteLLM (`media_pull` signed URLs); LAN direct (`thor.local:8091/media/files`).

**Design: `mcp_filebridge` (name decided 2026-11-24, D16) — one Thor container, two faces:**

> **Name (decided 2026-11-24, D16):** `mcp_filebridge` — the bridge files
> cross between public and internal systems/directories. No collision with
> `mcp_filesystem` / `mcp_filesystem_readonly` (those are in-place file ops;
> filebridge is boundary-crossing). Container `mcp_filebridge`, image
> `ai-mcp-mcp_filebridge`, tools `mcp_filebridge-file_pull` etc.
> Alternatives considered: `mcp_filegate`, `mcp_fileport`, `mcp_fileedge`.

*Face 1 — public HTTP (Caddy, `siri.choukalos.com`):*
- [x] `GET /media/pipeline/dl/<token>` → stream from Matrix (Range passthrough, never buffer); token validation stays on Matrix (transparent relay — no secret sprawl) — **done 2026-11-26 (task 16)**: `mcp_filebridge` `/dl/{token}` (httpx stream + aiter_bytes, never buffers; Range + status + content headers passed through). Evidence: unit tests (stub upstream) + live smoke vs real Matrix — fresh token fetch byte-identical (sha256 match), `Range: bytes=0-99` → 206 `Content-Range: bytes 0-99/540`, bad token 404.
- [x] `POST /media/pipeline/upload` → Caddy key gate unchanged; stream multipart to Matrix; enforce the 500 MB cap at the relay too — **done 2026-11-26 (task 16)**: streaming multipart relay (Content-Type incl. boundary forwarded; X-Api-Key stripped on the upstream leg); `UPLOAD_MAX_MB=500` enforced at the relay (Content-Length fast path 413 before reading; chunked counted while streaming). Evidence: unit tests (cap with small cap, Matrix-never-sees-body) + live smoke — small upload 200 → `media_jobs/uploads` (re-minted token fetch 200), 2 MiB vs 1 MiB cap → 413 (log: `bytes_out: 0`).
- [x] `GET /media/files/{filepath:path}` → **migrate from skill-runner now** (D11: security + consolidated logic — single public file edge, one log source); served from the work-area registry with a per-subdir policy (12.4 — `siri_outputs` excluded from public serving) — **done 2026-11-26 (task 16)**: FileResponse (native Range) from `MEDIA_ROOT`, allowlist `[generated, images, demos, presentations]` (default-deny; `filebridge.yaml`), traversal containment check; non-allowlisted/traversal/missing/directory → 404 (not 403). Cutover covers BOTH hosts (`siri.choukalos.com` @siri_media + `choukalos.com` @blog). Evidence: 12 policy unit tests + live smoke (allowlisted 200 + Range 206; siri_outputs 404; `../etc/passwd` + nested traversal 404; directory 404).
- [x] **No public upload endpoint** (D10 decided 2026-11-24): remote→work-area moves happen via MCP through an agent for now (`file_pull` from a URL / signed token) — no new public write surface

*Face 2 — MCP tools (via litellm → laptop + siri):* — **IMPLEMENTED 2026-11-26 (pi-long-task run 10f37f65) — PENDING DEPLOY** (litellm recreate + `family-mcp-full` access-group update per the deploy runbook `docs/filebridge_p12bc_deploy.md`; evidence: `docs/filebridge_p12bc.md` §2–§4 + unit tests green):
- [x] `file_pull(source, work_area)` — source = URL | signed pipeline token | pipeline path | work area; dest = any registered work area (consolidates the cross-area cases of `media_download`/`media_put`/`media_fetch`) — `mcp_face.py` + `fileops.py` (decision 2a: URL source = parity with `media_download`; the one-line JSON audit log is the trail)
- [x] `file_push(file, destination)` — dest = work area | client (mints a signed public URL) | publish target. **Shared persistent output (D13):** `siri_outputs` is siri-only (`remote_write: false`); other clients' persistent output goes to the **NAS media store** — the shared output area for now, extensible later — client dest mints the 1b path-bound, TTL'd token served at `GET /media/files/dl/{token}` (`tokens.py`)
- [x] `file_publish(file, target, ...)` — target = registered publish target; **extract the publish-file engine** (validated/atomic/size-capped/idempotent) as the engine; the `publish-file` skill becomes a thin wrapper — `publish_engine.py` (blog + nas targets; `PublishTarget` adapter protocol — bluebovine interface-only per D14); `skills/publish_file/skill.py` is now the thin wrapper (no fallback)
- [x] `file_work_areas()` / `file_targets()` — enumerate the registry (transparency)

**Registry (default-deny, consistent with the Phase 2 philosophy):**

```yaml
work_areas:
  media_staging:  {path: /home/chuck/workspace/media}
  pipeline_fetch: {path: /home/chuck/data/media/generated/pipeline}
  siri_outputs:   {path: /home/chuck/data/media/siri_outputs, remote_write: false}      # siri-only (D13)
  nas_media_store: {path: /mnt/lego-media-store, automount: true, shared_output: true}  # shared persistent output for other clients (D13)
  matrix_pipeline: {api: http://192.168.4.55:8189}                                      # first-class (D12)
  # more Thor areas as needed (D12: registry designed for growth)
publish_targets:
  blog:        # homelab files area (existing engine — P12-C)
    root: /home/chuck/data/media/public
    subdirs: [ai, images, audio, video, tabs]
    url_base: https://choukalos.com/files
    source_roots: [/home/chuck/data/media, /home/chuck/workspace]
    size_cap_mb: <confirm from publish-file impl>
  nas:         # publish to the NAS media store (D14)
    root: /mnt/lego-media-store/<subdir — decide>
  # bluebovine: (future — adapter interface defined in P12-C, no impl now (D14))
```

Adding a target/work area = one entry (+ adapter if needed) — the same
extensibility contract as Phase 11.

**Security properties:**
- Matrix 8189 stops being an internet origin → LAN-only after cutover (bind/ufw on Matrix — **✅ DONE 2026-11-26, validated**: LAN 200, external vantage timeout, public chain via bridge 200)
- One audited public file edge: every cross-boundary file move goes through one service with one log format → Phase 11 monitoring (canaries, log anomalies, size/rate limits)
- Minimal-env container: only work-area paths + pipeline URL — no LiteLLM master key, no memory keys
- Kill switch: stop the service = public file routes dead, Matrix untouched
- Rollback: Caddy one-line revert per route (back to `4.55:8189` / `skill-runner:8091`)

**12.4 — `siri_outputs` public exposure (finding, 2026-11-24):**
- [x] **Interim applied 2026-11-26 (pi, thor):** Caddy 404s `/media/files/siri_outputs/*` on both public hosts (choukalos.com `@blog` + siri.choukalos.com `@siri_media`) — graceful reload, no restarts. Verified: public siri_outputs → 404 on both hosts (cf-cache-status DYNAMIC — not edge-cached), allowlisted subdirs → 200, LAN skill-runner face (`192.168.4.54:8091`) unchanged (siri keeps its own access path). Rollback = delete the two Caddy blocks + `caddy reload`. (Kept as defense-in-depth in front of the bridge's allowlist — see Caddyfile.)
- [x] **Fix lands in P12-A**: the bridge serves `/media/files` with a per-subdir policy — allowlisted subdirs only, `siri_outputs` excluded (D13: siri-only; siri keeps its own access path — skill API artifact endpoint + LAN). **RESOLVED 2026-11-26 (P12-A, task 16)**: cutover committed (Caddyfile) + live-applied on thor the same day.

**Phasing (D15 decided 2026-11-24 — agreed):**
- [x] **P12-A: public face** — the two pipeline relays + `/media/files/*` migration off skill-runner (one cutover, one rollback) — the security fix — **DONE + LIVE 2026-11-26 (task 16)**: `mcp/servers/filebridge/` (22 unit tests green), `compose/compose.mcp.yml` service (no host port, minimal env), Caddy cutover commit (4 one-line upstream swaps, `caddy validate` green). **Live apply on thor 2026-11-26 17:15–17:25 UTC — all runbook steps green**: build + start (env gate 0, healthy, ai-net smoke), cutover (note: the bind-mounted Caddyfile was pinned to a pre-merge inode after the git merge's rename-replacement — `caddy reload` loaded the stale file; fixed with `docker restart caddy`, which re-binds the mount), public battery (dl sha256 identical to direct Matrix + Range 206 + bad-token 404 + cf-cache-status DYNAMIC; upload 401/401/200 + round-trip; 501 MB → 413 at the Cloudflare edge (100 MB free-plan cap) with the bridge's 500 MB cap proven via ai-net (413, `bytes_out: 0` — Matrix never saw the body); `/media/files` policy on both hosts — allowlisted 200, siri_outputs/non-allowlisted/traversal/directory 404; `/media/pipeline/jobs` + `/dl_token` 404), kill switch (4 routes 502 while Matrix + skill-runner stay 200; clean recovery), regression (siri/api 200 with chuck key, LAN skill-runner face untouched, blog portal intact), port diff (no new host ports). **Effective public upload cap: 100 MB (Cloudflare edge) — the bridge's 500 MB cap is the backstop.** **Post-cutover follow-up: Matrix 8189 → LAN-only — ✅ DONE 2026-11-26 (validated from thor: LAN `192.168.4.55:8189/health` 200; external vantage points (check-host.net, US + IL) TCP `104.5.56.59:8189` → connection timeout; public download via the bridge 200 + sha256 identical; bridge `pipeline_reachable: true`).**
- [x] **P12-B:** MCP tools (Face 2) + registry — **IMPLEMENTED 2026-11-26 (pi-long-task run 10f37f65) — PENDING DEPLOY** (was: unblocked by P12-A; grows `filebridge.yaml` into the full work-area/publish-target registry): `mcp_face.py` (streamable HTTP at `/mcp`; `file_pull`/`file_push`/`file_publish`/`file_work_areas`/`file_targets`; decision 3a — no face auth: litellm key gate + registry policies), `registry.py` (full default-deny registry — `work_areas` + `publish_targets`; boot lint fail-fast + standalone `python app.py lint` — **green 2026-11-26: OK, 5 work areas, 2 publish targets, exit 0**), `tokens.py` (1b bridge-minted path-bound TTL'd tokens at `GET /media/files/dl/{token}`), `fileops.py` (one-line JSON audit). Evidence: `docs/filebridge_p12bc.md` §2–§4; unit tests (`tests/test_registry.py` / `test_tokens.py` / `test_file_pull.py` / `test_file_push.py`) green. Deploy wiring (config only, 2026-11-26): compose work-area mounts + `litellm/config.yml` `mcp_servers` entry — applied at the deploy runbook's recreate + litellm restart + `family-mcp-full` access-group update (`docs/filebridge_p12bc_deploy.md`).
- [x] **P12-C:** publish engine migration (`publish-file` → `file_publish`) — blog + NAS targets; bluebovine adapter interface (no impl) — **IMPLEMENTED 2026-11-26 (same run) — PENDING DEPLOY** (was: unblocked by P12-B): `publish_engine.py` (extracted from `skills/publish_file/skill.py`, parameterized by the registry `publish_targets`; blog behavior preserved — same validation order / report shape / dedup; `PublishTarget` adapter protocol: blog + nas implement, bluebovine interface-only per D14), `file_publish` tool + `POST /publish` (ai-net only), `skills/publish_file/skill.py` is now a thin wrapper (no fallback). Evidence: `docs/filebridge_p12bc.md` §5; `tests/test_publish.py` + `skills/publish_file/test_skill.py` (wrapper contract) green. Deploy wiring (config only, 2026-11-26): compose publish mounts (blog root rw + workspace source_roots ro).

**Out of scope:** intra-work-area file ops (`mcp_filesystem` / `mcp_filesystem_readonly` — in-place ops, not boundary-crossing), pipeline-native job flows (mcp_media keeps its tools; cross-area cases route via the bridge).

---

### Phase 13 — LiteLLM key lifecycle + `.env` consolidation (agent-key driver) — **ADDED 2026-11-26 (DONE 2026-11-26 — all 5 work items complete: 13.1 one-.env, 13.2 key rotate, 13.3 alias-based capability map, 13.4 key inventory, 13.5 agent key conventions + `key add-agent`; framework step-6 prerequisite met)**

> Trigger: the agentic framework plan (`todo_agentic_framework.md`) stands up
> 4 standing agents, each with its own LiteLLM key (per-agent spend
> attribution) + a `MEMORY_USER_KEYS` entry + a kanban capability entry + a
> per-key model default. Rotation/drop today is a 5-step manual loop (create
> → edit two `.env` files → hand-edit the suffix map → restart consumers →
> block/observe/delete) — run ~4× at agent standup, then periodically.
> **Scope note:** this is the decided, agent-driven slice of the Phase 9
> stub's grooming agenda (LiteLLM-class rotation + the `.env` dedupe). The
> broader program (per-service env delivery, SOPS/at-rest decision,
> all-secrets inventory, breach runbook) stays in Phase 9.

**Assessment (2026-11-26):** the architecture is sound — the LiteLLM proxy
DB is already the source of truth for LLM keys (`./homelab.sh key
add/list/block/delete` exists), `.env` is bootstrap + name-references
(`MEMORY_USER_KEYS=chuck=$LITELLM_KEY_CHUCK,...`), per-key MCP scoping is in
place (Phase 2). What's missing is the *operations* layer. **No new secrets
manager** (Vault/Infisical/Doppler rejected — a crown-jewel daemon holding
every secret contradicts this plan's surface-shrink direction and is overkill
for a single-operator homelab; realistic risks are drift, stale keys,
accidental exposure — all addressed below). SOPS+age for encrypted
versioning stays a Phase 9 question (agenda item 3), deferred.

**Findings (verified 2026-11-26):**
- Two near-identical `.env` files (root + `compose/`, both gitignored, ~95
  vars each) → drift hazard. 12 compose files consume via `env_file:`.
- `KANBAN_MCP_KEY_CAPABILITIES` is keyed by **raw key suffixes**
  (`faxfoUszvw:admin;…`) — rotating a key silently breaks the map.
- The §1 key inventory table is hand-maintained; `key list` exists but isn't
  wired to it.

**Work items:**

- [x] **13.1 — One `.env`**: kill the `compose/.env` duplicate (symlink, or
      repoint the 12 `env_file:` refs at the root `.env`); verify per stack
      after (`docker compose config` per file + recreate smoke).
      **Done 2026-11-26 (pi):** already consolidated since 2026-11-21 —
      `compose/.env` is a symlink to `../.env` and all 12 `env_file:` refs
      across the 10 compose files point at `../.env` (verified live);
      `docker compose config` passes for all 10 stacks (n8n warning is
      pre-existing: N8N_DB_* unset, unrelated).
- [x] **13.2 — `key rotate <name>`** in `lib/litellm-keys.sh`: one command —
      mint in proxy → atomically update `.env` (Phase 0 backup first) →
      regenerate derived maps (13.3) → restart affected containers →
      **block old key** → print "observe N days, then `key delete <name>`"
      (the block → observe → delete pattern from the F5/Phase 3 work).
      Includes the Caddy reload step when rotating `LITELLM_KEY_CHUCK`/
      `LITELLM_KEY_DYLAN` (Phase 1 note) and a `scripts/key-sync-check.sh`
      run at the end. Subsumes the Phase 6 quarterly-rotation cadence for
      the family keys.
      **Done 2026-11-26 (pi):** `./homelab.sh key rotate <key> [--env-var VAR]
      [--observe-days N] [--yes]` — 8 steps: (1) .env backup (Phase 0
      pattern), (2) rename old key's alias to `<alias>-old-<YYYYMMDD-HHMM>`
      (LiteLLM enforces unique key aliases across ALL keys incl. blocked —
      `_enforce_unique_key_alias`, v1.104.0 — so the canonical alias must be
      freed first; the old key stays identifiable during the observation
      window), (3) mint new key with identical attrs + `access_group_ids`
      + canonical alias, probe `/v1/models` (200 or abort + block dangling
      key), (4) atomic .env update (same-dir temp + rename, 600), (5)
      regenerate `KANBAN_MCP_KEY_CAPABILITIES` suffix entry while it is
      suffix-keyed (no-op post-13.3), (6) recreate the compose services
      that reference the var + **recreate caddy** for the family keys
      (finding: a plain `caddy reload` re-parses with the container's
      baked env and would keep the OLD keys — the Phase 1 note's "reload"
      is insufficient after a key change), (7) block old key, (8)
      `scripts/key-sync-check.sh` with rotate-github-tokens.sh gate
      semantics: drift on the rotated var = FAIL, drift on other vars =
      informational carrier drift. `key update --alias` added (rename
      support). Verified with a full drill on a disposable key: rotate ×2,
      new key 200 / blocked old key 401, .env + alias state verified, test
      artifacts cleaned (3 keys deleted, env line removed). Pre-existing
      drift found by the gate: GITHUB_ACCESS_TOKEN/GITHUB_RUNNER_TOKEN on
      7 carrier containers (expected per rotate-github-tokens.sh — refresh
      on next recreate; GITHUB_RUNNER_TOKEN is unconsumed legacy).
- [x] **13.3 — Alias-based capability map**: `KANBAN_MCP_KEY_CAPABILITIES`
      keyed by alias (`product:control`) instead of raw suffixes; kanban
      server resolves alias → key (kanban harness change, small — separate
      repo: `data/ai-kanban`).
      **Done 2026-11-26 (pi):** `KANBAN_MCP_KEY_CAPABILITIES="chuck:admin;
      dylan:control"` — alias entries resolve to the full key via `USER_KEYS`
      (exact match) at call time; legacy suffix entries still work
      (backward compatible, no suffix fallback for known aliases). Kanban
      harness: `resolveMcpCapabilities` + `userKeys` param (commit
      `edf0285` on main, both clones synced via GitHub; the two clones —
      `/home/chuck/homelab` and `/home/chuck/data/ai-kanban/harness` — are
      separate checkouts of the same repo, and the Docker build context is
      the homelab clone's `mcp/servers/kanban`). 231/231 kanban tests pass
      (4 new: alias resolution, rotation survival, no-suffix-fallback,
      mixed map). mcp_kanban rebuilt + recreated; E2E verified: chuck
      `board_status` 200 + `delete_project` reaches handler (admin), dylan
      `board_status` 200 + `delete_project` → "not available for this key"
      (control), unknown key → 401, kanban key → full set, and through the
      LiteLLM proxy (chuck → `mcp_kanban_board_status` tool call). Rotation
      is now a no-op for the map: `key rotate` only updates `USER_KEYS`
      (via .env + container recreate).
- [x] **13.4 — `key inventory`**: generate the §1 key table from the proxy
      (`/key/info` + access groups + spend) so the table is never
      hand-maintained; reuse the output in the Phase 6
      `scripts/audit-litellm-keys.sh`.
      **Done 2026-11-26 (pi):** `./homelab.sh key inventory [--json]` in
      `lib/litellm-keys.sh` — builds the §1-format table from `/key/list` +
      `/key/info` (incl. `access_group_ids`) + `/v1/access_group/{id}` (group
      name + MCP server count); appends the master-key row; `--json` for the
      audit script. Verified live (4 rows: chuck, dylan, memory-service,
      master). Note: no list-all-groups endpoint exists in v1.104.0
      (`GET /mcp/access/groups` returns 200 empty) — groups resolved per-ID
      from each key's `access_group_ids`.
- [x] **13.5 — Agent key conventions** (feeds the framework plan's step 6):
      aliases = slugs (`product`, `analyst`, `strategist`, `marketing`);
      mint via `key add` with per-key model default by work type
      (`matrix-coder` / `matrix-copywriter`); `MEMORY_USER_KEYS` + kanban
      capability map updated in the same command (13.2/13.3 make this
      mechanical); the first rotation drill = agent standup itself
      (mint → verify → record in §1).
      **Done 2026-11-26 (pi):** `./homelab.sh key add-agent <slug>
      [--work-type coding|writing] [--capability read|control|admin]`
      (default: coding → `matrix-coder`, capability `control`) — one command
      mints the key, probes it, then wires the three `.env` surfaces in one
      atomic pass (`LITELLM_KEY_<SLUG>`, `MEMORY_USER_KEYS` entry,
      `KANBAN_MCP_KEY_CAPABILITIES` alias entry), recreates the consumers
      (skill-runner + mcp_kanban), and gates on `scripts/key-sync-check.sh`
      (fail on drift of the new var; other drift = informational). Conventions
      live in the framework step-6 checklist. **Enabler (kanban harness,
      `ff9fd48` + `f172c93` on main):** `USER_KEYS` now accepts env-var-NAME
      refs resolved at boot, so `compose.mcp.yml` sets
      `USER_KEYS=${MEMORY_USER_KEYS}` — single source of truth, no per-agent
      compose edit; a resolved ref that isn't a LiteLLM key (e.g.
      `service=SIRI_KEY_SERVICE`, the siri service token) is skipped with a
      startup warning instead of crashing `validateUserKeysAtBoot`. 233/233
      kanban tests. E2E: stood up a throwaway `testagent` (writing) —
      `board_status` 200 + `delete_project` → "not available for this key"
      (control) with zero compose edits; then fully torn down (key deleted,
      `.env` restored, containers recreated, chuck/dylan re-verified).

Rollback: 13.1 restore `compose/.env` from git/backup + recreate; 13.2/13.4
are additive script functions (delete = rollback); 13.3 revert the kanban
capability map to suffix form (git) + recreate; 13.5 `key delete <slug>` +
remove the `.env` lines (`LITELLM_KEY_<SLUG>`, `MEMORY_USER_KEYS`,
`KANBAN_MCP_KEY_CAPABILITIES`) + recreate skill-runner + mcp_kanban.

**Out of scope (Phase 9):** per-service env delivery (the carrier problem),
SOPS/encrypted at-rest, all-secrets inventory + breach runbook, non-LiteLLM
rotation runbooks (MySQL, Qdrant, app keys).

---

## 6. Decisions & open questions

### Resolved (2026-09-06)

| # | Decision | Resolution |
|---|---|---|
| D1 | Dylan's MCP scope | **Full** — family trust = Chuck's level (all 10 MCP servers) |
| D2 | Budget for chuck/dylan | **Unlimited** — family power users, no `max_budget` |
| D3 | The 3 `default_user_id` keys | Investigated: **orphaned dashboard test keys** (F5) → confirm with Dylan → block → observe → delete |
| D5 | Dead `.env` keys | `LITELLM_PUBLIC_API_KEY` = dead → remove. `SIRI_API_KEY` + `HARNESS_API_KEY` = **in use** (CLI, open-webui) → keep. **2026-11-15:** `LITELLM_PUBLIC_API_KEY` removed (Phase 3); `HARNESS_API_KEY` removed same day (open-webui gone); `SIRI_API_KEY` stays |
| D6 | `internal-service` key | **Yes** — formalized as Phase 8 |
| D2b | Rate guardrails for chuck/dylan | **None** — family decision 2026-11-15 (Chuck: no rate limits on the public keys). Consistent with D2 (unlimited budget): the keys are family-only (Caddy gate, Phase 1), spend tracking is live (Phase 3) so abuse is visible, and power-user agent sessions (pi, parallel tool calls) can hit ~60 RPM — any cap would just cause false positives. |
| D10 | File-bridge public upload scope (Phase 12) | **No public upload endpoint** (2026-11-24) — remote→work-area moves happen via MCP through an agent for now |
| D11 | `/media/files` migration (Phase 12) | **Move to the bridge now** (2026-11-24) — security + consolidated logic; part of P12-A |
| D12 | Work-area registry contents (Phase 12) | **NAS + Matrix + Thor areas first-class from day one** (2026-11-24); registry designed for growth — more areas expected |
| D13 | `siri_outputs` policy + shared output (Phase 12) | `siri_outputs` = **siri-only** (`remote_write: false`) (2026-11-24); other clients' persistent output → **NAS media store** as the shared output area for now (extensible later) |
| D14 | Publish targets (Phase 12) | **Blog (homelab files area) + NAS now; bluebovine later** (2026-11-24) — not set up yet, no impl now, but the adapter interface must make adding targets trivial |
| D15 | File-bridge phasing (Phase 12) | **Agreed** (2026-11-24): P12-A public face (relays + `/media/files` migration) → P12-B MCP tools + registry → P12-C publish engine |
| D16 | File-bridge naming (Phase 12) | **`mcp_filebridge`** (chuck, 2026-11-24) — "the bridge files cross between public and internal"; no collision with `mcp_filesystem`/`_readonly`. Alternatives considered: `mcp_filegate`, `mcp_fileport`, `mcp_fileedge` |
| D17 | Key-management architecture (Phase 13) | **No new secrets manager** (chuck, 2026-11-26 — Vault/Infisical rejected: crown-jewel daemon, overkill for single-operator). Keep proxy-as-source-of-truth + `.env` bootstrap; fix the operations layer: one `.env`, `key rotate` (block → observe → delete), alias-based kanban capability map, generated key inventory. SOPS/at-rest stays a Phase 9 question |

### Open

| # | Question | Notes |
|---|---|---|
| D4 | ufw rules for the two home subnets (`192.168.4.0/24` + `192.168.5.0/24`) | See Phase 5 discussion list — settle before executing |
| D7 | Alert delivery channel for Phase 10 anomalies | File + Grafana metric now, Siri/Shortcuts push later? See Phase 10 options (a/b/c) |
| D8 | Vantage point for external black-box probes (Phase 11.2) | Must be **off-LAN** — self-hosted runners run on Thor, so a GitHub Actions workflow would need `ubuntu-latest` (not the self-hosted runner); options: (a) GitHub-hosted cron workflow (free, probe keys as GH secrets), (b) CF Workers cron trigger, (c) small VPS, (d) Mac Studio (unreliable — sleep/travel). Working recommendation: **(a)** |
| D9 | WAF / rate-limiting posture on `api.choukalos.com` (Phase 11.3) | CF Managed Ruleset (OWASP Core) + rate limit — on/off + thresholds; block logs become a log source if on |

---

## 7. End-to-end verification (after all phases)

- [ ] **Mac Studio (LAN, Chuck's key):** chat via `llm.choukalos.com` ✅; MCP tool call (e.g. media image gen) ✅; `siri.choukalos.com` ask + skill launch ✅
- [ ] **Mac Studio (cellular, Chuck's key):** same three ✅ (the trip test)
- [ ] **Dylan's device (his key):** chat + one MCP tool ✅
- [ ] **Negative tests (outside LAN):** wrong key → 401; no key → 401; `GET /` on llm domain with a valid key → 404 from LiteLLM (no admin route); `llm.choukalos.com/ui/` with valid key → no admin UI
- [ ] **memory-service key (LAN):** 0 MCP servers, models only
- [ ] **internal-service key (LAN):** models work, 0 MCP servers; master key no longer present in the 6 internal container envs (Phase 8)
- [ ] `ss -tlnp` matches Phase 4 expected survivors; `ufw status` active
- [ ] Grafana: 401 + spend panels live
- [ ] Security scan (Phase 10): daily timer active, first daily report generated; test anomaly (temporary listener) detected in the next run and cleared
- [ ] Public surface (Phase 11): registry lint clean (7 Caddy hostnames = CF tunnel hostnames = registry), external probes live from the D8 vantage point, InvestHub DB schema-diff baseline captured, blog content-hash check green, plausible admin-block probe green
- [x] File bridge (Phase 12): P12-A public face **LIVE 2026-11-26 (task 16)** — code + cutover + live apply + public battery + kill switch + regression + port diff all green (task-report.md "Deployed" section); Matrix 8189 → LAN-only **validated 2026-11-26** (LAN 200; external vantage timeout; public chain 200); `/media/files` served by the bridge with `siri_outputs` excluded (12.4 ✅ resolved at the edge); bridge registry lint green (P12-B) **✅ RESOLVED 2026-11-26** (standalone `python app.py lint` exit 0 — OK, 5 work areas, 2 publish targets; boot lint fail-fast wired; `tests/test_registry.py` green; P12-B + P12-C implemented — pending deploy, runbook `docs/filebridge_p12bc_deploy.md`)
- [x] Docs updated (Phase 7) — 2026-11-21

## 8. Rollback (global)

1. `git checkout <pre-change commit>` for Caddyfile / litellm config / compose → `caddy reload` + `docker compose up -d` for affected stacks
2. `.env` from `/home/chuck/data/backups/env-<date>.bak`
3. LiteLLM DB rows (keys/groups) from the Phase 0 CSV snapshot
4. `sudo ufw disable`
5. `internal-service` key (Phase 8): revert consumer env vars to master key, recreate, `./homelab.sh key delete internal-service`
6. Re-run §7 verification

---

## 9. CVE cross-check — 2026-10-21 (web research + public-surface audit)

> Session 2026-10-21, triggered by the Oct 20–21 security-news flood.
> Scope: every **internet-facing** service (the 6 tunnel domains) + notable
> LAN services, cross-checked against CVEs published 2026-09-01 → 2026-10-21
> (NVD, GitHub/GHSA, OSV.dev, vendor advisories). **Incremental** to Phases
> 1–8 above — does not replace them.

### 9.1 What the "flood" was

| Source | What | Relevance to Thor |
|---|---|---|
| Oracle Oct 2026 CPU (pub 10-20) | ~1,000+ CVEs incl. MySQL Server | **Yes** — MySQL 8.4.11 affected (9.3-M1) |
| Microsoft Oct Patch Tuesday (10-13) | 1,413 CVEs; exploited Win Shell zero-day (CVE-2026-96951) | No (Linux) |
| CISA KEV additions (10-13 → 10-20) | Plex ×4, PAN-OS, BeyondTrust, Fortinet, Ivanti, Atlassian, Cisco SEG | **None run in the stack** |

### 9.2 Internet-facing services — CVE status

| Public service | Component / version | Recent CVEs? | Status |
|---|---|---|---|
| `llm.choukalos.com` | litellm **1.104.0** | CVE-2026-84377 (auth'd SSRF / provider-cred exfil), fixed 1.96.2 | ✅ Patched |
| (front) | Caddy **2.11.7** | CVE-2026-77281 / -92284 / -92700 (placeholder injection, body DoS, file-hide bypass) — all fixed 2.11.4 | ✅ Patched, latest |
| (tunnel) | cloudflared **2026.9.3** | none recent | ✅ OK — 2026.10.3 out (9.3-V1) |
| `invest`/`api.choukalos.com` | investhub API (Express 5.2.1, Prisma 7.8, mysql2) | npm deps clean (OSV); JWT on protected routes | ✅ OK |
| `invest.choukalos.com` | nginx **1.31.7** (client, was 1.27.5) | 5 advisories affect ≤1.31.6 (CVE-2026-42533 "major" map+regex; -97629 TLS tickets; -97205 AIO; -95101 HTTP/3; -15176 alias+rewrite) | ✅ **Resolved 2026-10-21** — bumped to `nginx:1.31-alpine` (1.31.7 ≥ "not vulnerable" floor for all 5); config still minimal (no map/regex, alias/rewrite, TLS, HTTP/3, AIO) — 9.3-N1 |
| `choukalos.com` (blog) | Hugo **0.165.0** static + portal (Py stdlib, read-only) | several medium (build-time/theme + 2 stored-XSS) | ⚠️ 3 releases behind (0.168.0) — 9.3-H1 |
| `siri.choukalos.com` | skill-runner (FastAPI 0.156.8) | none recent; uploads auth-gated (X-Api-Key) | ✅ OK |
| `plausible.choukalos.com` | Plausible CE **3.2.0** | none recent; admin UI blocked from internet (only `/js`, `/api/event`) | ✅ OK |

**No active-attack patterns** in Caddy / invest-hub / portal / skill-runner logs (48h) — traffic is Chuck's own (WARP egress 104.5.56.59) + local scrapers.

### 9.3 New items to track

| # | Sev | Item | Where | Fix / action |
|---|---|---|---|---|
| 9.3-M1 | MED | **MySQL 8.4.11** hit by Oracle Oct CPU: CVE-2026-101679 (7.5, unauth, network → DoS/crash) + replication/optimizer CVEs (affected 8.4.0–8.4.12). **LAN-only** (0.0.0.0:3306, not tunnel-routed) → risk = bad LAN device, not internet. Ubuntu apt has **no 8.4.13 yet** (candidate still 8.4.11). | host `mysql-server` 8.4.11 | Wait for Ubuntu to ship 8.4.13+ (then `apt upgrade`), or add Oracle MySQL apt repo. Low urgency (LAN-only). |
| 9.3-N1 | LOW | ✅ **RESOLVED 2026-10-21** — **nginx** (invest-hub client) bumped `1.27-alpine` → `1.31-alpine` in the invest-hub repo `client/Dockerfile`; CI rebuilt + redeployed (image 976a00c55f2c, 18:53Z); running `nginx/1.31.7` = at/above the "not vulnerable" floor (1.31.7+) for all 5 advisories. Note: mainline 1.31 chosen over stable 1.30 — fully patched either way. Config re-verified minimal (listen 80, try_files, proxy_pass only). | `choukalos/invest-hub` → `client/Dockerfile` | Done. (Future: consider pinning exact patch version, e.g. `nginx:1.31.7-alpine`, for reproducibility.) |
| 9.3-H1 | LOW | ✅ **RESOLVED 2026-11-15 (verified)** — **Hugo 0.165.0** → ≥0.168.0. Recent advisories are build-time/theme + 2 stored-XSS in generated HTML; blog content is own git-synced repo → low runtime risk. Blog repo `main` pins **Hugo ≥ v0.168.0 (extended)** in README (commit `6797742a`, 2026-10-21 — fixes GHSA-r73q-gwx2-fpxm theme `module.replacements` mount-sandbox bypass; includes update procedure). Latest deploy `b9c02d9` (2026-11-03) built from main@c2e01e9 — after the pin. Build machine = laptop (`~/bin/hugo` per IMPLEMENTATION_NOTES) → check `hugo version` ≥ 0.168.0 there at the next build. | blog build (Hugo) | Done (pin + post-pin rebuild). |
| 9.3-O1 | MED | ✅ **RESOLVED 2026-11-15 by removal** — **Open WebUI** (was 0.11.4, behind a 2026-10-18 advisory, running with placeholder `WEBUI_SECRET_KEY`) was **unused by the family** (owner decision) — container, compose service, and data dir removed (data tarball `/home/chuck/data/backups/open-webui-data-20261115.tar.gz`); `WEBUI_SECRET_KEY` + `HARNESS_API_KEY` removed from `.env`. The advisory question is moot. | `compose/compose.ai-core.yml`, `.env` | Done (removed, not bumped). |
| 9.3-V1 | INFO | ✅ **RESOLVED 2026-11-15** — **cloudflared 2026.9.3** → 2026.10.3+ (no CVE, just lag): running **2026.10.7** (built 2026-10-30, `cloudflared:latest` image pull). **Qdrant 1.18.1** → 1.19.2 (LAN-only, no critical CVE). | `compose/*.yml` | **Both DONE 2026-11-15** (cloudflared 2026.10.7 live-verified; Qdrant v1.19.2 live, verified — pre-bump backup, collections/points/bm25 intact, memory path green, key-sync clean). |

### 9.4 Overlap with existing plan
- Secret sprawl = **F6/F7** above (master key + 0.0.0.0 bindings). No new finding.
- Caddy key-gate gap = **F1** — **CLOSED 2026-11-15** (Phase 1: Caddy key gate live on `llm.choukalos.com`, verified via the public path).
- **Caveat:** only the 6 known tunnel domains were verified. If the Cloudflare Tunnel has extra public hostnames in the CF dashboard (pointing straight at other services, bypassing Caddy), review those separately.
