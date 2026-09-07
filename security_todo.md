# Security Plan — LiteLLM Public Access + Homelab Hardening

> Created: 2026-09-06 (audit session 22:09–22:33; plan completed same evening)
> Status: **DRAFT — nothing here is applied yet**
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
| F6 | MED | `LITELLM_MASTER_KEY == LITELLM_API_KEY` (same `sk-cb1678…` token) injected into 6 internal consumers (open-webui, presenton, mcp_knowledge, mcp_mysql, mcp_vision, skill-runner). Master key = proxy admin = all models + all MCP servers. Acceptable *while it stays internal* — which is exactly what Phases 1/4/5 guarantee. | `.env`, `compose/*.yml` | Phase 3 (document) + Phase 8 (internal-service key — decided) |
| F7 | MED | Wide `0.0.0.0` host bindings: MySQL `3306/33060`, Qdrant `6333`, LiteLLM `4000`, SearXNG `8088`, Open WebUI `3000`, monitoring stack `3001/8081/8082/9090/9091/9100`, `mcp_memory 8005`, crawl4ai `11235`. **ufw not running.** | `compose/*.yml`, host | Phase 4/5 |
| F8 | MED | `mcp_memory` (host `:8005`) has **no auth of its own** and falls back to `MEMORY_USER_KEY` (Chuck's key) when the caller sends none → any LAN client can search **Chuck's private memories** unauthenticated. | `compose/compose.mcp.yml`, `mcp/servers/memory/server.py` | Phase 4 |
| F9 | LOW | sshd config not fully verified (password auth / root login status unknown). | host | Phase 5 |
| F10 | LOW | Stale docs: `thor_public_access_model.md` describes a `$LITELLM_PUBLIC_API_KEY` gate and key table that don't match reality. | `docs/` | Phase 7 |
| F11 | INFO | `.env` key consumers confirmed (2026-09-06): `LITELLM_PUBLIC_API_KEY` is **dead** (assigned to an unused variable in `lib/litellm-keys.sh:12`, passed to the litellm-proxy container env but unused; Caddy never used it) → remove. `SIRI_API_KEY` **in use** (`cli/run-skill.sh` legacy mode, `cli/verify_attribution.sh` T7) and `HARNESS_API_KEY` **in use** (open-webui → skill-runner harness) → keep. | `.env`, `lib/litellm-keys.sh`, `cli/*.sh` | Phase 3 |

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
- [ ] Public routes accept only the two family keys (negative-tested with a wrong key)
- [ ] MCP tooling verified working from outside the LAN (Mac Studio on cellular) — confirms the trip story end-to-end
- [ ] Commit + push (config changes are git-tracked)

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

### Phase 0 — Backup & baseline (do first, every time)

- [ ] `git add -A && git commit` (Caddyfile, litellm config, compose, .env is gitignored — copy it separately):
      `cp .env /home/chuck/data/backups/env-$(date +%F).bak && chmod 600 /home/chuck/data/backups/env-$(date +%F).bak`
- [ ] `bash scripts/backup-memory.sh` (Qdrant snapshot)
- [ ] Snapshot LiteLLM key table (read-only):
      `docker exec litellm-db psql -U litellm -d litellm -c "\copy (SELECT key_alias, key_name, user_id, max_budget, rpm_limit, tpm_limit, models FROM \"LiteLLM_VerificationToken\") /tmp/keys-$(date +%F).csv"`
- [ ] Record current port state: `ss -tlnp | grep LISTEN > /tmp/ports-$(date +%F).txt`

### Phase 1 — Caddy key gate on `llm.choukalos.com` (public = chuck/dylan only)

Makes Caddy the first line of defense: even if LiteLLM auth is misconfigured,
only the two family keys can reach the proxy over the public route.

- [ ] Replace the `@llm` block in `caddy/Caddyfile`:

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

- [ ] `docker exec caddy caddy reload --config /etc/caddy/Caddyfile` (or restart the caddy container)
- [ ] Verify (from outside the LAN, e.g. Mac Studio):
  - [ ] `curl -s https://llm.choukalos.com/v1/models -H "X-Api-Key: $LITELLM_KEY_CHUCK"` → 200
  - [ ] same with Dylan's key → 200
  - [ ] same with a wrong key → **401**
  - [ ] no key → **401**
  - [ ] `Authorization: Bearer <chuck key>` → 200
- [ ] Verify `siri.choukalos.com` still works (unchanged): `/siri/*` + `/api/*` with both keys → 200; wrong key → 401.
- [ ] **Note for the future:** the siri route only accepts `X-Api-Key` (not `Bearer`). iOS Shortcuts use `X-Api-Key` — fine today; if a client needs `Bearer` there, mirror the expression above.
- [ ] **Key-rotation procedure (document in Phase 7):** when rotating `LITELLM_KEY_CHUCK`/`LITELLM_KEY_DYLAN`, update `.env` **and** reload Caddy, or the public routes break.

Rollback: restore previous Caddyfile block + reload.

### Phase 2 — Per-key MCP scoping (kill `allow_all_keys`)

With Phase 1 done, the public path only carries chuck/dylan keys — but those
keys currently unlock **all 10 MCP servers**. Scope them explicitly
(default-deny; grant what each key needs).

**Decision matrix (default = both family keys get everything; tighten Dylan's if desired — see §6):**

| MCP server | chuck | dylan | memory-service | default_user_id keys |
|---|---|---|---|---|
| mcp_search, mcp_crawl, mcp_knowledge, mcp_filesystem_readonly, mcp_mysql | ✅ | ✅ | ❌ | ❌ (verify need first) |
| mcp_media, mcp_vision (long GPU jobs) | ✅ | ✅ | ❌ | ❌ |
| mcp_homelab_status (docker ps/logs) | ✅ | ✅ | ❌ | ❌ |
| mcp_filesystem (**write** to workspace) | ✅ | ✅ *(decision point)* | ❌ | ❌ |
| mcp_skills (runs family skills) | ✅ | ✅ | ❌ | ❌ |

Mechanism (LiteLLM v1.92, verified against installed source):

- [ ] Remove `allow_all_keys: true` from **all 10** entries in `litellm/config.yml` (keep `url`, `timeout`, `extra_headers` as-is). Default is `false` = deny.
- [ ] Restart `litellm-proxy` (config reload).
- [ ] Grant via **access group** (single place to manage; API verified present in v1.92):
  1. Get key IDs (hashed `key` field): `curl -s http://localhost:4000/v1/key/info -H "Authorization: Bearer $LITELLM_KEY_CHUCK"` (and Dylan's).
  2. Create group with master key:
     ```bash
     curl -s -X POST http://localhost:4000/v1/access_group \
       -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H "Content-Type: application/json" \
       -d '{
             "access_group_name": "family-mcp-full",
             "description": "Full MCP access for Chuck + Dylan (public keys)",
             "access_mcp_server_ids": ["mcp_search","mcp_knowledge","mcp_crawl","mcp_filesystem_readonly","mcp_mysql","mcp_homelab_status","mcp_filesystem","mcp_media","mcp_vision","mcp_skills"],
             "assigned_key_ids": ["<chuck key hash>","<dylan key hash>"]
           }'
     ```
  3. (If Dylan gets a narrower set: second group `dylan-mcp-scoped` with his subset + his key only; a key in two groups gets the union — so use exactly one group per key.)
- [ ] `memory-service` key: leave with **no** MCP grant (models only) — default-deny covers it.
- [ ] `default_user_id` keys: after Phase 3 identifies them, grant only what each actually needs (likely none — they call chat models, not MCP).
- [ ] **Master key behavior (expected, document it):** proxy-admin keys without an explicit `object_permission` still see all MCP servers (v1.92 code path). That's intentional — internal containers (skill-runner, mcp_*) authenticate with it on the docker network. It never crosses the public path (Phase 1) or the LAN edge (Phases 4/5).
- [ ] Verify per key (each from the public URL, after Phase 1):
  - [ ] `GET /v1/mcp/servers` (or a real tool call) with chuck key → 10 servers visible
  - [ ] with dylan key → matches his grant
  - [ ] with memory-service key (LAN) → **0** MCP servers
  - [ ] negative: a key not in any group → 0 servers / 403 on tool call
- [ ] Smoke-test one tool end-to-end per family (e.g. `mcp_search.search_web` via `llm.choukalos.com` with each key).

Rollback: re-add `allow_all_keys: true` + restart litellm-proxy (or delete the access group).

### Phase 3 — Key hygiene (guardrails, retire orphans + dead key)

- [ ] **Enable spend tracking** (prerequisite for budgets): in `litellm/config.yml` set `disable_spend_logs: false`, `disable_spend_updates: false`; restart litellm-proxy.
- [ ] **Set limits on the two public keys** — family decision (2026-09-06): **no budget cap** (power users). Rate guardrails pending D2b:
  ```bash
  # via /v1/key/update with master key, for each of chuck-remote + dylan-v2:
  #   max_budget: (none — unlimited, family decision)
  #   rpm_limit: TBD (D2b)              # proposal: 120 or none
  #   tpm_limit: TBD (D2b)              # proposal: 400000 or none
  #   max_parallel_requests: TBD (D2b)  # proposal: 8 or none
  ```
- [ ] **Retire the 3 orphaned `default_user_id` keys** (investigation complete 2026-09-06 — see F5: dashboard-created test keys, zero repo references, zero spend):
  - [ ] confirm with Dylan that none of the 3 was pasted into a client (Mac Studio, his device) — plaintext isn't stored on Thor, so this is the only remaining blind spot
  - [ ] **block** (soft, reversible): `./homelab.sh key block <key>` for each
  - [ ] observe a few days — any breakage means someone was using one → unblock + investigate
  - [ ] **delete**: `./homelab.sh key delete <key>`
- [ ] **Retire the dead `.env` key** (consumer check done 2026-09-06):
  - [ ] remove `LITELLM_PUBLIC_API_KEY` from `.env` + `compose/compose.ai-core.yml:34` (env passed to litellm-proxy, unused) + the unused variable at `lib/litellm-keys.sh:12` + the mention in the `homelab.sh` header comment
  - [ ] **keep** `SIRI_API_KEY` (in use: `cli/run-skill.sh` legacy mode, `cli/verify_attribution.sh` T7) and `HARNESS_API_KEY` (in use: open-webui → skill-runner harness) — document their consumers in `docs/thor_public_access_model.md` (Phase 7)
- [ ] **Document master-key usage** (F6): add a note in `docs/thor_public_access_model.md` that `LITELLM_MASTER_KEY == LITELLM_API_KEY` is internal-only by design (docker network + LAN only after Phases 4/5).
- [ ] **Dedicated `internal-service` key** — decided 2026-09-06 (was optional): see **Phase 8**.
- [ ] Re-run the key inventory snapshot (Phase 0 command) and paste the new table into §1 for the record.

Rollback: budgets/limits are per-key DB rows — revert via `/v1/key/update`; `.env` restore from Phase 0 backup.

### Phase 4 — Shrink LAN exposure (rebind / remove host port mappings)

Principle: containers talk over the docker network (`ai-net`); host port
publishing is only for things a human needs from another machine.

| Port (owner) | Current | Action | Verify consumer first |
|---|---|---|---|
| `3306/33060` (mysql) | 0.0.0.0 | bind `192.168.4.54:3306:3306` | skill-runner uses `MYSQL_DB_HOST=thor.local` → THOR_IP binding keeps it working |
| `6333` (qdrant) | 0.0.0.0 | **remove host mapping** (or THOR_IP) | `MEMORY_QDRANT_URL=http://qdrant:6333` = docker DNS; check `compose.mcp.yml` QDRANT_URL too |
| `4000` (litellm-proxy) | 0.0.0.0 | bind `192.168.4.54:4000:4000` | Open WebUI + LAN clients; check open-webui's LITELLM base URL (if it uses `litellm-proxy:4000` via docker net, mapping can be removed) |
| `8088` (searxng) | 0.0.0.0 | **remove host mapping** | mcp_search calls `http://searxng:8080` (docker DNS) — confirm |
| `3000` (open-webui) | 0.0.0.0 | bind `192.168.4.54:3000:8080` | family LAN use |
| `3001` (grafana), `8081` (cadvisor), `8082` (plausible), `9090/9091` (victoria-metrics), `9100` (node-exporter) | 0.0.0.0 | bind to `192.168.4.54:` | monitoring is LAN-admin only |
| `8005` (mcp_memory) | 0.0.0.0, **unauthenticated, falls back to Chuck's key (F8)** | **remove host mapping** | consumers reach it via `mcp_memory:8000` on ai-net (LiteLLM config) — confirm no direct LAN client |
| `11235` (crawl4ai) | 0.0.0.0 | **remove host mapping** | mcp_crawl uses docker DNS — confirm |
| `80/443` (caddy) | 0.0.0.0 | keep | tunnel + LAN |
| `22` (ssh) | 0.0.0.0 | keep; restrict source in Phase 5 | — |

- [ ] For each row: grep the consumer (`grep -rn "<port or service name>" compose/ .env | grep -v ports:`), change the compose `ports:` entry, `docker compose up -d <stack>` (recreate, no data loss — verify after).
- [ ] Re-run `ss -tlnp | grep LISTEN` — expected survivors: `22, 80, 443, 192.168.4.54:{3000,3306,4000,3001,8081,8082,9090,9091,9100,5000,8091}`.
- [ ] Confirm from a LAN client (Mac Studio): Open WebUI, Grafana, `llm.choukalos.com`, `siri.choukalos.com` all still work; confirm from a phone on a *different* network (cellular) that the public routes still work.

Rollback: restore the `ports:` lines from git + recreate.

### Phase 5 — Host firewall (ufw) + SSH hardening

Defense in depth: even if a future service binds 0.0.0.0, only the home LAN
gets in. (Cloudflare Tunnel is outbound from the caddy container — an inbound
deny does **not** break it.)

- [ ] SSH baseline (F9): `sshd -T | grep -iE '^(passwordauthentication|permitrootlogin|kbdinteractiveauthentication|pubkeyauthentication)'`
  - [ ] ensure `passwordauthentication no`, `permitrootlogin no`, `pubkeyauthentication yes` (edit `/etc/ssh/sshd_config.d/`, `systemctl reload ssh`)
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

- [ ] `docs/thor_public_access_model.md`:
  - [ ] `llm.choukalos.com` row: auth = Caddy OR-gate (chuck/dylan keys, `X-Api-Key` or `Bearer`), not `$LITELLM_PUBLIC_API_KEY`
  - [ ] Key table: current inventory (Phase 3 output) incl. MCP access groups
  - [ ] Add master-key-internal-only note (F6) + key-rotation procedure
- [ ] `docs/thor_mcp_architecture.md`: note the 2026-08-25 `allow_all_keys` decision is **superseded** — per-key access groups now (Phase 2).
- [ ] Update this file: mark phases done with dates as they land; keep the §1 inventory table current.

---

### Phase 8 — Dedicated `internal-service` key (decided 2026-09-06)

Goal: internal containers stop using the master key; the master key becomes
admin-only (key management via `./homelab.sh key ...`, dashboard).

Master-key consumers found 2026-09-06 (6 services):
| Service | Env var | Location |
|---|---|---|
| open-webui | `OPENAI_API_KEY=${LITELLM_MASTER_KEY}` | `compose/compose.ai-core.yml:76` |
| presenton | `CUSTOM_LLM_API_KEY=${LITELLM_API_KEY}` | `compose/compose.ai-core.yml:179` |
| mcp_knowledge | `LITELLM_API_KEY=${LITELLM_API_KEY}` | `compose/compose.mcp.yml:22` (embeddings + vision fallback) |
| mcp_mysql | `LITELLM_API_KEY=${LITELLM_API_KEY}` | `compose/compose.mcp.yml:84` (matrix-coder nl→sql) |
| mcp_vision | `LITELLM_API_KEY=${LITELLM_API_KEY}` | `compose/compose.mcp.yml:152` (matrix-coder frame analysis) |
| skill-runner | `LITELLM_API_KEY=${LITELLM_API_KEY}` | `compose/compose.skill-runner.yml:17` |

- [ ] Mint key: `./homelab.sh key add internal-service --alias internal-service` (all models, **no MCP group**, no budget — internal trust; per-service model scoping is a later nicety)
- [ ] Add `LITELLM_KEY_INTERNAL=${sk-...}` to `.env` (Phase 0 backup first)
- [ ] Point each consumer env var above at `${LITELLM_KEY_INTERNAL}` — the litellm-proxy container keeps its own `LITELLM_MASTER_KEY`/`LITELLM_API_KEY` (the proxy needs its master key)
- [ ] Recreate affected containers one stack at a time; verify each (open-webui chat, presenton render, MCP tool calls, skill run)
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
| D5 | Dead `.env` keys | `LITELLM_PUBLIC_API_KEY` = dead → remove. `SIRI_API_KEY` + `HARNESS_API_KEY` = **in use** (CLI, open-webui) → keep |
| D6 | `internal-service` key | **Yes** — formalized as Phase 8 |

### Open

| # | Question | Notes |
|---|---|---|
| D4 | ufw rules for the two home subnets (`192.168.4.0/24` + `192.168.5.0/24`) | See Phase 5 discussion list — settle before executing |
| D2b | Rate guardrails for chuck/dylan: none, or loose (e.g. 120 RPM / 400k TPM / 8 parallel)? | Budget is unlimited; guardrails are anti-abuse-only. Power-user agent sessions (pi, parallel tool calls) can hit 60 RPM, so the original proposal was too tight if we keep any |

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
