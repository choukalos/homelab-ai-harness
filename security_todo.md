# Security Plan — LiteLLM Public Access + Homelab Hardening

> Created: 2026-09-06 (audit session 22:09–22:33; plan completed same evening)
> Status: **Phases 0–4 DONE (2026-11-15)** — Caddy key gate live on
> `llm.choukalos.com`, per-key MCP scoping (default-deny + `family-mcp-full`
> group), key hygiene (spend tracking on, orphan key deleted, dead keys
> removed), LAN exposure shrunk (all rebinds/mapping removals applied +
> verified; `ss -tlnp` matches expected survivors; device-side confirmations
> done from Mac Studio 2026-11-15). Phases 5–8
> not started (Phase 5 blocked on D4). Open WebUI removed 2026-11-15
> (9.3-O1 resolved by removal).
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
| `chuck` | chuck | all models | none (family decision: no cap) | none (D2b: no rate limits, decided 2026-11-15) | public (llm + siri routes); MCP: all 12 via `family-mcp-full` group |
| `dylan` | dylan | all models | none | none | public (llm + siri routes); MCP: all 12 via `family-mcp-full` group |
| *(no alias)* | — | models: matrix-coder, homelab-embedding-v1 | none | none | internal (skill-runner mem0, `MEMORY_LITELLM_KEY`); MCP: **none** (default-deny, Phase 2) |
| *(no alias, `sk-...sOsg`)* | default_user_id | all models | $1 | none | **DELETED 2026-11-15** — F5 orphan; blocked same day, then deleted (observation window waived — already expired 2026-10-05, zero spend). (The other 2 F5 orphans, created 07-15 / 08-15, were already deleted before 2026-11-15.) |
| master (`sk-cb1678…`) | — | admin, everything | — | — | internal only (F6); MCP: all 12 via `admin_view_unscoped` (verified in v1.104.0 source) |

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
- [ ] **Quarterly key rotation** cadence for `LITELLM_KEY_CHUCK` / `LITELLM_KEY_DYLAN` (rotate → update `.env` → Caddy reload → old key deleted in LiteLLM).
- [ ] Log-review habit: after any trip/absence, skim Caddy logs for 401s + LiteLLM spend for the period.

### Phase 7 — Docs sync

- [x] `docs/thor_public_access_model.md` — **done 2026-11-15** (pulled forward with Phase 3; content re-verified 2026-11-15):
  - [x] `llm.choukalos.com` row: auth = Caddy OR-gate (chuck/dylan keys, `X-Api-Key` or `Bearer`), not `$LITELLM_PUBLIC_API_KEY`
  - [x] Key table: current inventory (Phase 3 output) incl. MCP access groups
  - [x] Add master-key-internal-only note (F6) + key-rotation procedure
- [ ] `docs/thor_mcp_architecture.md`: note the 2026-08-25 `allow_all_keys` decision is **superseded** — per-key access groups now (Phase 2). (Still stale as of 2026-11-15: `allow_all_keys: true` described in 3 places, no superseded note.)
- [ ] Update this file: mark phases done with dates as they land; keep the §1 inventory table current.

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

### Open

| # | Question | Notes |
|---|---|---|
| D4 | ufw rules for the two home subnets (`192.168.4.0/24` + `192.168.5.0/24`) | See Phase 5 discussion list — settle before executing |

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
- [ ] Docs updated (Phase 7)

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
